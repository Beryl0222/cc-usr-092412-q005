"""确定性关键场景：撤稿传播、局部替换、历史时点解释。"""

import unittest

from src.errors import DomainError
from src.service import TranslationService
from src.store import EventStore

from scenario import (
    GY_WORDING,
    STUDY_ID,
    build_service_with_claim,
    sign_and_freeze,
)


def _three_states_service():
    """同一主张下三个材料：草稿 / 已冻结未发放 / 已发放。"""
    svc = build_service_with_claim()
    svc.draft_variant(
        variant_id="var-draft", department="妇科门诊",
        claim_id="claim-window-correlation", wording=GY_WORDING,
        usage_scenarios=["妇科门诊候诊区纸质材料"],
        occurred_at="2026-09-03T09:00:00+08:00",
    )
    svc.draft_variant(
        variant_id="var-frozen", department="妇科门诊",
        claim_id="claim-window-correlation", wording=GY_WORDING,
        usage_scenarios=["妇科门诊候诊区纸质材料"],
        occurred_at="2026-09-03T09:05:00+08:00",
    )
    sign_and_freeze(svc, "var-frozen", occurred_at="2026-09-04T09:00:00+08:00")
    svc.draft_variant(
        variant_id="var-distributed", department="妇科门诊",
        claim_id="claim-window-correlation", wording=GY_WORDING,
        usage_scenarios=["妇科门诊候诊区纸质材料"],
        occurred_at="2026-09-03T09:10:00+08:00",
    )
    sign_and_freeze(svc, "var-distributed", occurred_at="2026-09-04T09:05:00+08:00")
    svc.distribute(
        variant_id="var-distributed",
        recipients=["妇科护士站", "门诊宣教屏运维方"],
        occurred_at="2026-09-05T09:00:00+08:00",
    )
    return svc


class RetractionPropagationTest(unittest.TestCase):
    def test_flag_only_affects_referencing_materials_by_freeze_state(self) -> None:
        svc = _three_states_service()
        # 不引用该研究版本的材料不应被波及
        svc.register_study(
            study_id="study-other", title="另一项骨密度研究",
            occurred_at="2026-08-01T09:00:00+08:00",
        )
        svc.record_study_version(
            study_id="study-other", study_version=1,
            population_groups=["绝经后女性"], age_range=(50, 70),
            treatment_windows=[(0, 30)], endpoints=["椎体骨折"],
            exclusions=[], limitations=["样本量小"],
            statistical_conclusion="骨密度与骨折呈相关",
            result_nature="correlation", evidence_grade=2,
            high_risk_populations=[],
            occurred_at="2026-08-01T09:05:00+08:00",
        )
        svc.map_claim(
            claim_id="claim-other", statement="另一项研究的限定相关性表述",
            study_id="study-other", study_version=1,
            scope=dict(
                population_groups=["绝经后女性"], age_range=(50, 70),
                treatment_windows=[(0, 30)], endpoints=["椎体骨折"],
            ),
            not_applicable=[], limitations_disclosed=["样本量小"],
            result_nature="correlation", evidence_grade=2,
            occurred_at="2026-08-02T09:00:00+08:00",
        )
        svc.draft_variant(
            variant_id="var-unrelated", department="骨科门诊",
            claim_id="claim-other", wording="骨密度沟通稿",
            usage_scenarios=["骨科门诊"], occurred_at="2026-08-03T09:00:00+08:00",
        )
        result = svc.flag_evidence(
            study_id=STUDY_ID,
            study_version=1,
            change_type="retraction",
            reason="原始数据核查发现关键亚组编码错误",
            risk_handling="立即停止以该结论支持新建议；已发材料加贴撤稿警示并回收",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        self.assertEqual(result["affected_unfrozen"], ["var-draft@r1"])
        self.assertEqual(result["frozen_pending_distribution"], ["var-frozen@r1"])
        self.assertEqual(
            result["correction_notices"],
            ["corr-var-distributed-r1-study-mht-chd-2026-3"],
        )
        # 不相关材料不出现在任何传播清单中
        touched = (
            result["affected_unfrozen"]
            + result["frozen_pending_distribution"]
            + result["correction_notices"]
        )
        self.assertFalse(any("var-unrelated" in ref for ref in touched))

        # 未冻结材料：冻结被阻断
        status = svc.review_status("var-draft")
        self.assertTrue(any("撤稿" in e for e in status["boundary_errors"]))
        with self.assertRaises(DomainError):
            svc.freeze_for_scenarios(
                variant_id="var-draft",
                usage_scenarios=["妇科门诊候诊区纸质材料"],
                occurred_at="2026-09-10T10:00:00+08:00",
            )

        # 已冻结未发放：发放前重检被阻断，冻结决定本身不被追溯改写
        self.assertEqual(svc.trace("var-frozen")["status"], "frozen")
        with self.assertRaises(DomainError) as ctx:
            svc.distribute(
                variant_id="var-frozen", recipients=["某科室"],
                occurred_at="2026-09-10T10:00:00+08:00",
            )
        self.assertIn("撤稿", str(ctx.exception))

        # 已发放：冻结版本不动，追加更正通知与风险处置
        trace = svc.trace("var-distributed")
        self.assertEqual(trace["status"], "distributed")
        self.assertEqual(len(trace["corrections"]), 1)
        correction = trace["corrections"][0]
        self.assertEqual(correction["change_type"], "retraction")
        self.assertIn("回收", correction["risk_handling"])
        self.assertEqual(
            correction["pending_receivers"], ["妇科护士站", "门诊宣教屏运维方"]
        )
        self.assertEqual(correction["acknowledgements"], [])

    def test_correction_acknowledgements_are_tracked(self) -> None:
        svc = _three_states_service()
        svc.flag_evidence(
            study_id=STUDY_ID, study_version=1, change_type="retraction",
            reason="数据编码错误",
            risk_handling="加贴撤稿警示并回收",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        notice_id = "corr-var-distributed-r1-study-mht-chd-2026-3"
        # 非发放名单内的人不能代签
        with self.assertRaises(DomainError):
            svc.acknowledge_correction(
                notice_id=notice_id, receiver="无关科室",
                received_at="2026-09-10T14:00:00+08:00",
            )
        svc.acknowledge_correction(
            notice_id=notice_id, receiver="妇科护士站",
            received_at="2026-09-10T14:00:00+08:00",
        )
        # 重复确认被拒绝
        with self.assertRaises(DomainError):
            svc.acknowledge_correction(
                notice_id=notice_id, receiver="妇科护士站",
                received_at="2026-09-10T15:00:00+08:00",
            )
        trace = svc.trace("var-distributed")
        correction = trace["corrections"][0]
        self.assertEqual(correction["pending_receivers"], ["门诊宣教屏运维方"])
        self.assertEqual(
            correction["acknowledgements"][0]["receiver"], "妇科护士站"
        )

    def test_downgrade_warns_unfrozen_but_still_corrects_distributed(self) -> None:
        svc = _three_states_service()
        result = svc.flag_evidence(
            study_id=STUDY_ID, study_version=1, change_type="downgrade",
            reason="偏倚风险复评后下调一级",
            risk_handling="已发材料附加降级说明，不再作为最高等级证据引用",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        # 草稿被列入影响面，但降级只提示、不硬阻断；已发版本仍触发更正
        self.assertEqual(result["affected_unfrozen"], ["var-draft@r1"])
        self.assertEqual(len(result["correction_notices"]), 1)
        status = svc.review_status("var-draft")
        self.assertTrue(any("降级" in w for w in status["boundary_warnings"]))
        self.assertEqual(status["boundary_errors"], [])

    def test_propagation_is_deterministic_on_replay(self) -> None:
        svc = _three_states_service()
        svc.flag_evidence(
            study_id=STUDY_ID, study_version=1, change_type="retraction",
            reason="数据编码错误", risk_handling="回收并加贴警示",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        svc.acknowledge_correction(
            notice_id="corr-var-distributed-r1-study-mht-chd-2026-3",
            receiver="妇科护士站", received_at="2026-09-10T14:00:00+08:00",
        )
        # 用完整事件流重建：同输入必须得到同一查询结果与事件标识
        replayed = TranslationService(EventStore(svc.store.events))
        before = svc.trace("var-distributed")
        after = replayed.trace("var-distributed")
        self.assertEqual(before, after)
        self.assertEqual(
            [e["event_id"] for e in svc.store.events],
            [e["event_id"] for e in replayed.store.events],
        )


class LocalReplacementTest(unittest.TestCase):
    def test_replacement_creates_new_revision_and_preserves_history(self) -> None:
        svc = build_service_with_claim()
        svc.draft_variant(
            variant_id="var-gy", department="妇科门诊",
            claim_id="claim-window-correlation", wording=GY_WORDING,
            usage_scenarios=["妇科门诊候诊区纸质材料"],
            occurred_at="2026-09-03T09:00:00+08:00",
        )
        sign_and_freeze(svc, "var-gy", occurred_at="2026-09-04T09:00:00+08:00")
        svc.distribute(
            variant_id="var-gy", recipients=["妇科护士站"],
            occurred_at="2026-09-05T09:00:00+08:00",
        )

        new_wording = GY_WORDING + "（2026-09 复核：请同时留意新增的东亚人群证据局限说明。）"
        svc.replace_wording(
            variant_id="var-gy", wording=new_wording,
            reason="按科室沟通习惯补充局限提示，证据边界不变",
            occurred_at="2026-09-08T09:00:00+08:00",
        )

        # 当前版本是 r2，r1 原样保留且仍标记为已发放
        current = svc.trace("var-gy")
        self.assertEqual(current["wording_revision"], 2)
        self.assertEqual(current["status"], "draft")
        self.assertEqual(current["statement"], new_wording)
        old = svc.trace("var-gy", wording_revision=1)
        self.assertEqual(old["statement"], GY_WORDING)
        self.assertEqual(old["status"], "distributed")
        # 旧版本的签署不自动继承到新版本
        self.assertEqual(
            sorted(a["role"] for a in old["sign_offs"]),
            ["clinician", "methodology"],
        )
        status_r2 = svc.review_status("var-gy")
        self.assertEqual(
            sorted(status_r2["missing_confirmations"]), ["clinician", "methodology"]
        )

        # 新版本重新双签后可冻结，且只在新场景生效
        sign_and_freeze(
            svc, "var-gy", occurred_at="2026-09-09T09:00:00+08:00",
            scenarios=["妇科门诊电子屏"],
        )
        self.assertEqual(svc.trace("var-gy")["usage"]["scenarios"], ["妇科门诊电子屏"])
        self.assertEqual(old["usage"]["scenarios"], ["妇科门诊候诊区纸质材料"])

    def test_replacement_cannot_break_boundary(self) -> None:
        svc = build_service_with_claim()
        svc.draft_variant(
            variant_id="var-gy", department="妇科门诊",
            claim_id="claim-window-correlation", wording=GY_WORDING,
            usage_scenarios=["妇科门诊候诊区纸质材料"],
            occurred_at="2026-09-03T09:00:00+08:00",
        )
        with self.assertRaises(DomainError) as ctx:
            svc.replace_wording(
                variant_id="var-gy",
                wording="所有女性一律用药，必然预防冠心病，无需考虑禁忌证",
                reason="媒体要求改醒目",
                occurred_at="2026-09-08T09:00:00+08:00",
            )
        self.assertIn("突破证据边界", str(ctx.exception))
        # 失败的替换不产生事件，当前仍是 r1
        self.assertEqual(svc.trace("var-gy")["wording_revision"], 1)

    def test_replacement_can_track_claim_revision_while_old_version_keeps_link(self) -> None:
        svc = build_service_with_claim()
        svc.draft_variant(
            variant_id="var-gy", department="妇科门诊",
            claim_id="claim-window-correlation", wording=GY_WORDING,
            usage_scenarios=["妇科门诊候诊区纸质材料"],
            occurred_at="2026-09-03T09:00:00+08:00",
        )
        sign_and_freeze(svc, "var-gy", occurred_at="2026-09-04T09:00:00+08:00")
        # 主张修订：年龄收窄
        revised_scope = dict(
            population_groups=["绝经后早期女性"],
            age_range=(48, 55),
            treatment_windows=[(0, 10)],
            endpoints=["冠心病事件"],
        )
        svc.revise_claim(
            claim_id="claim-window-correlation",
            scope=revised_scope,
            occurred_at="2026-09-07T09:00:00+08:00",
        )
        svc.replace_wording(
            variant_id="var-gy",
            wording=GY_WORDING.replace("45-55", "48-55"),
            reason="按主张修订 r2 收窄年龄表述",
            claim_revision=2,
            occurred_at="2026-09-08T09:00:00+08:00",
        )
        new = svc.trace("var-gy")
        self.assertEqual(new["claim"]["claim_revision"], 2)
        self.assertEqual(new["claim"]["evidence_scope"]["age_range"], [48, 55])
        old = svc.trace("var-gy", wording_revision=1)
        self.assertEqual(old["claim"]["claim_revision"], 1)
        self.assertEqual(old["claim"]["evidence_scope"]["age_range"], [45, 55])


class HistoricalPointInTimeTest(unittest.TestCase):
    def _timeline_service(self):
        svc = build_service_with_claim()
        svc.draft_variant(
            variant_id="var-gy", department="妇科门诊",
            claim_id="claim-window-correlation", wording=GY_WORDING,
            usage_scenarios=["妇科门诊候诊区纸质材料"],
            occurred_at="2026-09-03T09:00:00+08:00",
        )
        sign_and_freeze(svc, "var-gy", occurred_at="2026-09-04T09:00:00+08:00")
        svc.distribute(
            variant_id="var-gy", recipients=["妇科护士站"],
            occurred_at="2026-09-05T09:00:00+08:00",
        )
        return svc

    def test_explain_at_replays_each_phase(self) -> None:
        svc = self._timeline_service()

        with self.assertRaises(DomainError):
            svc.explain_at("var-gy", "2026-09-02T23:59:59+08:00")

        drafted = svc.explain_at("var-gy", "2026-09-03T23:59:59+08:00")
        self.assertEqual(drafted["wording_revision"], 1)
        self.assertEqual(drafted["sign_offs_at_that_time"], {})
        self.assertFalse(drafted["frozen_at_that_time"])
        self.assertFalse(drafted["distributed_at_that_time"])
        self.assertIsNone(drafted["evidence_flag_at_that_time"])
        # 当时就能看到研究限制与不适用情形
        self.assertIn("乳腺癌病史", drafted["not_applicable"])
        self.assertIn("观察性研究", "；".join(drafted["study_limitations"]))

        frozen = svc.explain_at("var-gy", "2026-09-04T23:59:59+08:00")
        self.assertTrue(frozen["frozen_at_that_time"])
        self.assertFalse(frozen["distributed_at_that_time"])
        self.assertEqual(
            frozen["sign_offs_at_that_time"],
            {"methodology": "confirmed", "clinician": "confirmed"},
        )

        distributed = svc.explain_at("var-gy", "2026-09-06T00:00:00+08:00")
        self.assertTrue(distributed["distributed_at_that_time"])
        self.assertEqual(
            distributed["usage_scenarios"], ["妇科门诊候诊区纸质材料"]
        )

        # 撤稿发生在发放之后：历史时点能区分“当时无警示”与“事后已知撤稿”
        svc.flag_evidence(
            study_id=STUDY_ID, study_version=1, change_type="retraction",
            reason="数据编码错误", risk_handling="回收并加贴警示",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        before_flag = svc.explain_at("var-gy", "2026-09-09T00:00:00+08:00")
        self.assertIsNone(before_flag["evidence_flag_at_that_time"])
        self.assertFalse(before_flag["evidence_changed_after_distribution"])
        after_flag = svc.explain_at("var-gy", "2026-09-11T00:00:00+08:00")
        self.assertEqual(
            after_flag["evidence_flag_at_that_time"]["change_type"], "retraction"
        )
        self.assertTrue(after_flag["evidence_changed_after_distribution"])

    def test_explain_at_follows_replacement_timeline(self) -> None:
        svc = self._timeline_service()
        svc.replace_wording(
            variant_id="var-gy", wording=GY_WORDING + "（补充东亚人群局限提示。）",
            reason="补充局限提示", occurred_at="2026-09-08T09:00:00+08:00",
        )
        before = svc.explain_at("var-gy", "2026-09-07T00:00:00+08:00")
        after = svc.explain_at("var-gy", "2026-09-09T00:00:00+08:00")
        self.assertEqual(before["wording_revision"], 1)
        self.assertEqual(after["wording_revision"], 2)

    def test_historical_explanation_is_deterministic_across_replay(self) -> None:
        svc = self._timeline_service()
        svc.flag_evidence(
            study_id=STUDY_ID, study_version=1, change_type="retraction",
            reason="数据编码错误", risk_handling="回收",
            occurred_at="2026-09-10T09:00:00+08:00",
        )
        replayed = TranslationService(EventStore(svc.store.events))
        checkpoint = "2026-09-11T00:00:00+08:00"
        self.assertEqual(
            svc.explain_at("var-gy", checkpoint),
            replayed.explain_at("var-gy", checkpoint),
        )


if __name__ == "__main__":
    unittest.main()
