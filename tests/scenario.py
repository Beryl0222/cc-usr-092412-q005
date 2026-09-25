"""测试共用场景。

背景：一项绝经激素治疗（MHT）与冠心病事件相关性的队列研究。媒体摘要
把“绝经 10 年内、限定年龄、排除禁忌证人群中的校正后相关”写成了面向
所有更年期女性的普遍建议。夹具用它构造正确主张、越界主张与各科室材料。
"""

from __future__ import annotations

import copy

from src.service import TranslationService
from src.store import EventStore

STUDY_ID = "study-mht-chd-2026"

STUDY_VERSION = dict(
    study_version=1,
    population_groups=["围绝经期女性", "绝经后早期女性"],
    age_range=(45, 55),
    treatment_windows=[(0, 10)],  # 绝经年限 0-10 年
    endpoints=["冠心病事件", "潮热评分"],
    exclusions=["乳腺癌病史", "不明原因阴道出血", "活动性静脉血栓"],
    limitations=["观察性研究，不能排除残余混杂", "东亚人群占比低"],
    statistical_conclusion=(
        "绝经 10 年内启动 MHT 与冠心病事件风险降低相关（HR 0.78，95%CI 0.62-0.98）"
    ),
    result_nature="correlation_adj",
    evidence_grade=2,
    high_risk_populations=["合并心血管高危因素女性"],
)

SCOPE = dict(
    population_groups=["绝经后早期女性"],
    age_range=(45, 55),
    treatment_windows=[(0, 10)],
    endpoints=["冠心病事件"],
)

NOT_APPLICABLE = [
    "乳腺癌病史",
    "不明原因阴道出血",
    "活动性静脉血栓",
    "绝经超过 10 年或 60 岁以后启动者",
]

CORRECT_CLAIM = dict(
    claim_id="claim-window-correlation",
    statement=(
        "绝经 10 年内、45-55 岁且无禁忌证的女性，启动 MHT 与冠心病事件风险降低相关；"
        "该结果为相关性，不等于普遍预防建议。"
    ),
    scope=SCOPE,
    not_applicable=NOT_APPLICABLE,
    limitations_disclosed=STUDY_VERSION["limitations"],
    result_nature="correlation_adj",
    evidence_grade=2,
)

# 媒体摘要式越界主张：扩大人群/年龄/窗口/终点、丢弃排除条件、
# 把相关写成普遍建议。
MEDIA_OVERREACH = dict(
    claim_id="claim-media-overreach",
    statement="所有更年期女性都应启动激素治疗，能预防冠心病和死亡",
    scope=dict(
        population_groups=["绝经后早期女性", "绝经后晚期女性"],
        age_range=(45, 70),
        treatment_windows=[(0, 20)],
        endpoints=["冠心病事件", "全因死亡率"],
    ),
    not_applicable=[],
    limitations_disclosed=[],
    result_nature="general_recommendation",
    evidence_grade=4,
)

GY_WORDING = (
    "给妇科门诊患者：如果您在绝经 10 年内、年龄 45-55 岁且无乳腺癌病史、"
    "不明原因阴道出血或活动性血栓，研究观察到启动 MHT 与冠心病事件减少相关，"
    "但这不是对所有人的建议，具体请与医生讨论。"
)

GP_WORDING = (
    "全科知情单：限定绝经 10 年内、45-55 岁、无禁忌证人群，MHT 与冠心病事件"
    "风险降低呈校正后相关；观察性数据存在残余混杂，不作为普遍推荐。"
)

HIGH_RISK_SCOPE = dict(
    population_groups=["绝经后早期女性", "合并心血管高危因素女性"],
    age_range=(45, 55),
    treatment_windows=[(0, 10)],
    endpoints=["冠心病事件"],
)


def build_registered_service() -> TranslationService:
    """登记研究并记录 v1，未含任何主张与材料。"""
    svc = TranslationService(EventStore())
    svc.register_study(
        study_id=STUDY_ID,
        title="绝经早期 MHT 与冠心病事件相关性队列研究",
        occurred_at="2026-09-01T09:00:00+08:00",
    )
    svc.record_study_version(
        study_id=STUDY_ID,
        occurred_at="2026-09-01T09:05:00+08:00",
        **STUDY_VERSION,
    )
    return svc


def build_service_with_claim() -> TranslationService:
    svc = build_registered_service()
    fields = copy.deepcopy(CORRECT_CLAIM)
    svc.map_claim(occurred_at="2026-09-02T09:00:00+08:00", study_id=STUDY_ID,
                  study_version=1, **fields)
    return svc


def sign_and_freeze(
    svc: TranslationService,
    variant_id: str,
    *,
    occurred_at: str,
    high_risk: bool = False,
    scenarios: list[str] | None = None,
) -> None:
    svc.mark_approval(
        variant_id=variant_id, role="methodology", reviewer="方法学-林",
        decision="confirmed", occurred_at=occurred_at,
    )
    svc.mark_approval(
        variant_id=variant_id, role="clinician", reviewer="临床-周",
        decision="confirmed", occurred_at=occurred_at,
    )
    if high_risk:
        svc.mark_approval(
            variant_id=variant_id, role="extra_review", reviewer="高危复核-秦",
            decision="confirmed", occurred_at=occurred_at,
        )
    svc.freeze_for_scenarios(
        variant_id=variant_id,
        usage_scenarios=scenarios or ["妇科门诊候诊区纸质材料"],
        occurred_at=occurred_at,
    )
