"""信封校验：枚举取值与时间格式。"""

import json
import unittest
from pathlib import Path

from src.validator import validate_event

SAMPLE = json.loads(
    (Path(__file__).parents[1] / "data" / "sample.json").read_text(encoding="utf-8")
)


class ValidatorTest(unittest.TestCase):
    def _with(self, **changes) -> dict:
        record = dict(SAMPLE)
        record.update(changes)
        return record

    def test_unknown_event_type_rejected(self) -> None:
        errors = validate_event(self._with(event_type="NOPE"))
        self.assertTrue(any("event_type" in e for e in errors))

    def test_unknown_aggregate_type_rejected(self) -> None:
        errors = validate_event(self._with(aggregate_type="unknown"))
        self.assertTrue(any("aggregate_type" in e for e in errors))

    def test_naive_occurred_at_rejected(self) -> None:
        errors = validate_event(self._with(occurred_at="2026-09-20 18:00:00"))
        self.assertTrue(any("时区" in e for e in errors))

    def test_bad_version_rejected(self) -> None:
        self.assertTrue(validate_event(self._with(version=0)))
        self.assertTrue(validate_event(self._with(version="1")))
        self.assertTrue(validate_event(self._with(version=True)))


if __name__ == "__main__":
    unittest.main()
