"""历史时点解释与公开表述溯源。"""

import unittest

from src.queries import explain_at, trace
from tests.helpers import (
    LIMITATIONS,
    approve_and_distribute,
    draft_and_check,
    make_service,
    sign_both,
)


class ExplainAtTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = make_service()
        draft_and_check(self.service, "VAR-GYN-01")
        sign_both(self.service, "VAR-GYN-01")
        approve_and_distribute(self.service, "VAR-GYN-01")
        # 09-05 降级，09-08 撤稿。
        self.service.update_evidence(
            "STU-HT-001",
            kind="downgrade",
            endpoints=["潮热频率"],
            rationale="荟萃分析后证据等级下调",
            occurred_at="2026-09-05T09:00:00+08:00",
        )
        self.service.update_evidence(
            "STU-HT-001",
            kind="retraction",
            endpoints="all",
            rationale="数据完整性问题，论文撤稿",
            occurred_at="2026-09-08T09:00:00+08:00",
        )

    def test_before_claim_mapped(self) -> None:
        snapshot = explain_at(self.service, "CLM-HOTFLASH", "2026-09-01T23:59:00+08:00")
        self.assertFalse(snapshot["exists"])

    def test_before_downgrade(self) -> None:
        snapshot = explain_at(self.service, "CLM-HOTFLASH", "2026-09-04T00:00:00+08:00")
        self.assertTrue(snapshot["exists"])
        self.assertEqual(snapshot["evidence_status"], "valid")
        self.assertEqual(snapshot["evidence_updates"], [])
        self.assertEqual(snapshot["corrections"], [])
        self.assertEqual(snapshot["limitations"], LIMITATIONS)
        self.assertEqual(snapshot["materials"][0]["status"], "distributed")

    def test_between_downgrade_and_retraction(self) -> None:
        snapshot = explain_at(self.service, "CLM-HOTFLASH", "2026-09-06T00:00:00+08:00")
        self.assertEqual(snapshot["evidence_status"], "downgraded")
        self.assertEqual(len(snapshot["evidence_updates"]), 1)
        self.assertEqual(len(snapshot["corrections"]), 1)

    def test_after_retraction(self) -> None:
        snapshot = explain_at(self.service, "CLM-HOTFLASH", "2026-09-09T00:00:00+08:00")
        self.assertEqual(snapshot["evidence_status"], "retracted")
        self.assertEqual(len(snapshot["corrections"]), 2)

    def test_unrelated_endpoint_keeps_valid_status(self) -> None:
        snapshot = explain_at(self.service, "CLM-BONE", "2026-09-06T00:00:00+08:00")
        self.assertEqual(snapshot["evidence_status"], "valid")
        # 撤稿为全部终点后，骨密度主张同样受影响。
        snapshot = explain_at(self.service, "CLM-BONE", "2026-09-09T00:00:00+08:00")
        self.assertEqual(snapshot["evidence_status"], "retracted")


class StudyVersionHistoryTest(unittest.TestCase):
    def test_claim_stays_pinned_to_mapped_version(self) -> None:
        service = make_service()
        # 研究登记新版本，限制条件增加；已映射主张仍锚定旧版本。
        service.register_study(
            "STU-HT-001",
            version_label="v2026.2",
            population={"description": "45–55岁围绝经期女性", "age_min": 45, "age_max": 55},
            endpoints=[{"name": "潮热频率", "result": "更新分析"}, {"name": "骨密度", "result": "更新分析"}],
            limitations=LIMITATIONS + ["新增限制：亚组证据不足"],
            statistics=[],
            occurred_at="2026-09-04T09:00:00+08:00",
        )
        snapshot = explain_at(service, "CLM-HOTFLASH", "2026-09-06T00:00:00+08:00")
        self.assertEqual(snapshot["study_version"], "v2026.1")
        self.assertEqual(snapshot["limitations"], LIMITATIONS)
        self.assertEqual(service.state.studies["STU-HT-001"].current.label, "v2026.2")


class TraceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = make_service()
        draft_and_check(self.service, "VAR-GYN-01")
        sign_both(self.service, "VAR-GYN-01")
        approve_and_distribute(self.service, "VAR-GYN-01")
        result = self.service.update_evidence(
            "STU-HT-001",
            kind="retraction",
            endpoints=["潮热频率"],
            rationale="论文撤稿",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        self.service.confirm_receipt(
            result["notices"][0], department="妇科门诊", occurred_at="2026-09-10T12:00:00+08:00"
        )

    def test_trace_from_public_wording(self) -> None:
        records = trace(self.service, "激素治疗")
        record = next(r for r in records if r["claim_id"] == "CLM-HOTFLASH")
        # 追到研究限制。
        self.assertEqual(record["study"]["limitations"], LIMITATIONS)
        self.assertEqual(record["study"]["evidence_status"], "retracted")
        self.assertEqual(record["study"]["version"], "v2026.1")
        # 追到签署决定与使用范围。
        material = record["materials"][0]
        self.assertEqual(material["department"], "妇科门诊")
        self.assertEqual(material["scenarios"], ["门诊宣教"])
        self.assertEqual(
            {s["role"] for s in material["signoffs"]}, {"methodology", "clinical"}
        )
        self.assertIsNotNone(material["distributed_at"])
        # 追到后续更正与接收确认。
        correction = material["corrections"][0]
        self.assertEqual(correction["kind"], "retraction")
        self.assertIn("撤稿", correction["disposition"])
        self.assertIn("妇科门诊", correction["receipts"])
        self.assertEqual(correction["pending"], [])

    def test_trace_by_claim_id(self) -> None:
        records = trace(self.service, "CLM-HOTFLASH")
        self.assertEqual([r["claim_id"] for r in records], ["CLM-HOTFLASH"])

    def test_trace_unknown_text_returns_empty(self) -> None:
        self.assertEqual(trace(self.service, "不存在的表述"), [])


if __name__ == "__main__":
    unittest.main()
