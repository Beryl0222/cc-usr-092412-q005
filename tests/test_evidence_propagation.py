"""撤稿、降级、随访更新的传播与已发放版本的风险处置。"""

import unittest

from src.events import DomainError
from src.queries import pending_receipts
from tests.helpers import (
    CAREFUL_WORDING,
    approve_and_distribute,
    draft_and_check,
    make_service,
    sign_both,
)


class RetractionPropagationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = make_service()
        # 妇科版本已发放（冻结）。
        draft_and_check(self.service, "VAR-GYN-01", department="妇科门诊")
        sign_both(self.service, "VAR-GYN-01")
        approve_and_distribute(self.service, "VAR-GYN-01")
        # 全科版本仍在起草，尚未签署。
        draft_and_check(self.service, "VAR-PCP-01", department="全科门诊")

    def test_retraction_flags_unfrozen_and_notices_frozen(self) -> None:
        result = self.service.update_evidence(
            "STU-HT-001",
            kind="retraction",
            endpoints=["潮热频率"],
            rationale="原始数据完整性问题，论文撤稿",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        self.assertEqual(result["flagged"], ["VAR-PCP-01"])
        self.assertEqual(len(result["notices"]), 1)

        # 未冻结材料标记为待修订，不能再直接签署。
        self.assertEqual(self.service.state.variants["VAR-PCP-01"].status, "needs_revision")
        with self.assertRaises(DomainError):
            self.service.sign_off(
                "VAR-PCP-01",
                role="clinical",
                reviewer="临床-赵",
                note="x",
                occurred_at="2026-09-10T10:00:00+08:00",
            )

        # 已发放版本不被改写、不被冻结状态破坏。
        frozen = self.service.state.variants["VAR-GYN-01"]
        self.assertEqual(frozen.status, "distributed")
        self.assertIn("激素治疗", frozen.items["CLM-HOTFLASH"])
        self.assertEqual(len(frozen.corrections), 1)

        notice = self.service.state.notices[result["notices"][0]]
        self.assertEqual(notice.kind, "retraction")
        self.assertEqual(notice.claims, ["CLM-HOTFLASH"])
        self.assertIn("撤稿", notice.disposition)
        self.assertEqual(notice.required_recipients, ["妇科门诊"])
        self.assertEqual(pending_receipts(self.service, notice.notice_id), ["妇科门诊"])

    def test_receipt_confirmation_flow(self) -> None:
        result = self.service.update_evidence(
            "STU-HT-001",
            kind="retraction",
            endpoints="all",
            rationale="撤稿",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        notice_id = result["notices"][0]
        with self.assertRaises(DomainError):
            # 不在接收范围的科室不能确认。
            self.service.confirm_receipt(
                notice_id, department="全科门诊", occurred_at="2026-09-10T12:00:00+08:00"
            )
        self.service.confirm_receipt(
            notice_id, department="妇科门诊", occurred_at="2026-09-10T12:00:00+08:00"
        )
        self.assertEqual(pending_receipts(self.service, notice_id), [])
        with self.assertRaises(DomainError):
            # 不允许重复确认。
            self.service.confirm_receipt(
                notice_id, department="妇科门诊", occurred_at="2026-09-10T13:00:00+08:00"
            )

    def test_downgrade_does_not_affect_unrelated_claim(self) -> None:
        # 骨密度降级只影响引用骨密度终点的材料；本两版材料均只引用潮热主张。
        result = self.service.update_evidence(
            "STU-HT-001",
            kind="downgrade",
            endpoints=["骨密度"],
            rationale="重新评估后证据等级下调",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        self.assertEqual(result["flagged"], [])
        self.assertEqual(result["notices"], [])
        self.assertEqual(self.service.state.variants["VAR-PCP-01"].status, "draft")
        self.assertEqual(self.service.state.variants["VAR-GYN-01"].corrections, [])

    def test_followup_uses_default_disposition(self) -> None:
        result = self.service.update_evidence(
            "STU-HT-001",
            kind="followup",
            endpoints=["潮热频率"],
            rationale="36个月随访结果公布",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        notice = self.service.state.notices[result["notices"][0]]
        self.assertEqual(notice.kind, "followup")
        self.assertIn("随访", notice.disposition)


if __name__ == "__main__":
    unittest.main()
