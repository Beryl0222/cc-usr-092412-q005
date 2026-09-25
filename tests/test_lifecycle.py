"""材料版本生命周期与双签署门禁。"""

import unittest

from src.events import DomainError
from tests.helpers import (
    CAREFUL_WORDING,
    OVERGENERAL_WORDING,
    draft_and_check,
    make_service,
    sign_both,
)


class LifecycleTest(unittest.TestCase):
    def test_compliant_wording_passes_checks(self) -> None:
        service = make_service()
        prompts = draft_and_check(service, "VAR-GYN-01")
        self.assertEqual(prompts, [])

    def test_overgeneral_wording_is_flagged(self) -> None:
        service = make_service()
        prompts = draft_and_check(
            service, "VAR-GYN-01", items={"CLM-HOTFLASH": OVERGENERAL_WORDING}
        )
        kinds = {p["kind"] for p in prompts}
        self.assertIn("over_extrapolation", kinds)
        self.assertIn("omission", kinds)

    def test_cannot_sign_before_checks(self) -> None:
        service = make_service()
        service.draft_material(
            "VAR-GYN-01",
            department="妇科门诊",
            audience="patient",
            items={"CLM-HOTFLASH": CAREFUL_WORDING},
            occurred_at="2026-09-03T09:00:00+08:00",
        )
        with self.assertRaises(DomainError):
            service.sign_off(
                "VAR-GYN-01",
                role="methodology",
                reviewer="方法学-林",
                note="x",
                occurred_at="2026-09-03T10:00:00+08:00",
            )

    def test_approve_requires_both_signoffs(self) -> None:
        service = make_service()
        draft_and_check(service, "VAR-GYN-01")
        service.sign_off(
            "VAR-GYN-01",
            role="methodology",
            reviewer="方法学-林",
            note="解释一致",
            occurred_at="2026-09-03T10:00:00+08:00",
        )
        with self.assertRaises(DomainError):
            service.approve(
                "VAR-GYN-01", scenarios=["门诊宣教"], occurred_at="2026-09-03T11:00:00+08:00"
            )

    def test_different_departments_share_one_evidence_boundary(self) -> None:
        """不同科室可用不同措辞，但引用同一主张、同一证据边界，且都需双签署。"""
        service = make_service()
        draft_and_check(
            service,
            "VAR-GYN-01",
            department="妇科门诊",
            items={"CLM-HOTFLASH": "妇科版本：" + CAREFUL_WORDING},
        )
        sign_both(service, "VAR-GYN-01")
        service.approve(
            "VAR-GYN-01", scenarios=["妇科门诊宣教"], occurred_at="2026-09-03T11:00:00+08:00"
        )

        draft_and_check(
            service,
            "VAR-PCP-01",
            department="全科门诊",
            items={"CLM-HOTFLASH": "全科版本：" + CAREFUL_WORDING},
        )
        with self.assertRaises(DomainError):
            # 全科版本未双签署，不能因妇科版本已批准而放行。
            service.approve(
                "VAR-PCP-01", scenarios=["全科候诊屏"], occurred_at="2026-09-03T11:30:00+08:00"
            )
        sign_both(service, "VAR-PCP-01")
        service.approve(
            "VAR-PCP-01", scenarios=["全科候诊屏"], occurred_at="2026-09-03T12:00:00+08:00"
        )
        gyn = service.state.variants["VAR-GYN-01"]
        pcp = service.state.variants["VAR-PCP-01"]
        self.assertEqual(gyn.items.keys(), pcp.items.keys())
        self.assertNotEqual(gyn.items["CLM-HOTFLASH"], pcp.items["CLM-HOTFLASH"])

    def test_high_risk_requires_extra_review(self) -> None:
        service = make_service()
        draft_and_check(service, "VAR-HIGH-01", risk="high")
        sign_both(service, "VAR-HIGH-01")
        with self.assertRaises(DomainError):
            service.approve(
                "VAR-HIGH-01", scenarios=["高风险门诊"], occurred_at="2026-09-03T11:00:00+08:00"
            )
        service.sign_off(
            "VAR-HIGH-01",
            role="high_risk_review",
            reviewer="复核-周",
            note="高风险人群适用性已逐句核对",
            occurred_at="2026-09-03T10:30:00+08:00",
        )
        service.approve(
            "VAR-HIGH-01", scenarios=["高风险门诊"], occurred_at="2026-09-03T11:00:00+08:00"
        )
        self.assertEqual(service.state.variants["VAR-HIGH-01"].status, "approved")

    def test_high_risk_signoff_rejected_for_general_material(self) -> None:
        service = make_service()
        draft_and_check(service, "VAR-GYN-01")
        with self.assertRaises(DomainError):
            service.sign_off(
                "VAR-GYN-01",
                role="high_risk_review",
                reviewer="复核-周",
                note="x",
                occurred_at="2026-09-03T10:00:00+08:00",
            )

    def test_revision_clears_signoffs_and_checks(self) -> None:
        service = make_service()
        draft_and_check(service, "VAR-GYN-01")
        sign_both(service, "VAR-GYN-01")
        variant = service.state.variants["VAR-GYN-01"]
        self.assertEqual(variant.revision, 1)

        # 已批准但未发放的版本不能直接修订，必须先被证据更新标记。
        service.approve(
            "VAR-GYN-01", scenarios=["门诊宣教"], occurred_at="2026-09-03T11:00:00+08:00"
        )
        with self.assertRaises(DomainError):
            service.revise_material(
                "VAR-GYN-01",
                changes={"CLM-HOTFLASH": CAREFUL_WORDING + "（补充随访说明）"},
                occurred_at="2026-09-04T09:00:00+08:00",
            )

        service.update_evidence(
            "STU-HT-001",
            kind="followup",
            endpoints=["潮热频率"],
            rationale="36个月随访公布",
            occurred_at="2026-09-04T08:00:00+08:00",
        )
        service.revise_material(
            "VAR-GYN-01",
            changes={"CLM-HOTFLASH": CAREFUL_WORDING + "（随访36个月结论仍成立）"},
            occurred_at="2026-09-04T09:00:00+08:00",
        )
        variant = service.state.variants["VAR-GYN-01"]
        self.assertEqual(variant.revision, 2)
        self.assertEqual(variant.signoffs, {})
        self.assertEqual(variant.checks, [])
        self.assertEqual(variant.status, "draft")


if __name__ == "__main__":
    unittest.main()
