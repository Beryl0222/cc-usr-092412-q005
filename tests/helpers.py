"""测试共用的中文样例与搭建函数。

所有时间戳固定，保证测试可复现。
"""

from src.service import TranslationService

POPULATION = {
    "description": "45–55岁围绝经期女性",
    "age_min": 45,
    "age_max": 55,
    "condition": "围绝经期",
    "exclusions": ["乳腺癌病史", "原因不明的阴道出血"],
}
ENDPOINTS = [
    {"name": "潮热频率", "result": "治疗组潮热频率较安慰剂组下降"},
    {"name": "骨密度", "result": "腰椎骨密度变化无统计学差异"},
]
LIMITATIONS = ["单中心随机对照试验", "随访仅18个月", "排除乳腺癌病史人群"]
STATISTICS = [
    {"endpoint": "潮热频率", "effect": "RR 0.62", "ci": "0.51–0.75", "p": "<0.01"},
    {"endpoint": "骨密度", "effect": "MD 0.4%", "ci": "-0.2–1.0", "p": "0.18"},
]

# 合规措辞：注明年龄范围、时间窗与不适用情形。
CAREFUL_WORDING = (
    "45至55岁围绝经期女性在绝经10年内的时间窗内起始激素治疗，"
    "可能减少潮热发作；乳腺癌病史或原因不明的阴道出血者不适用。"
)
BONE_WORDING = "在45至55岁围绝经期女性中，现有证据未显示激素治疗对腰椎骨密度有统计学意义的改善。"
# 媒体摘要式的问题措辞：普遍化、越界年龄、缺少不适用情形。
OVERGENERAL_WORDING = "所有女性都适合激素治疗。"
OUT_OF_RANGE_AGE_WORDING = "62岁女性起始激素治疗同样获益。"


def register_base_study(service: TranslationService, at: str = "2026-09-01T09:00:00+08:00") -> None:
    service.register_study(
        "STU-HT-001",
        version_label="v2026.1",
        population=POPULATION,
        endpoints=ENDPOINTS,
        limitations=LIMITATIONS,
        statistics=STATISTICS,
        occurred_at=at,
    )


def map_base_claims(service: TranslationService, at: str = "2026-09-02T09:00:00+08:00") -> None:
    service.map_claim(
        "CLM-HOTFLASH",
        study_id="STU-HT-001",
        audience="patient",
        statement="激素治疗可减轻45–55岁围绝经期女性的潮热症状",
        evidence_scope={
            "endpoints": ["潮热频率"],
            "population": "45–55岁围绝经期女性",
            "window": "绝经10年内",
        },
        non_applicable=["乳腺癌病史", "原因不明的阴道出血"],
        occurred_at=at,
    )
    service.map_claim(
        "CLM-BONE",
        study_id="STU-HT-001",
        audience="patient",
        statement="激素治疗对腰椎骨密度的改善未显示统计学意义",
        evidence_scope={"endpoints": ["骨密度"], "population": "45–55岁围绝经期女性"},
        non_applicable=[],
        occurred_at=at,
    )


def make_service() -> TranslationService:
    service = TranslationService()
    register_base_study(service)
    map_base_claims(service)
    return service


def draft_and_check(
    service: TranslationService,
    variant_id: str,
    *,
    department: str = "妇科门诊",
    items: dict | None = None,
    risk: str = "general",
    at: str = "2026-09-03T09:00:00+08:00",
) -> list:
    service.draft_material(
        variant_id,
        department=department,
        audience="patient",
        population_risk=risk,
        items=items or {"CLM-HOTFLASH": CAREFUL_WORDING},
        occurred_at=at,
    )
    return service.run_checks(variant_id, occurred_at=at)


def sign_both(service: TranslationService, variant_id: str, at: str = "2026-09-03T10:00:00+08:00") -> None:
    service.sign_off(
        variant_id, role="methodology", reviewer="方法学-林", note="解释与研究结论一致", occurred_at=at
    )
    service.sign_off(
        variant_id, role="clinical", reviewer="临床-赵", note="措辞未突破证据边界", occurred_at=at
    )


def approve_and_distribute(
    service: TranslationService,
    variant_id: str,
    *,
    scenarios: list[str] | None = None,
    at: str = "2026-09-03T11:00:00+08:00",
) -> None:
    service.approve(variant_id, scenarios=scenarios or ["门诊宣教"], occurred_at=at)
    service.distribute(variant_id, occurred_at=at)
