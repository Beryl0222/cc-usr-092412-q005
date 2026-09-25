import json
import unittest
from pathlib import Path

from src.events import make_event, validate_envelope
from src.validator import validate_event


class ContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sample = json.loads(
            (Path(__file__).parents[1] / "data" / "sample.json").read_text(encoding="utf-8")
        )

    def test_sample_matches_envelope(self) -> None:
        self.assertEqual(validate_event(self.sample), [])
        self.assertEqual(validate_envelope(self.sample), [])

    def test_sample_payload_round_trips_through_constructor(self) -> None:
        record = self.sample
        event = make_event(
            event_id=record["event_id"],
            event_type=record["event_type"],
            aggregate_type=record["aggregate_type"],
            aggregate_id=record["aggregate_id"],
            occurred_at=record["occurred_at"],
            version=record["version"],
            summary=record["summary"],
            payload=record["payload"],
        )
        self.assertEqual(event["payload"]["study_version"], 1)
        self.assertEqual(event["payload"]["not_applicable"][0], "乳腺癌病史")


if __name__ == "__main__":
    unittest.main()
