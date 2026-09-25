import json
import unittest
from pathlib import Path

from src.validator import validate_event
from tests.helpers import approve_and_distribute, draft_and_check, make_service, sign_both


class ContractTest(unittest.TestCase):
    def test_sample_matches_envelope(self) -> None:
        sample = json.loads((Path(__file__).parents[1] / "data" / "sample.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_event(sample), [])


class ServiceEnvelopeTest(unittest.TestCase):
    def test_emitted_events_match_contract(self) -> None:
        service = make_service()
        draft_and_check(service, "VAR-GYN-01")
        sign_both(service, "VAR-GYN-01")
        approve_and_distribute(service, "VAR-GYN-01")
        result = service.update_evidence(
            "STU-HT-001",
            kind="retraction",
            endpoints="all",
            rationale="论文撤稿",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        service.confirm_receipt(
            result["notices"][0], department="妇科门诊", occurred_at="2026-09-10T12:00:00+08:00"
        )
        events = service.log.all()
        self.assertGreater(len(events), 0)
        for event in events:
            self.assertEqual(validate_event(event.as_dict()), [], event.event_id)
        # 事件标识全局递增，聚合版本各自递增。
        self.assertEqual(
            [e.event_id for e in events], [f"evt-{i:06d}" for i in range(1, len(events) + 1)]
        )
        per_aggregate: dict[str, list[int]] = {}
        for event in events:
            per_aggregate.setdefault(event.aggregate_id, []).append(event.version)
        for versions in per_aggregate.values():
            self.assertEqual(versions, list(range(1, len(versions) + 1)))


if __name__ == "__main__":
    unittest.main()
