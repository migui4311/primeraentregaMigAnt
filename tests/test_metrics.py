import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from metrics import percentile, summarize  # noqa: E402


class MetricsTest(unittest.TestCase):
    def test_percentile_nearest_rank(self):
        self.assertEqual(percentile(list(range(1, 101)), 95), 95)
        self.assertEqual(percentile([10], 95), 10)
        self.assertIsNone(percentile([], 95))

    def test_summary_counts(self):
        sim = [
            {"outcome": "sent", "event_id": "a", "event_type": "peligro_carretera"},
            {"outcome": "sent", "event_id": "a", "event_type": "peligro_carretera"},  # duplicated publish
            {"outcome": "sent", "event_id": "b", "event_type": "frenado brusco"},       # never processed
            {"outcome": "sent", "event_id": "c", "event_type": "rutina"},               # filtered at RSU
        ]
        consumer = [
            {"outcome": "processed", "event_id": "a", "event_type": "peligro_carretera",
             "latency_ms": 120, "queue_ms": 30},
            {"outcome": "duplicate", "event_id": "a"},
            {"outcome": "alert", "alert_id": "cloud-a"},
            {"outcome": "retry", "message_id": "m1"},
        ]
        result = summarize(sim, consumer, [{"event_id": "a", "status": "done"}])
        self.assertEqual(result["simulator"], {"publishes": 4, "unique_events": 3, "duplicated_by_simulator": 1})
        self.assertEqual(result["consumer"]["duplicates_detected"], 1)
        self.assertEqual(result["consumer"]["retries"], 1)
        self.assertEqual(result["consumer"]["cloud_alerts"], 1)
        self.assertEqual(result["lost_event_ids"], ["b"])  # routine "c" is not counted as lost
        self.assertEqual(result["latency_ms"]["p95"], 120)
        self.assertTrue(result["final_state"]["consistent"])


if __name__ == "__main__":
    unittest.main()
