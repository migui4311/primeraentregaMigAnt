import json
import os
import time
from datetime import datetime, timezone

from botocore.exceptions import ClientError

# Each consumer log line is one JSON object, so experiment logs can be parsed by
# scripts/metrics.py. Outcomes: processed, duplicate, alert, retry, receive_error.


def log(**fields):
    print(json.dumps(fields), flush=True)


def latency_ms(event_time, now):
    """Milliseconds from the vehicle timestamp to `now`, or None if it cannot be parsed."""
    try:
        sent = datetime.fromisoformat(event_time)
    except (TypeError, ValueError):
        return None
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    return round((now - sent).total_seconds() * 1000)


def process(event, events, alerts, sns, topic, meta=None):
    """Process one SQS message body. Raises to keep the message for an SQS retry."""
    meta = meta or {}
    event_id = event["event_id"]
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("invalid event_id")
    now = datetime.now(timezone.utc)
    latency = latency_ms(event.get("event_time"), now)
    # SentTimestamp is set by SQS, so queue_ms does not depend on the laptop clock.
    sent_ms = meta.get("SentTimestamp")
    queue_ms = round(now.timestamp() * 1000) - int(sent_ms) if sent_ms else None

    # Idempotent registration: a finished event (status "done") cannot be registered
    # again, so a duplicate delivery is detected and counted. An event left in
    # "processing" by a failed attempt can still be retried.
    item = {"event_id": event_id, "event": json.dumps(event), "status": "processing",
            "processed_at": now.isoformat()}
    if latency is not None:
        item["latency_ms"] = latency
    try:
        events.put_item(Item=item,
                        ConditionExpression="attribute_not_exists(event_id) OR #s <> :done",
                        ExpressionAttributeNames={"#s": "status"},
                        ExpressionAttributeValues={":done": "done"})
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        log(outcome="duplicate", event_id=event_id, event_type=event.get("event_type"),
            source_id=event.get("source_id"), receive_count=meta.get("ApproximateReceiveCount"))
        return "duplicate"

    if event["event_type"] == "peligro_carretera":
        alert_id = f"cloud-{event_id}"
        key = {"alert_id": alert_id}
        if not alerts.get_item(Key=key, ConsistentRead=True).get("Item"):
            alert = {**key, "event_id": event_id, "origin": "cloud",
                     "rule": event["event_type"], "location": event["location"],
                     "event_time": event.get("event_time")}
            sns.publish(TopicArn=topic, Message=json.dumps(alert))
            alerts.put_item(Item={**key, "alert": json.dumps(alert)})
            log(outcome="alert", alert_id=alert_id, event_id=event_id, location=event["location"])

    events.update_item(Key={"event_id": event_id}, UpdateExpression="SET #s = :done",
                       ExpressionAttributeNames={"#s": "status"},
                       ExpressionAttributeValues={":done": "done"})
    log(outcome="processed", event_id=event_id, event_type=event.get("event_type"),
        source_id=event.get("source_id"), rsu_id=event.get("rsu_id"),
        event_time=event.get("event_time"), processed_at=now.isoformat(),
        latency_ms=latency, queue_ms=queue_ms, receive_count=meta.get("ApproximateReceiveCount"))
    return "processed"


def main():
    import boto3

    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-east-1"))
    queue = sqs.get_queue_url(QueueName=os.getenv("QUEUE_NAME", "v2x-events"))["QueueUrl"]
    db = boto3.resource("dynamodb", region_name=sqs.meta.region_name)
    sns = boto3.client("sns", region_name=sqs.meta.region_name)
    topic = os.environ["TOPIC_ARN"]
    while True:
        try:
            messages = sqs.receive_message(
                QueueUrl=queue, WaitTimeSeconds=20, MaxNumberOfMessages=10,
                AttributeNames=["SentTimestamp", "ApproximateReceiveCount"]).get("Messages", [])
            for message in messages:
                meta = message.get("Attributes", {})
                try:
                    process(json.loads(message["Body"]), db.Table("v2x-events"),
                            db.Table("v2x-alerts"), sns, topic, meta)
                    sqs.delete_message(QueueUrl=queue, ReceiptHandle=message["ReceiptHandle"])
                except Exception as error:
                    log(outcome="retry", error=f"{type(error).__name__}: {error}",
                        message_id=message.get("MessageId"),
                        receive_count=meta.get("ApproximateReceiveCount"))
        except Exception as error:
            log(outcome="receive_error", error=f"{type(error).__name__}: {error}")
            time.sleep(5)


if __name__ == "__main__":
    main()
