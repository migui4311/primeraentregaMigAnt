import unittest
from unittest.mock import Mock

from adminalertas import process


class ConsumerTest(unittest.TestCase):
    def setUp(self):
        self.events = Mock()
        self.alerts = Mock()
        self.alerts.get_item.return_value = {}
        self.sns = Mock()
        self.event = {"event_id": "sample", "event_type": "peligro_carretera", "location": "segmento_1"}

    def process(self):
        process(self.event, self.events, self.alerts, self.sns, "topic")

    def test_hazard_is_persisted_and_published(self):
        self.process()
        self.events.put_item.assert_called_once()
        self.sns.publish.assert_called_once()
        self.alerts.put_item.assert_called_once()

    def test_duplicate_alert_is_not_published(self):
        self.alerts.get_item.return_value = {"Item": {"alert_id": "cloud-sample"}}
        self.process()
        self.sns.publish.assert_not_called()

    def test_failed_publish_can_be_retried(self):
        self.sns.publish.side_effect = [RuntimeError("offline"), {}]
        with self.assertRaises(RuntimeError):
            self.process()
        self.alerts.put_item.assert_not_called()
        self.process()
        self.alerts.put_item.assert_called_once()


class IdempotencyAndLatencyTest(unittest.TestCase):
    def setUp(self):
        self.events = Mock()
        self.alerts = Mock()
        self.alerts.get_item.return_value = {}
        self.sns = Mock()

    def run_process(self, event, meta=None):
        return process(event, self.events, self.alerts, self.sns, "topic", meta)

    def test_finished_event_is_counted_as_duplicate(self):
        from botocore.exceptions import ClientError
        self.events.put_item.side_effect = ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        event = {"event_id": "dup", "event_type": "peligro_carretera", "location": "segmento_1"}
        self.assertEqual(self.run_process(event), "duplicate")
        self.sns.publish.assert_not_called()
        self.events.update_item.assert_not_called()

    def test_other_dynamodb_errors_are_retried(self):
        from botocore.exceptions import ClientError
        self.events.put_item.side_effect = ClientError(
            {"Error": {"Code": "ProvisionedThroughputExceededException"}}, "PutItem")
        with self.assertRaises(ClientError):
            self.run_process({"event_id": "x", "event_type": "rutina", "location": "s"})

    def test_registration_is_conditional_and_marked_done(self):
        self.assertEqual(self.run_process({"event_id": "new", "event_type": "rutina", "location": "s"}),
                         "processed")
        kwargs = self.events.put_item.call_args.kwargs
        self.assertIn("attribute_not_exists(event_id)", kwargs["ConditionExpression"])
        self.assertEqual(kwargs["Item"]["status"], "processing")
        self.assertEqual(self.events.update_item.call_args.kwargs["ExpressionAttributeValues"],
                         {":done": "done"})

    def test_latency_is_logged_and_stored(self):
        import io
        import json
        from contextlib import redirect_stdout
        from datetime import datetime, timedelta, timezone
        sent = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
        sqs_sent = int((datetime.now(timezone.utc) - timedelta(seconds=1)).timestamp() * 1000)
        output = io.StringIO()
        with redirect_stdout(output):
            self.run_process({"event_id": "lat", "event_type": "rutina", "location": "s", "event_time": sent},
                             {"SentTimestamp": str(sqs_sent), "ApproximateReceiveCount": "1"})
        line = json.loads(output.getvalue().strip().splitlines()[-1])
        self.assertEqual(line["outcome"], "processed")
        self.assertTrue(1900 <= line["latency_ms"] <= 4000)
        self.assertTrue(900 <= line["queue_ms"] <= 3000)
        self.assertEqual(self.events.put_item.call_args.kwargs["Item"]["latency_ms"], line["latency_ms"])

    def test_missing_event_time_does_not_fail(self):
        self.assertEqual(self.run_process({"event_id": "no-time", "event_type": "rutina", "location": "s"}),
                         "processed")
