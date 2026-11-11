import base64
import json
import os
import re
import sqlite3
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import boto3
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from paho.mqtt import client as mqtt


def verify(envelope, topic, region):
    if envelope["TopicArn"] != topic:
        raise ValueError("unexpected topic")
    url = envelope["SigningCertURL"]
    host = re.escape(f"sns.{region}.amazonaws.com")
    if not re.fullmatch(rf"https://{host}/SimpleNotificationService-[a-fA-F0-9]+\.pem", url):
        raise ValueError("invalid certificate URL")
    kind = envelope["Type"]
    fields = ["Message", "MessageId"]
    if kind == "Notification":
        if "Subject" in envelope:
            fields.append("Subject")
        fields.extend(["Timestamp", "TopicArn", "Type"])
    elif kind == "SubscriptionConfirmation":
        fields.extend(["SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"])
    else:
        raise ValueError("unsupported SNS message type")
    body = "".join(f"{key}\n{envelope[key]}\n" for key in fields).encode()
    version = envelope["SignatureVersion"]
    digest = {"1": hashes.SHA1, "2": hashes.SHA256}[version]()
    # Connect directly to the validated SNS host without following redirects.
    from http.client import HTTPSConnection
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    connection = HTTPSConnection(parsed.hostname, timeout=5)
    try:
        connection.request("GET", parsed.path)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("SNS certificate retrieval failed")
        cert = x509.load_pem_x509_certificate(response.read(16384))
    finally:
        connection.close()
    cert.public_key().verify(base64.b64decode(envelope["Signature"], validate=True),
                             body, padding.PKCS1v15(), digest)


def main():
    rsu = os.environ["RSU_ID"]
    region = os.getenv("AWS_REGION", "us-east-1")
    topic = os.environ["TOPIC_ARN"]
    sqs = boto3.client("sqs", region_name=region)
    sns = boto3.client("sns", region_name=region)
    queue = os.environ["QUEUE_URL"]
    state = Path("/state/outbox.db")
    state.parent.mkdir(exist_ok=True)
    with sqlite3.connect(state) as db:
        db.executescript("CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, body TEXT);"
                         "CREATE TABLE IF NOT EXISTS delivered (id TEXT PRIMARY KEY);")
    broker = subprocess.Popen(["mosquitto", "-c", "mosquitto.conf"])
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    last_routine = {}
    alert_topic = f"v2x/{rsu}/alerts"

    def receive(client, _, message):
        try:
            event = json.loads(message.payload)
            event_id = event["event_id"]
            source = event["source_id"]
            kind = event["event_type"]
            if (event["rsu_id"] != rsu or kind not in {"rutina", "frenado brusco", "peligro_carretera"}
                    or not all(isinstance(event[key], str) and event[key]
                               for key in ("event_id", "source_id", "event_time", "location"))
                    or not isinstance(event["payload"], dict)):
                raise ValueError("invalid event")
            now = time.monotonic()
            if kind == "rutina" and now - last_routine.get(source, -10) < 5:
                return
            with sqlite3.connect(state) as db:
                if kind == "frenado brusco":
                    alert_id = f"local-{event_id}"
                    if db.execute("INSERT OR IGNORE INTO delivered VALUES (?)", (alert_id,)).rowcount:
                        client.publish(alert_topic, json.dumps({"alert_id": alert_id,
                                       "event_id": event_id, "origin": rsu, "rule": kind}), qos=1)
                if db.execute("SELECT count(*) FROM outbox").fetchone()[0] >= 10000:
                    print(f"Outbox full, rejected {event_id}", flush=True)
                    return
                db.execute("INSERT OR IGNORE INTO outbox VALUES (?, ?)", (event_id, message.payload))
            if kind == "rutina":
                last_routine[source] = now
        except (KeyError, ValueError, TypeError, sqlite3.Error) as error:
            print(f"Rejected event: {error}", flush=True)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/health" and client.is_connected() else 503)
            self.end_headers()

        def do_POST(self):
            try:
                length = int(self.headers["Content-Length"])
                if self.path != "/sns" or not 0 < length <= 262144:
                    raise ValueError("invalid request")
                envelope = json.loads(self.rfile.read(length))
                verify(envelope, topic, region)
                if envelope["Type"] == "SubscriptionConfirmation":
                    sns.confirm_subscription(TopicArn=topic, Token=envelope["Token"])
                else:
                    alert = json.loads(envelope["Message"])
                    with sqlite3.connect(state) as db:
                        if db.execute("INSERT OR IGNORE INTO delivered VALUES (?)",
                                      (alert["alert_id"],)).rowcount:
                            result = client.publish(alert_topic, json.dumps(alert), qos=1)
                            result.wait_for_publish(timeout=5)
                            if not result.is_published():
                                raise RuntimeError("MQTT publish timed out")
                self.send_response(200)
            except Exception as error:
                print(f"SNS delivery failed: {type(error).__name__}", flush=True)
                self.send_response(503)
            self.end_headers()

    try:
        client.on_message = receive
        client.on_connect = lambda c, *_: c.subscribe(f"v2x/{rsu}/events", qos=1)
        client.connect_async("127.0.0.1")
        client.loop_start()
        server = HTTPServer(("0.0.0.0", 8080), Handler)
        Thread(target=server.serve_forever, daemon=True).start()
        delay = 1
        while broker.poll() is None:
            with sqlite3.connect(state) as db:
                row = db.execute("SELECT id, body FROM outbox ORDER BY rowid LIMIT 1").fetchone()
            if row is None:
                time.sleep(0.25)
                continue
            try:
                sqs.send_message(QueueUrl=queue, MessageBody=row[1].decode())
            except Exception as error:
                print(f"Retrying buffered event {row[0]}: {error}", flush=True)
                time.sleep(delay)
                delay = min(delay * 2, 10)
                continue
            with sqlite3.connect(state) as db:
                db.execute("DELETE FROM outbox WHERE id = ?", (row[0],))
            delay = 1
        raise RuntimeError("MQTT broker stopped")
    finally:
        client.loop_stop()
        if broker.poll() is None:
            broker.terminate()
            broker.wait(timeout=5)


if __name__ == "__main__":
    main()
