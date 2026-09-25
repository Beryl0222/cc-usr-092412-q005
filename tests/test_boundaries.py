"""证据边界规则：子集约束、排除条件、结论语气、高风险与证据标记。"""

import unittest

from src.boundaries import evaluate_scope

from scenario import NOT_APPLICABLE, SCOPE, STUDY_VERSION


def _evaluate(**overrides):
    fields = dict(
        statement="限定人群中的相关性表述",
        scope=SCOPE,
        not_applicable=NOT_APPLICABLE,
        limitations_disclosed=list(STUDY_VERSION["limitations"]),
        result_nature="correlation_adj",
        evidence_grade=2,
        high_risk_note="",
        study_version=STUDY_VERSION,
        flagged=None,
    )
    fields.update(overrides)
    return evaluate_scope(**fields)


class BoundaryTest(unittest.TestCase):
    def test_conforming_claim_passes(self) -> None:
        warnings, errors = _evaluate()
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_population_must_be_subset(self) -> None:
        scope = dict(SCOPE, population_groups=["绝经后早期女性", "绝经后晚期女性"])
        _, errors = _evaluate(scope=scope)
        self.assertTrue(any("超出研究纳入人群" in e for e in errors))

    def test_age_window_endpoints_must_stay_inside(self) -> None:
        _, errors = _evaluate(scope=dict(SCOPE, age_range=(45, 70)))
        self.assertTrue(any("超出研究年龄" in e for e in errors))
        _, errors = _evaluate(scope=dict(SCOPE, treatment_windows=[(0, 20)]))
        self.assertTrue(any("治疗窗口" in e for e in errors))
        _, errors = _evaluate(scope=dict(SCOPE, endpoints=["冠心病事件", "全因死亡率"]))
        self.assertTrue(any("终点" in e for e in errors))

    def test_exclusions_must_not_be_dropped(self) -> None:
        _, errors = _evaluate(not_applicable=["乳腺癌病史"])
        dropped = [e for e in errors if "丢弃了研究排除条件" in e]
        self.assertEqual(len(dropped), 1)
        self.assertIn("不明原因阴道出血", dropped[0])
        self.assertIn("活动性静脉血栓", dropped[0])

    def test_correlation_cannot_become_general_recommendation(self) -> None:
        _, errors = _evaluate(
            statement="所有更年期女性一律启动治疗",
            result_nature="general_recommendation",
        )
        self.assertTrue(any("过度外推" in e for e in errors))
        warnings, _ = _evaluate(statement="这适用于所有符合条件的女性吗？需确认")
        # 普遍化措辞本身只是提示，不直接阻断
        self.assertTrue(any("普遍化措辞" in w for w in warnings))

    def test_evidence_grade_cannot_be_inflated(self) -> None:
        _, errors = _evaluate(evidence_grade=4)
        self.assertTrue(any("证据等级" in e for e in errors))

    def test_missing_limitation_is_warning_not_hard_block(self) -> None:
        warnings, errors = _evaluate(limitations_disclosed=[])
        self.assertEqual(errors, [])
        self.assertTrue(any("研究限制" in w for w in warnings))

    def test_retraction_blocks_later_use_downgrade_warns(self) -> None:
        retracted = {"change_type": "retraction", "reason": "数据造假", "study_version": 1}
        _, errors = _evaluate(flagged=retracted)
        self.assertTrue(any("撤稿" in e for e in errors))
        downgraded = {"change_type": "downgrade", "reason": "重新评级", "study_version": 1}
        warnings, errors = _evaluate(flagged=downgraded)
        self.assertEqual(errors, [])
        self.assertTrue(any("降级" in w for w in warnings))

    def test_high_risk_population_requires_explicit_note(self) -> None:
        scope = dict(SCOPE, population_groups=["绝经后早期女性", "合并心血管高危因素女性"])
        _, errors = _evaluate(scope=scope, high_risk_note="")
        self.assertTrue(any("高风险人群" in e for e in errors))
        _, errors = _evaluate(
            scope=scope, high_risk_note="合并心血管高危因素者需心内科联合评估"
        )
        self.assertEqual([e for e in errors if "高风险" in e], [])


if __name__ == "__main__":
    unittest.main()
