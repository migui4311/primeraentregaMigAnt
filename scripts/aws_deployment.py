import argparse
import json
import shlex
import time

import boto3


def wait_for_ssm(session, instances, timeout=900):
    """New instances need a few minutes before Systems Manager can run commands on them."""
    ssm = session.client("ssm")
    deadline = time.time() + timeout
    while True:
        info = ssm.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": list(instances)}])["InstanceInformationList"]
        missing = set(instances) - {item["InstanceId"] for item in info if item["PingStatus"] == "Online"}
        if not missing:
            return
        if time.time() > deadline:
            raise RuntimeError(f"Instances not online in Systems Manager: {sorted(missing)}")
        print(f"Waiting for Systems Manager: {sorted(missing)}", flush=True)
        time.sleep(15)


def rollout(session, bucket, revision, instances, topic, queue):
    wait_for_ssm(session, instances)
    ssm = session.client("ssm")
    pending = {}
    for index, instance in enumerate(instances):
        name = "v2x-rsu" if index else "v2x-service"
        source = shlex.quote(f"s3://{bucket}/releases/{revision}/{name}")
        options = ["-e", f"TOPIC_ARN={topic}", "-e", f"QUEUE_URL={queue}"]
        if index:
            options += ["-e", f"RSU_ID=rsu-{index}", "-p", "1883:1883", "-p", "8080:8080",
                        "-v", "v2x-rsu-state:/state"]
        args = shlex.join(options + [f"{name}:{revision}"])
        health = "curl -fsS http://localhost:8080/health" if index else (
            "test \"$(docker inspect -f '{{.State.Status}} {{.RestartCount}}' v2x-service)\" = 'running 0'")
        commands = [
            "set -eu",
            # On a new instance, wait until the user data has installed Docker.
            "cloud-init status --wait >/dev/null 2>&1 || true",
            "command -v docker >/dev/null || { echo 'Docker is not installed yet' >&2; exit 1; }",
            "work=$(mktemp -d)", "trap 'rm -rf -- \"$work\"' EXIT", 'cd "$work"',
            f"aws s3 cp {source}.tar.gz {name}.tar.gz",
            f"aws s3 cp {source}.sha256 {name}.sha256",
            f"sha256sum -c {name}.sha256", f"docker load -i {name}.tar.gz",
            f"if docker inspect {name} >/dev/null 2>&1; then docker stop {name}; "
            f"docker rename {name} {name}-previous; fi",
            f"if docker run -d --restart unless-stopped --name {name} {args} && sleep 8 && {health}; then "
            f"docker rm {name}-previous 2>/dev/null || true; else "
            f"docker logs --tail 30 {name} || true; docker rm -f {name} || true; "
            f"if docker inspect {name}-previous >/dev/null 2>&1; then "
            f"docker rename {name}-previous {name}; docker start {name}; fi; exit 1; fi",
        ]
        pending[instance] = ssm.send_command(InstanceIds=[instance],
            DocumentName="AWS-RunShellScript", Parameters={"commands": commands,
                                                            "executionTimeout": ["600"]})["Command"]["CommandId"]
    failed = []
    for _ in range(75):
        for instance, command in list(pending.items()):
            try:
                result = ssm.get_command_invocation(CommandId=command, InstanceId=instance)
            except ssm.exceptions.InvocationDoesNotExist:
                continue
            status = result["Status"]
            if status in {"Pending", "InProgress", "Delayed", "Cancelling"}:
                continue
            print(instance, command, status, result.get("StandardErrorContent", ""))
            if status != "Success":
                failed.append(instance)
            del pending[instance]
        if not pending:
            break
        time.sleep(8)
    if pending or failed:
        raise RuntimeError(f"Failed: {failed}. Still pending: {pending}")


def subscribe(session, topic, rsu_instances):
    """Subscribe each RSU's current public IP to SNS and remove endpoints of old IPs."""
    ec2 = session.client("ec2")
    sns = session.client("sns")
    reservations = ec2.describe_instances(InstanceIds=rsu_instances)["Reservations"]
    # describe_instances does not keep the requested order: map by ID so rsu-1 stays first.
    ip_by_id = {instance["InstanceId"]: instance.get("PublicIpAddress")
                for r in reservations for instance in r["Instances"]}
    ips = [ip_by_id.get(instance_id) for instance_id in rsu_instances]
    if not all(ips):
        raise RuntimeError("Every RSU instance needs a public IPv4 address")
    wanted = {f"http://{ip}:8080/sns" for ip in ips}
    current = []
    for page in sns.get_paginator("list_subscriptions_by_topic").paginate(TopicArn=topic):
        current += page["Subscriptions"]
    for item in current:
        confirmed = item["SubscriptionArn"].startswith("arn:")
        if item["Protocol"] == "http" and item["Endpoint"] not in wanted and confirmed:
            sns.unsubscribe(SubscriptionArn=item["SubscriptionArn"])
            print(f"Removed stale subscription {item['Endpoint']}")
    confirmed = {item["Endpoint"] for item in current if item["SubscriptionArn"].startswith("arn:")}
    for endpoint in sorted(wanted):
        if endpoint in confirmed:
            print(f"Already subscribed {endpoint}")
        else:
            sns.subscribe(TopicArn=topic, Protocol="http", Endpoint=endpoint)
            print(f"Subscribed {endpoint} (the RSU confirms it)")
    for index, (instance_id, ip) in enumerate(zip(rsu_instances, ips), 1):
        print(f"rsu-{index}: {ip} ({instance_id})")
    print("Simulator: python local_files/coches.py --rsu " + " ".join(ips))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile")
    parser.add_argument("--account", default="364733575524")
    commands = parser.add_subparsers(dest="command", required=True)
    deploy = commands.add_parser("deploy", help="deploy to existing resources")
    deploy.add_argument("--bucket", required=True)
    deploy.add_argument("--revision", required=True)
    deploy.add_argument("--instances", nargs=3, required=True, metavar=("SERVICE", "RSU1", "RSU2"))
    deploy.add_argument("--topic", required=True)
    deploy.add_argument("--queue", required=True)
    alerts = commands.add_parser("subscribe", help="subscribe both RSUs to v2x-alerts")
    alerts.add_argument("--topic", required=True)
    alerts.add_argument("--instances", nargs=2, required=True, metavar=("RSU1", "RSU2"))
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name="us-east-1")
    account = session.client("sts").get_caller_identity()["Account"]
    if account != args.account:
        parser.error("AWS identity does not match deployment account")
    if args.command == "deploy":
        rollout(session, args.bucket, args.revision, args.instances, args.topic, args.queue)
    else:
        subscribe(session, args.topic, args.instances)


if __name__ == "__main__":
    main()
