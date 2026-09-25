"""主张映射、科室措辞、签署冻结门禁与发放的工作流测试。"""

import unittest

from src.errors import DomainError

from scenario import (
    GP_WORDING,
    GY_WORDING,
    HIGH_RISK_SCOPE,
    MEDIA_OVERREACH,
    NOT_APPLICABLE,
    STUDY_ID,
    build_registered_service,
    build_service_with_claim,
    sign_and_freeze,
)


class ClaimWorkflowTest(unittest.TestCase):
    def test_media_overreach_is_rejected_with_itemized_problems(self) -> None:
        svc = build_registered_service()
        with self.assertRaises(DomainError) as ctx:
            svc.map_claim(
                study_id=STUDY_ID,
                study_version=1,
                occurred_at="2026-09-02T10:00:00+08:00",
                **MEDIA_OVERREACH,
            )
        message = str(ctx.exception)
        # 各类过度外推与遗漏都应被提示
        self.assertIn("超出研究纳入人群", message)
        self.assertIn("超出研究年龄", message)
        self.assertIn("治疗窗口", message)
        self.assertIn("终点", message)
        self.assertIn("丢弃了研究排除条件", message)
        self.assertIn("过度外推", message)
        self.assertIn("证据等级", message)

    def test_conforming_claim_warns_on_general_words_but_is_accepted(self) -> None:
        svc = build_service_with_claim()
        state = svc._state()  # smoke: 主张可回放
        self.assertIn("claim-window-correlation", state.claims)

    def test_departments_may_word_differently_but_share_one_boundary(self) -> None:
        svc = build_service_with_claim()
        svc.draft_variant(
            variant_id="var-gynecology",
            department="妇科门诊",
            claim_id="claim-window-correlation",
            wording=GY_WORDING,
            usage_scenarios=["妇科门诊候诊区纸质材料"],
            occurred_at="2026-09-03T09:00:00+08:00",
        )
        svc.draft_variant(
            variant_id="var-general-practice",
            department="全科医学科",
            claim_id="claim-window-correlation",
            wording=GP_WORDING,
            usage_scenarios=["全科知情同意辅助单"],
            occurred_at="2026-09-03T09:10:00+08:00",
        )
        sign_and_freeze(svc, "var-gynecology", occurred_at="2026-09-04T09:00:00+08:00")
        sign_and_freeze(
            svc, "var-general-practice",
            occurred_at="2026-09-04T09:05:00+08:00",
            scenarios=["全科知情同意辅助单"],
        )
        gy = svc.trace("var-gynecology")
        gp = svc.trace("var-general-practice")
        self.assertEqual(gy["status"], "frozen")
        self.assertEqual(gp["status"], "frozen")
        # 措辞不同，证据边界同一
        self.assertNotEqual(gy["statement"], gp["statement"])
        self.assertEqual(gy["study"]["study_id"], gp["study"]["study_id"])
        self.assertEqual(gy["claim"]["evidence_scope"], gp["claim"]["evidence_scope"])
        self.assertEqual(gy["claim"]["not_applicable"], gp["claim"]["not_applicable"])

    def test_department_cannot_break_boundary_with_softer_process(self) -> None:
        svc = build_service_with_claim()
        with self.assertRaises(DomainError) as ctx:
            svc.draft_variant(
                variant_id="var-bad",
                department="某科室",
                claim_id="claim-window-correlation",
                wording="所有更年期女性一律用药，无需评估禁忌证，必然预防冠心病",
                usage_scenarios=["公众号推文"],
                occurred_at="2026-09-03T09:00:00+08:00",
            )
        self.assertIn("突破证据边界", str(ctx.exception))

    def test_freeze_requires_methodology_and_clinician_confirmations(self) -> None:
        svc = build_service_with_claim()
        svc.draft_variant(
            variant_id="var-gynecology",
            department="妇科门诊",
            claim_id="claim-window-correlation",
            wording=GY_WORDING,
            usage_scenarios=["妇科门诊候诊区纸质材料"],
            occurred_at="2026-09-03T09:00:00+08:00",
        )
        # 无签署不能冻结
        with self.assertRaises(DomainError) as ctx:
            svc.freeze_for_scenarios(
                variant_id="var-gynecology",
                usage_scenarios=["妇科门诊候诊区纸质材料"],
                occurred_at="2026-09-04T09:00:00+08:00",
            )
        self.assertIn("methodology", str(ctx.exception))
        self.assertIn("clinician", str(ctx.exception))
        # 只有方法学确认、临床驳回仍不能冻结
        svc.mark_approval(
            variant_id="var-gynecology", role="methodology", reviewer="方法学-林",
            decision="confirmed", occurred_at="2026-09-04T08:00:00+08:00",
        )
        svc.mark_approval(
            variant_id="var-gynecology", role="clinician", reviewer="临床-周",
            decision="rejected", occurred_at="2026-09-04T08:05:00+08:00",
        )
        with self.assertRaises(DomainError) as ctx:
            svc.freeze_for_scenarios(
                variant_id="var-gynecology",
                usage_scenarios=["妇科门诊候诊区纸质材料"],
                occurred_at="2026-09-04T09:00:00+08:00",
            )
        self.assertIn("驳回", str(ctx.exception))

    def test_high_risk_requires_extra_review(self) -> None:
        svc = build_registered_service()
        svc.map_claim(
            claim_id="claim-high-risk",
            statement=(
                "绝经 10 年内、合并心血管高危因素的女性，MHT 与冠心病事件降低相关；"
                "高危者须心内科联合评估。"
            ),
            study_id=STUDY_ID,
            study_version=1,
            scope=HIGH_RISK_SCOPE,
            not_applicable=NOT_APPLICABLE,
            limitations_disclosed=["观察性研究，不能排除残余混杂", "东亚人群占比低"],
            result_nature="correlation_adj",
            evidence_grade=2,
            high_risk_note="合并心血管高危因素者需心内科联合评估后再决定",
            occurred_at="2026-09-02T11:00:00+08:00",
        )
        svc.draft_variant(
            variant_id="var-high-risk",
            department="心内科联合门诊",
            claim_id="claim-high-risk",
            wording="高危人群联合门诊沟通稿（略）：需心内科评估，结果仅为相关。",
            usage_scenarios=["联合门诊医患沟通"],
            occurred_at="2026-09-03T09:00:00+08:00",
        )
        # 双签但缺额外复核
        svc.mark_approval(
            variant_id="var-high-risk", role="methodology", reviewer="方法学-林",
            decision="confirmed", occurred_at="2026-09-04T08:00:00+08:00",
        )
        svc.mark_approval(
            variant_id="var-high-risk", role="clinician", reviewer="临床-周",
            decision="confirmed", occurred_at="2026-09-04T08:05:00+08:00",
        )
        status = svc.review_status("var-high-risk")
        self.assertTrue(status["high_risk"])
        self.assertEqual(status["missing_confirmations"], ["extra_review"])
        with self.assertRaises(DomainError):
            svc.freeze_for_scenarios(
                variant_id="var-high-risk",
                usage_scenarios=["联合门诊医患沟通"],
                occurred_at="2026-09-04T09:00:00+08:00",
            )
        # 补齐额外复核后可冻结
        svc.mark_approval(
            variant_id="var-high-risk", role="extra_review", reviewer="高危复核-秦",
            decision="confirmed", occurred_at="2026-09-04T08:10:00+08:00",
        )
        svc.freeze_for_scenarios(
            variant_id="var-high-risk",
            usage_scenarios=["联合门诊医患沟通"],
            occurred_at="2026-09-04T09:00:00+08:00",
        )
        self.assertEqual(svc.trace("var-high-risk")["status"], "frozen")

    def test_distribution_requires_frozen_and_recipients(self) -> None:
        svc = build_service_with_claim()
        svc.draft_variant(
            variant_id="var-gynecology",
            department="妇科门诊",
            claim_id="claim-window-correlation",
            wording=GY_WORDING,
            usage_scenarios=["妇科门诊候诊区纸质材料"],
            occurred_at="2026-09-03T09:00:00+08:00",
        )
        with self.assertRaises(DomainError):
            svc.distribute(
                variant_id="var-gynecology",
                recipients=["护士站甲"],
                occurred_at="2026-09-05T09:00:00+08:00",
            )
        sign_and_freeze(svc, "var-gynecology", occurred_at="2026-09-04T09:00:00+08:00")
        svc.distribute(
            variant_id="var-gynecology",
            recipients=["妇科护士站", "门诊宣教屏运维方"],
            occurred_at="2026-09-05T09:00:00+08:00",
        )
        trace = svc.trace("var-gynecology")
        self.assertEqual(trace["status"], "distributed")
        self.assertEqual(trace["usage"]["recipients"], ["妇科护士站", "门诊宣教屏运维方"])


if __name__ == "__main__":
    unittest.main()
