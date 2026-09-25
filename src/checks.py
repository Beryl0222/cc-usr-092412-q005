"""措辞体检：对材料措辞做确定性检查，提示遗漏与过度外推。

体检结果只是提示，不作裁断；是否放行由研究方法人员确认解释、
临床人员确认边界的签署决定。
"""

from __future__ import annotations

import re
from typing import Any

# 把受限人群结论说成普遍建议的措辞。
UNIVERSAL_PHRASES = (
    "所有女性",
    "所有患者",
    "所有人",
    "任何年龄",
    "任何人群",
    "人人适用",
    "普遍适用",
    "都适合",
)
# 标注不适用情形的常见措辞。
CONTRA_MARKERS = ("不适用", "除外", "禁忌", "避免使用")
# 标注治疗时间窗的常见措辞。
WINDOW_MARKERS = ("时间窗", "窗口", "年内")

_AGE_PATTERN = re.compile(r"(\d{1,3})\s*岁")


def _age_bounds(evidence_scope: dict, study_population: dict) -> tuple[Any, Any]:
    """年龄边界优先取主张声明的证据范围，缺省回落到研究人群。"""
    age_min = evidence_scope.get("age_min", study_population.get("age_min"))
    age_max = evidence_scope.get("age_max", study_population.get("age_max"))
    return age_min, age_max


def check_wording(
    *,
    evidence_scope: dict,
    non_applicable: list[str],
    study_population: dict,
    wording: str,
) -> list[dict[str, str]]:
    """返回针对一条措辞的提示列表；每条提示含 kind 与 message。"""
    prompts: list[dict[str, str]] = []
    age_min, age_max = _age_bounds(evidence_scope, study_population)
    restricted = bool(
        age_min is not None or age_max is not None or study_population.get("exclusions")
    )

    if restricted:
        for phrase in UNIVERSAL_PHRASES:
            if phrase in wording:
                prompts.append(
                    {
                        "kind": "over_extrapolation",
                        "message": f"“{phrase}”把受限人群的结论说成了普遍建议",
                    }
                )

    for match in _AGE_PATTERN.finditer(wording):
        age = int(match.group(1))
        if (age_min is not None and age < age_min) or (
            age_max is not None and age > age_max
        ):
            prompts.append(
                {
                    "kind": "over_extrapolation",
                    "message": f"措辞提及{age}岁，超出研究人群年龄范围（{age_min}–{age_max}岁）",
                }
            )

    if non_applicable and not any(marker in wording for marker in CONTRA_MARKERS):
        prompts.append(
            {"kind": "omission", "message": "未标注主张声明的不适用情形"}
        )

    if (age_min is not None or age_max is not None) and "岁" not in wording:
        prompts.append(
            {"kind": "omission", "message": "未注明研究人群的年龄范围"}
        )

    if evidence_scope.get("window") and not any(
        marker in wording for marker in WINDOW_MARKERS
    ):
        prompts.append(
            {"kind": "omission", "message": "未注明证据所限定的时间窗"}
        )

    return prompts
