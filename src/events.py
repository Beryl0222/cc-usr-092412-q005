"""领域事件定义与构造。

事件只追加、不原地改写：研究版本、证据标记、主张修订、材料措辞替换、
签署决定、冻结发放与更正回执都各自留下独立记录。载荷字段的命名就是
业务术语，便于从一句公开表述逐级追溯。
"""

from __future__ import annotations

from typing import Any

# ---- 聚合与事件名称 -------------------------------------------------------

RESEARCH_STUDY = "research_study"
PUBLIC_CLAIM = "public_claim"
CONTENT_VARIANT = "content_variant"
CORRECTION_NOTICE = "correction_notice"

AGGREGATE_TYPES = (RESEARCH_STUDY, PUBLIC_CLAIM, CONTENT_VARIANT, CORRECTION_NOTICE)

STUDY_REGISTERED = "STUDY_REGISTERED"
STUDY_VERSION_RECORDED = "STUDY_VERSION_RECORDED"
EVIDENCE_FLAGGED = "EVIDENCE_FLAGGED"
CLAIM_MAPPED = "CLAIM_MAPPED"
CLAIM_REVISED = "CLAIM_REVISED"
VARIANT_DRAFTED = "VARIANT_DRAFTED"
VARIANT_WORDING_REPLACED = "VARIANT_WORDING_REPLACED"
VARIANT_APPROVAL_MARKED = "VARIANT_APPROVAL_MARKED"
VARIANT_FROZEN = "VARIANT_FROZEN"
VARIANT_DISTRIBUTED = "VARIANT_DISTRIBUTED"
CORRECTION_ISSUED = "CORRECTION_ISSUED"
CORRECTION_ACKNOWLEDGED = "CORRECTION_ACKNOWLEDGED"

EVENT_TYPES = (
    STUDY_REGISTERED,
    STUDY_VERSION_RECORDED,
    EVIDENCE_FLAGGED,
    CLAIM_MAPPED,
    CLAIM_REVISED,
    VARIANT_DRAFTED,
    VARIANT_WORDING_REPLACED,
    VARIANT_APPROVAL_MARKED,
    VARIANT_FROZEN,
    VARIANT_DISTRIBUTED,
    CORRECTION_ISSUED,
    CORRECTION_ACKNOWLEDGED,
)

# 证据状态变化类型
FLAG_DOWNGRADE = "downgrade"        # 证据降级
FLAG_RETRACTION = "retraction"      # 撤稿
FLAG_FOLLOWUP_UPDATE = "followup_update"  # 随访更新
FLAG_TYPES = (FLAG_DOWNGRADE, FLAG_RETRACTION, FLAG_FOLLOWUP_UPDATE)

# 签署角色
ROLE_METHODOLOGY = "methodology"    # 研究方法人员：确认解释
ROLE_CLINICIAN = "clinician"        # 临床人员：确认边界
ROLE_EXTRA_REVIEW = "extra_review"  # 高风险人群额外复核
REVIEW_ROLES = (ROLE_METHODOLOGY, ROLE_CLINICIAN, ROLE_EXTRA_REVIEW)

AUDIENCE_PATIENT = "patient"
AUDIENCE_STAFF = "staff"

ENVELOPE_FIELDS = (
    "event_id",
    "event_type",
    "aggregate_type",
    "aggregate_id",
    "occurred_at",
    "version",
    "summary",
)

_PAYLOAD_REQUIRED: dict[str, tuple[str, ...]] = {
    STUDY_REGISTERED: ("study_id", "title"),
    STUDY_VERSION_RECORDED: (
        "study_id",
        "study_version",
        "population_groups",
        "age_range",
        "treatment_windows",
        "endpoints",
        "exclusions",
        "limitations",
        "statistical_conclusion",
        "result_nature",
        "evidence_grade",
        "high_risk_populations",
    ),
    EVIDENCE_FLAGGED: ("study_id", "study_version", "change_type", "reason"),
    CLAIM_MAPPED: (
        "claim_id",
        "revision",
        "statement",
        "study_id",
        "study_version",
        "scope",
        "not_applicable",
        "limitations_disclosed",
        "result_nature",
        "evidence_grade",
        "high_risk_note",
    ),
    CLAIM_REVISED: (
        "claim_id",
        "revision",
        "statement",
        "study_id",
        "study_version",
        "scope",
        "not_applicable",
        "limitations_disclosed",
        "result_nature",
        "evidence_grade",
        "high_risk_note",
        "supersedes_revision",
    ),
    VARIANT_DRAFTED: (
        "variant_id",
        "department",
        "claim_id",
        "claim_revision",
        "audience",
        "wording",
        "usage_scenarios",
        "wording_revision",
    ),
    VARIANT_WORDING_REPLACED: (
        "wording_revision",
        "old_wording",
        "wording",
        "claim_id",
        "claim_revision",
        "reason",
    ),
    VARIANT_APPROVAL_MARKED: (
        "wording_revision",
        "role",
        "reviewer",
        "decision",
    ),
    VARIANT_FROZEN: ("wording_revision", "usage_scenarios"),
    VARIANT_DISTRIBUTED: ("wording_revision", "usage_scenarios", "recipients"),
    CORRECTION_ISSUED: (
        "notice_id",
        "variant_id",
        "study_id",
        "study_version",
        "change_type",
        "risk_handling",
        "requires_ack",
    ),
    CORRECTION_ACKNOWLEDGED: ("notice_id", "receiver", "received_at"),
}


def make_event(
    *,
    event_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    occurred_at: str,
    version: int,
    summary: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """构造一条完整领域事件（追加前调用，不负责落库序号）。"""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"未知事件类型：{event_type}")
    if aggregate_type not in AGGREGATE_TYPES:
        raise ValueError(f"未知聚合类型：{aggregate_type}")
    if not isinstance(version, int) or version < 1:
        raise ValueError("version 必须是正整数")
    missing = [name for name in _PAYLOAD_REQUIRED[event_type] if name not in payload]
    if missing:
        raise ValueError(f"{event_type} 载荷缺少字段：{', '.join(missing)}")
    return {
        "event_id": event_id,
        "event_type": event_type,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "occurred_at": occurred_at,
        "version": version,
        "summary": summary,
        "payload": payload,
    }


def validate_envelope(record: dict[str, Any]) -> list[str]:
    """信封层校验：保留基线行为，并补充枚举一致性检查。"""
    errors = [f"缺少字段：{name}" for name in ENVELOPE_FIELDS if name not in record]
    if "version" in record and (not isinstance(record["version"], int) or record["version"] < 1):
        errors.append("version 必须是正整数")
    if "event_type" in record and record["event_type"] not in EVENT_TYPES:
        errors.append(f"未知事件类型：{record['event_type']}")
    if "aggregate_type" in record and record["aggregate_type"] not in AGGREGATE_TYPES:
        errors.append(f"未知聚合类型：{record['aggregate_type']}")
    if "payload" in record and not isinstance(record["payload"], dict):
        errors.append("payload 必须是对象")
    return errors
