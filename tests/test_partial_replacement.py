"""局部替换：一条主张被证据更新命中时，只修订受影响条目。"""

import unittest

from tests.helpers import (
    BONE_WORDING,
    CAREFUL_WORDING,
    approve_and_distribute,
    draft_and_check,
    make_service,
    sign_both,
)


class PartialReplacementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = make_service()
        # 同一材料引用两条主张：潮热 + 骨密度。
        draft_and_check(
            self.service,
            "VAR-GYN-01",
            items={"CLM-HOTFLASH": CAREFUL_WORDING, "CLM-BONE": BONE_WORDING},
        )
        sign_both(self.service, "VAR-GYN-01")
        approve_and_distribute(self.service, "VAR-GYN-01")

    def test_partial_retraction_hits_only_matched_claim(self) -> None:
        result = self.service.update_evidence(
            "STU-HT-001",
            kind="retraction",
            endpoints=["潮热频率"],
            rationale="潮热分析数据撤稿，骨密度结论不受影响",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        notice = self.service.state.notices[result["notices"][0]]
        # 处置只覆盖潮热主张，骨密度条目不在通知内。
        self.assertEqual(notice.claims, ["CLM-HOTFLASH"])

    def test_unfrozen_material_keeps_unaffected_items(self) -> None:
        draft_and_check(
            self.service,
            "VAR-PCP-01",
            department="全科门诊",
            items={"CLM-HOTFLASH": CAREFUL_WORDING, "CLM-BONE": BONE_WORDING},
        )
        self.service.update_evidence(
            "STU-HT-001",
            kind="downgrade",
            endpoints=["潮热频率"],
            rationale="潮热证据等级下调",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        variant = self.service.state.variants["VAR-PCP-01"]
        self.assertEqual(variant.status, "needs_revision")
        self.assertEqual(variant.impacted, {"CLM-HOTFLASH"})

        # 局部替换：只改潮热条目，骨密度条目原样保留。
        self.service.revise_material(
            "VAR-PCP-01",
            changes={"CLM-HOTFLASH": CAREFUL_WORDING + "（证据等级已下调为低）"},
            occurred_at="2026-09-10T10:00:00+08:00",
        )
        variant = self.service.state.variants["VAR-PCP-01"]
        self.assertEqual(variant.status, "draft")
        self.assertEqual(variant.impacted, set())
        self.assertEqual(variant.items["CLM-BONE"], BONE_WORDING)
        self.assertIn("证据等级已下调", variant.items["CLM-HOTFLASH"])

    def test_removal_also_clears_impact(self) -> None:
        draft_and_check(
            self.service,
            "VAR-PCP-01",
            department="全科门诊",
            items={"CLM-HOTFLASH": CAREFUL_WORDING, "CLM-BONE": BONE_WORDING},
        )
        self.service.update_evidence(
            "STU-HT-001",
            kind="retraction",
            endpoints=["潮热频率"],
            rationale="撤稿",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        # 撤稿后无法改写措辞补救，直接移除该条目。
        self.service.revise_material(
            "VAR-PCP-01", removals=["CLM-HOTFLASH"], occurred_at="2026-09-10T10:00:00+08:00"
        )
        variant = self.service.state.variants["VAR-PCP-01"]
        self.assertEqual(variant.status, "draft")
        self.assertEqual(list(variant.items), ["CLM-BONE"])


if __name__ == "__main__":
    unittest.main()
