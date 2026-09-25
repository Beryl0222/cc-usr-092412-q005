"""证据边界规则。

每条主张与每份科室措辞都必须落在其引用研究版本所声明的范围内：
人群、年龄、治疗窗口只能是研究的子集；相关结论不得被改写成因果或
普遍建议；排除条件不得被丢弃；不得引用研究未覆盖的终点；引用已被
降级/撤稿/更新的版本必须显式声明。高风险人群内容需要额外复核。

检查结果分两类：``warnings`` 是系统提示（可能遗漏或过度外推，供人工
判断），``errors`` 是硬性违规，阻断冻结。
"""

from __future__ import annotations

from collections.abc import Iterable

from .events import (
    FLAG_DOWNGRADE,
    FLAG_FOLLOWUP_UPDATE,
    FLAG_RETRACTION,
)

# 结论语气的强度序：索引越大主张越强
_RESULT_STRENGTH = {
    "correlation": 0,        # 相关
    "association": 0,        # 关联
    "correlation_adj": 1,    # 校正后相关
    "causation": 2,          # 因果
    "general_recommendation": 3,  # 普遍建议
}

_GENERAL_WORDS = ("所有", "普遍", "人人", "每位", "凡是", "全部", "一律", "一定能", "必然")
# 出现在措辞里即构成过度承诺的硬升级表述
_HARD_ESCALATION_PHRASES = (
    "必然",
    "一定能",
    "肯定能",
    "绝对",
    "保证",
    "无需评估禁忌",
    "无需考虑禁忌",
    "不用考虑禁忌",
    "不需考虑禁忌",
    "无须考虑禁忌",
)


def _subset(claimed: Iterable[str], allowed: Iterable[str]) -> list[str]:
    allowed_set = set(allowed)
    return [item for item in claimed if item not in allowed_set]


def evaluate_scope(
    *,
    statement: str,
    scope: dict,
    not_applicable: list[str],
    limitations_disclosed: list[str],
    result_nature: str,
    evidence_grade: int,
    high_risk_note: str,
    study_version: dict,
    flagged: dict | None,
) -> tuple[list[str], list[str]]:
    """对照研究版本评估主张/措辞的证据范围。

    ``scope`` 包含 population_groups、age_range、treatment_windows、endpoints。
    ``flagged`` 为该研究版本当前最新的证据标记（无则传 None）。
    返回 ``(warnings, errors)``。
    """
    warnings: list[str] = []
    errors: list[str] = []

    # 1. 人群只能是研究人群（含被识别的高风险亚组）的子集
    allowed_groups = set(study_version.get("population_groups", [])) | set(
        study_version.get("high_risk_populations", [])
    )
    extra_groups = _subset(scope.get("population_groups", []), allowed_groups)
    if extra_groups:
        errors.append(f"主张人群超出研究纳入人群：{'、'.join(extra_groups)}")

    # 2. 年龄范围必须落在研究年龄范围内
    claimed_age = scope.get("age_range")
    study_age = study_version.get("age_range")
    if claimed_age and study_age:
        if claimed_age[0] < study_age[0] or claimed_age[1] > study_age[1]:
            errors.append(
                f"主张年龄 {claimed_age[0]}-{claimed_age[1]} 超出研究年龄 "
                f"{study_age[0]}-{study_age[1]}"
            )

    # 3. 治疗窗口只能是研究窗口的子集（逐对包含于某一研究窗口）
    study_windows = study_version.get("treatment_windows", [])
    for window in scope.get("treatment_windows", []):
        if not any(s[0] <= window[0] and window[1] <= s[1] for s in study_windows):
            errors.append(f"治疗窗口 {window[0]}-{window[1]} 不在研究治疗窗口内")

    # 4. 终点必须是研究终点之一
    extra_endpoints = _subset(scope.get("endpoints", []), study_version.get("endpoints", []))
    if extra_endpoints:
        errors.append(f"主张终点未被研究覆盖：{'、'.join(extra_endpoints)}")

    # 5. 排除条件不得丢弃：研究的每条排除条件都应出现在不适用情形中
    dropped = _subset(study_version.get("exclusions", []), not_applicable)
    if dropped:
        errors.append(f"丢弃了研究排除条件，未声明为不适用情形：{'、'.join(dropped)}")

    # 6. 研究限制必须披露
    undisclosed = _subset(study_version.get("limitations", []), limitations_disclosed)
    if undisclosed:
        warnings.append(f"可能遗漏研究限制的披露：{'、'.join(undisclosed)}")

    # 7. 结论语气不得强于统计结论
    study_nature = study_version.get("result_nature", "")
    if _RESULT_STRENGTH.get(result_nature, 0) > _RESULT_STRENGTH.get(study_nature, 0):
        errors.append(
            f"过度外推：研究结论为“{study_nature}”，主张却表述为“{result_nature}”"
        )

    # 8. 普遍化措辞提示
    if any(word in statement for word in _GENERAL_WORDS):
        warnings.append("表述含普遍化措辞，请确认是否把特定条件下的结论写成了普遍建议")

    # 8b. 措辞内的确定性承诺/抛弃禁忌是硬升级，不能被合规的主张元数据洗白
    hit_phrases = [p for p in _HARD_ESCALATION_PHRASES if p in statement]
    if hit_phrases:
        errors.append(
            "措辞含超出统计结论的确定性或抛弃禁忌表述：" + "、".join(hit_phrases)
        )

    # 9. 证据等级不得高于研究版本
    if evidence_grade > study_version.get("evidence_grade", 0):
        errors.append("主张证据等级高于研究版本所支持的等级")

    # 10. 引用被标记版本必须显式声明
    if flagged is not None:
        change = flagged["change_type"]
        if change == FLAG_RETRACTION:
            errors.append("引用的研究版本已撤稿，不得用于新的未冻结材料")
        elif change == FLAG_DOWNGRADE:
            warnings.append("引用的研究版本已降级，须随附降级说明")
        elif change == FLAG_FOLLOWUP_UPDATE:
            warnings.append("存在更新的随访结果，须提示读者以最新随访为准")

    # 11. 高风险人群：必须有显式高风险说明
    claimed_groups = set(scope.get("population_groups", []))
    if claimed_groups & set(study_version.get("high_risk_populations", [])) and not high_risk_note:
        errors.append("涉及高风险人群的内容必须给出显式高风险提示并走额外复核")

    return warnings, errors
