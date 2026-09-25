"""溯源查询：从一句公开表述追到研究限制、签署决定、使用范围与后续更正。

另提供历史时点解释：按指定时间截断日志重放，重建当时对一条主张
的理解，不受后续证据更新影响。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.events import DomainError
from src.service import TranslationService
from src.state import State, build_state


def trace(service: TranslationService, query: str) -> list[dict[str, Any]]:
    """按主张标识或公开表述片段查询完整溯源记录。"""
    state = service.state
    claim_ids: list[str] = []
    if query in state.claims:
        claim_ids.append(query)
    for claim_id, claim in state.claims.items():
        if claim_id not in claim_ids and query in claim.statement:
            claim_ids.append(claim_id)
    for variant in state.variants.values():
        for claim_id, wording in variant.items.items():
            if claim_id not in claim_ids and query in wording:
                claim_ids.append(claim_id)
    return [_trace_record(state, claim_id) for claim_id in claim_ids]


def explain_at(service: TranslationService, claim_id: str, as_of: str) -> dict[str, Any]:
    """重建某一历史时点对一条主张的解释。"""
    state = build_state(service.log.up_to(as_of))
    if claim_id not in state.claims:
        return {"claim_id": claim_id, "as_of": as_of, "exists": False}
    claim = state.claims[claim_id]
    study = state.studies[claim.study_id]
    version = study.version(claim.study_version)
    endpoints = claim.evidence_scope["endpoints"]
    updates = [
        deepcopy(update)
        for update in study.updates
        if update["endpoints"] == "all" or set(update["endpoints"]) & set(endpoints)
    ]
    materials = [
        {"variant_id": variant.variant_id, "status": variant.status, "revision": variant.revision}
        for variant in state.variants.values()
        if claim_id in variant.items
    ]
    corrections = [
        notice_id
        for variant in state.variants.values()
        if claim_id in variant.items
        for notice_id in variant.corrections
        if claim_id in state.notices[notice_id].claims
    ]
    return {
        "claim_id": claim_id,
        "as_of": as_of,
        "exists": True,
        "statement": claim.statement,
        "study_id": study.study_id,
        "study_version": claim.study_version,
        "limitations": list(version.limitations),
        "evidence_status": study.status_for(endpoints),
        "evidence_updates": updates,
        "materials": materials,
        "corrections": corrections,
    }


def pending_receipts(service: TranslationService, notice_id: str) -> list[str]:
    """尚未确认接收风险处置的接收方。"""
    notice = service.state.notices.get(notice_id)
    if notice is None:
        raise DomainError(f"未知更正通知：{notice_id}")
    return [dept for dept in notice.required_recipients if dept not in notice.receipts]


def _trace_record(state: State, claim_id: str) -> dict[str, Any]:
    claim = state.claims[claim_id]
    study = state.studies[claim.study_id]
    version = study.version(claim.study_version)
    materials = []
    for variant in state.variants.values():
        if claim_id not in variant.items:
            continue
        corrections = []
        for notice_id in variant.corrections:
            notice = state.notices[notice_id]
            if claim_id not in notice.claims:
                continue
            corrections.append(
                {
                    "notice_id": notice_id,
                    "kind": notice.kind,
                    "disposition": notice.disposition,
                    "published_at": notice.published_at,
                    "receipts": dict(notice.receipts),
                    "pending": [
                        dept
                        for dept in notice.required_recipients
                        if dept not in notice.receipts
                    ],
                }
            )
        materials.append(
            {
                "variant_id": variant.variant_id,
                "department": variant.department,
                "wording": variant.items[claim_id],
                "status": variant.status,
                "revision": variant.revision,
                "scenarios": list(variant.scenarios),
                "signoffs": [
                    {"role": role, "reviewer": signoff["reviewer"], "at": signoff["at"]}
                    for role, signoff in variant.signoffs.items()
                ],
                "distributed_at": variant.distributed_at,
                "corrections": corrections,
            }
        )
    return {
        "claim_id": claim_id,
        "statement": claim.statement,
        "audience": claim.audience,
        "evidence_scope": deepcopy(claim.evidence_scope),
        "non_applicable": list(claim.non_applicable),
        "study": {
            "study_id": study.study_id,
            "version": claim.study_version,
            "limitations": list(version.limitations),
            "population": deepcopy(version.population),
            "evidence_status": study.status_for(claim.evidence_scope["endpoints"]),
        },
        "materials": materials,
    }
