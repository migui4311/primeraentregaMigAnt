import json
import os



def process(event, events, alerts, sns, topic):
    event_id = event["event_id"]
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("invalid event_id")
    events.put_item(Item={"event_id": event_id, "event": json.dumps(event)})
    if event["event_type"] == "peligro_carretera":
        alert_id = f"cloud-{event_id}"
        key = {"alert_id": alert_id}
        if alerts.get_item(Key=key, ConsistentRead=True).get("Item"):
            return
        alert = {**key, "event_id": event_id, "origin": "cloud",
                 "rule": event["event_type"], "location": event["location"]}
        sns.publish(TopicArn=topic, Message=json.dumps(alert))
        alerts.put_item(Item={**key, "alert": json.dumps(alert)})
    print(json.dumps({"outcome": "processed", "event_id": event_id}), flush=True)


def main():
    import boto3

    sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-east-1"))
    queue = sqs.get_queue_url(QueueName=os.getenv("QUEUE_NAME", "v2x-events"))["QueueUrl"]
    db = boto3.resource("dynamodb", region_name=sqs.meta.region_name)
    sns = boto3.client("sns", region_name=sqs.meta.region_name)
    topic = os.environ["TOPIC_ARN"]
    while True:
        try:
            messages = sqs.receive_message(QueueUrl=queue, WaitTimeSeconds=20,
                                           MaxNumberOfMessages=10).get("Messages", [])
            for message in messages:
                try:
                    process(json.loads(message["Body"]), db.Table("v2x-events"),
                            db.Table("v2x-alerts"), sns, topic)
                    sqs.delete_message(QueueUrl=queue, ReceiptHandle=message["ReceiptHandle"])
                except Exception as error:
                    print(f"Message retained for retry: {error}", flush=True)
        except Exception as error:
            import time
            print(f"Receive failed: {error}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
