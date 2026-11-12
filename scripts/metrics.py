"""Experiment measurements for the V2X system.

summary: combine simulator output and consumer logs into the counts the assignment asks for.

    python local_files/coches.py --rsu IP1 IP2 ... > sim.log
    python scripts/metrics.py --profile miguel logs --since 15m --out consumer.log
    python scripts/metrics.py --profile miguel logs --since 15m --instance v2x-rsu-1 --out rsu1.log
    python scripts/metrics.py --profile miguel logs --since 15m --instance v2x-rsu-2 --out rsu2.log
    python scripts/metrics.py --profile miguel summary --sim sim.log --consumer consumer.log \
        --rsu rsu1.log rsu2.log --dynamodb

logs: download `docker logs` from one of the three EC2 instances through Systems Manager
(the output goes through the artifact bucket, so long logs are not truncated).

queue: sample SQS queue depth every N seconds into a CSV (component-failure experiment).

    python scripts/metrics.py --profile miguel queue --interval 5 --out queue.csv

--profile is optional (omit it in CloudShell or when using default credentials).
"""
import argparse
import csv
import json
import math
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

RSU_FILTERED_TYPES = {"rutina"}  # the RSU forwards at most one routine event per vehicle every 5 s


def percentile(values, p):
    """Nearest-rank percentile, or None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def read_json_lines(path):
    """JSON objects from a log file, skipping non-JSON lines (MQTT alerts are printed too)."""
    rows = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def summarize(sim_rows, consumer_rows, db_items=None, rsu_rows=None):
    sent = [r for r in sim_rows if r.get("outcome") == "sent"]
    sent_types = {}
    sent_rsu = {}
    publishes = Counter()
    for r in sent:
        publishes[r["event_id"]] += 1
        sent_types[r["event_id"]] = r.get("event_type")
        sent_rsu[r["event_id"]] = r.get("rsu_id")

    processed = {}
    duplicates = Counter()
    retries = Counter()
    alerts = set()
    for r in consumer_rows:
        outcome = r.get("outcome")
        if outcome == "processed":
            processed.setdefault(r["event_id"], r)
        elif outcome == "duplicate":
            duplicates[r["event_id"]] += 1
        elif outcome == "retry":
            retries[r.get("message_id")] += 1
        elif outcome == "alert":
            alerts.add(r["alert_id"])

    per_type = defaultdict(lambda: Counter())
    for event_id, kind in sent_types.items():
        per_type[kind]["sent_unique"] += 1
        per_type[kind]["processed"] += event_id in processed
    per_rsu = defaultdict(lambda: Counter())
    for event_id, rsu in sent_rsu.items():
        per_rsu[rsu]["sent_unique"] += 1
        per_rsu[rsu]["processed"] += event_id in processed
    for event_id, row in processed.items():
        if event_id not in sent_types:
            per_type[row.get("event_type")]["processed_not_in_sim_log"] += 1

    # Routine events are filtered at the edge by design, so only alert-capable types
    # can be "lost": sent by a vehicle but never processed in the cloud.
    lost = sorted(e for e, k in sent_types.items() if k not in RSU_FILTERED_TYPES and e not in processed)
    latency = [r["latency_ms"] for r in processed.values() if r.get("latency_ms") is not None]
    queue = [r["queue_ms"] for r in processed.values() if r.get("queue_ms") is not None]

    result = {
        "simulator": {
            "publishes": sum(publishes.values()),
            "unique_events": len(publishes),
            "duplicated_by_simulator": sum(1 for n in publishes.values() if n > 1),
        },
        "consumer": {
            "processed_unique": len(processed),
            "duplicates_detected": sum(duplicates.values()),
            "retries": sum(retries.values()),
            "cloud_alerts": len(alerts),
        },
        "per_event_type": {k: dict(v) for k, v in sorted(per_type.items(), key=lambda kv: str(kv[0]))},
        "per_rsu": {k: dict(v) for k, v in sorted(per_rsu.items(), key=lambda kv: str(kv[0]))},
        "lost_alert_capable_events": len(lost),
        "lost_event_ids": lost[:20],
        "latency_ms": {
            "count": len(latency),
            "p50": percentile(latency, 50),
            "p95": percentile(latency, 95),
            "max": max(latency) if latency else None,
        },
        "queue_ms": {
            "count": len(queue),
            "p50": percentile(queue, 50),
            "p95": percentile(queue, 95),
            "max": max(queue) if queue else None,
        },
    }
    if rsu_rows is not None:
        edge = Counter()
        for r in rsu_rows:
            if r.get("outcome") == "duplicate":
                edge[r.get("rsu_id")] += 1
        result["rsu_duplicates_absorbed"] = dict(edge)
        result["duplicates_detected_total"] = sum(edge.values()) + result["consumer"]["duplicates_detected"]
    if db_items is not None:
        stored = {item["event_id"]: item for item in db_items}
        done = {e for e, item in stored.items() if item.get("status") == "done"}
        result["final_state"] = {
            "dynamodb_events": len(stored),
            "dynamodb_done": len(done),
            "processed_in_logs_missing_in_db": len(set(processed) - set(stored)),
            "consistent": set(processed) <= done,
        }
    return result


def scan_events(session):
    table = session.resource("dynamodb").Table("v2x-events")
    items, kwargs = [], {"ProjectionExpression": "event_id, #s", "ExpressionAttributeNames": {"#s": "status"}}
    while True:
        page = table.scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def sample_queue(session, interval, out, duration):
    sqs = session.client("sqs")
    names = ["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]
    queues = {name: sqs.get_queue_url(QueueName=name)["QueueUrl"] for name in ("v2x-events", "v2x-events-dlq")}
    start = time.time()
    with open(out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "elapsed_s", "visible", "in_flight", "dlq_visible"])
        while not duration or time.time() - start < duration:
            main = sqs.get_queue_attributes(QueueUrl=queues["v2x-events"], AttributeNames=names)["Attributes"]
            dlq = sqs.get_queue_attributes(QueueUrl=queues["v2x-events-dlq"], AttributeNames=names[:1])["Attributes"]
            row = [datetime.now(timezone.utc).isoformat(), round(time.time() - start),
                   main[names[0]], main[names[1]], dlq[names[0]]]
            writer.writerow(row)
            handle.flush()
            print(*row, flush=True)
            time.sleep(interval)


def fetch_logs(session, out, since, name="v2x-service"):
    import shlex
    account = session.client("sts").get_caller_identity()["Account"]
    bucket = f"v2x-artifacts-{account}-us-east-1"
    reservations = session.client("ec2").describe_instances(Filters=[
        {"Name": "tag:Name", "Values": [name]},
        {"Name": "instance-state-name", "Values": ["running"]}])["Reservations"]
    instances = [i["InstanceId"] for r in reservations for i in r["Instances"]]
    if len(instances) != 1:
        raise SystemExit(f"Expected one running {name} instance, found {instances}")
    instance = instances[0]
    container = "v2x-service" if name == "v2x-service" else "v2x-rsu"
    command = f"docker logs {container}" + (f" --since {shlex.quote(since)}" if since else "") + " 2>&1"
    ssm = session.client("ssm")
    command_id = ssm.send_command(InstanceIds=[instance], DocumentName="AWS-RunShellScript",
                                  Parameters={"commands": [command]},
                                  OutputS3BucketName=bucket, OutputS3KeyPrefix="logs")["Command"]["CommandId"]
    for _ in range(60):
        time.sleep(3)
        try:
            status = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance)["Status"]
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        if status not in {"Pending", "InProgress", "Delayed"}:
            break
    if status != "Success":
        raise SystemExit(f"docker logs command finished with status {status}")
    key = f"logs/{command_id}/{instance}/awsrunShellScript/0.awsrunShellScript/stdout"
    session.client("s3").download_file(bucket, key, out)
    print(f"Saved {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile")
    commands = parser.add_subparsers(dest="command", required=True)
    summary = commands.add_parser("summary")
    summary.add_argument("--sim", required=True, help="simulator output")
    summary.add_argument("--consumer", required=True, help="docker logs of v2x-service")
    summary.add_argument("--rsu", nargs="*", default=None, help="docker logs of the RSUs (edge duplicates)")
    summary.add_argument("--dynamodb", action="store_true", help="also check final state in DynamoDB")
    logs = commands.add_parser("logs")
    logs.add_argument("--since", help="docker logs --since value, e.g. 15m or 2026-11-13T10:00:00")
    logs.add_argument("--instance", default="v2x-service", choices=["v2x-service", "v2x-rsu-1", "v2x-rsu-2"])
    logs.add_argument("--out", default="consumer.log")
    queue = commands.add_parser("queue")
    queue.add_argument("--interval", type=float, default=5)
    queue.add_argument("--duration", type=float, default=0, help="seconds, 0 = until Ctrl+C")
    queue.add_argument("--out", default="queue.csv")
    args = parser.parse_args()

    session = None
    if args.command in {"queue", "logs"} or getattr(args, "dynamodb", False):
        import boto3
        session = boto3.Session(profile_name=args.profile, region_name="us-east-1")

    if args.command == "summary":
        items = scan_events(session) if args.dynamodb else None
        rsu_rows = [row for path in args.rsu for row in read_json_lines(path)] if args.rsu is not None else None
        result = summarize(read_json_lines(args.sim), read_json_lines(args.consumer), items, rsu_rows)
        print(json.dumps(result, indent=2, default=str))
    elif args.command == "logs":
        fetch_logs(session, args.out, args.since, args.instance)
    else:
        try:
            sample_queue(session, args.interval, args.out, args.duration)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
