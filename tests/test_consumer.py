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
