"""由事件日志重放出的读模型。

当前态与历史时点共用同一段重放逻辑：历史时点只是先把日志按
occurred_at 截断再重放，保证两种视图语义一致。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable

from src.events import Event

# 证据状态严重度：多条证据更新叠加时取最重的一档。
SEVERITY = {"valid": 0, "followup": 1, "downgraded": 2, "retracted": 3}
_UPDATE_STATUS = {"followup": "followup", "downgrade": "downgraded", "retraction": "retracted"}


@dataclass
class StudyVersion:
    """一次研究登记留痕：版本、人群、终点、限制条件、统计结论分别保存。"""

    label: str
    population: dict[str, Any]
    endpoints: list[dict[str, Any]]
    limitations: list[str]
    statistics: list[dict[str, Any]]
    registered_at: str


@dataclass
class StudyState:
    study_id: str
    versions: list[StudyVersion] = field(default_factory=list)
    updates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def current(self) -> StudyVersion:
        return self.versions[-1]

    def version(self, label: str) -> StudyVersion | None:
        for item in self.versions:
            if item.label == label:
                return item
        return None

    def endpoint_names(self) -> set[str]:
        return {endpoint["name"] for version in self.versions for endpoint in version.endpoints}

    def status_for(self, endpoint_names: Iterable[str]) -> str:
        """给定终点集合，返回叠加所有证据更新后的最严重状态。"""
        worst = "valid"
        targets = set(endpoint_names)
        for update in self.updates:
            if update["endpoints"] != "all" and not (set(update["endpoints"]) & targets):
                continue
            status = _UPDATE_STATUS[update["kind"]]
            if SEVERITY[status] > SEVERITY[worst]:
                worst = status
        return worst


@dataclass
class ClaimState:
    claim_id: str
    study_id: str
    study_version: str
    audience: str
    statement: str
    evidence_scope: dict[str, Any]
    non_applicable: list[str]
    mapped_at: str


@dataclass
class VariantState:
    variant_id: str
    department: str
    audience: str
    population_risk: str
    revision: int
    items: dict[str, str]
    status: str = "draft"  # draft → approved → distributed；待修订为 needs_revision
    scenarios: list[str] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    checks_revision: int | None = None
    signoffs: dict[str, dict[str, Any]] = field(default_factory=dict)
    impacted: set[str] = field(default_factory=set)
    recipients: list[str] = field(default_factory=list)
    distributed_at: str | None = None
    corrections: list[str] = field(default_factory=list)


@dataclass
class NoticeState:
    notice_id: str
    variant_id: str
    study_id: str
    kind: str
    claims: list[str]
    disposition: str
    published_at: str
    required_recipients: list[str]
    receipts: dict[str, str] = field(default_factory=dict)


@dataclass
class State:
    studies: dict[str, StudyState] = field(default_factory=dict)
    claims: dict[str, ClaimState] = field(default_factory=dict)
    variants: dict[str, VariantState] = field(default_factory=dict)
    notices: dict[str, NoticeState] = field(default_factory=dict)


def _study_registered(state: State, event: Event) -> None:
    payload = event.payload
    study = state.studies.setdefault(event.aggregate_id, StudyState(event.aggregate_id))
    study.versions.append(
        StudyVersion(
            label=payload["study_version"],
            population=deepcopy(payload["population"]),
            endpoints=deepcopy(payload["endpoints"]),
            limitations=list(payload["limitations"]),
            statistics=deepcopy(payload["statistics"]),
            registered_at=event.occurred_at,
        )
    )


def _claim_mapped(state: State, event: Event) -> None:
    payload = event.payload
    state.claims[event.aggregate_id] = ClaimState(
        claim_id=event.aggregate_id,
        study_id=payload["study_id"],
        study_version=payload["study_version"],
        audience=payload["audience"],
        statement=payload["statement"],
        evidence_scope=deepcopy(payload["evidence_scope"]),
        non_applicable=list(payload["non_applicable"]),
        mapped_at=event.occurred_at,
    )


def _material_drafted(state: State, event: Event) -> None:
    payload = event.payload
    state.variants[event.aggregate_id] = VariantState(
        variant_id=event.aggregate_id,
        department=payload["department"],
        audience=payload["audience"],
        population_risk=payload["population_risk"],
        revision=payload["revision"],
        items=deepcopy(payload["items"]),
    )


def _checks_recorded(state: State, event: Event) -> None:
    variant = state.variants[event.aggregate_id]
    variant.checks = deepcopy(event.payload["prompts"])
    variant.checks_revision = event.payload["revision"]


def _signoff_recorded(state: State, event: Event) -> None:
    payload = event.payload
    state.variants[event.aggregate_id].signoffs[payload["role"]] = {
        "reviewer": payload["reviewer"],
        "note": payload["note"],
        "at": event.occurred_at,
        "revision": payload["revision"],
    }


def _content_approved(state: State, event: Event) -> None:
    variant = state.variants[event.aggregate_id]
    variant.status = "approved"
    variant.scenarios = list(event.payload["scenarios"])


def _content_distributed(state: State, event: Event) -> None:
    variant = state.variants[event.aggregate_id]
    variant.status = "distributed"
    variant.recipients = list(event.payload["recipients"])
    variant.distributed_at = event.occurred_at


def _evidence_updated(state: State, event: Event) -> None:
    payload = event.payload
    state.studies[event.aggregate_id].updates.append(
        {
            "kind": payload["kind"],
            "endpoints": deepcopy(payload["endpoints"]),
            "rationale": payload["rationale"],
            "at": event.occurred_at,
        }
    )


def _material_flagged(state: State, event: Event) -> None:
    variant = state.variants[event.aggregate_id]
    variant.impacted |= set(event.payload["claims"])
    variant.status = "needs_revision"


def _material_revised(state: State, event: Event) -> None:
    payload = event.payload
    variant = state.variants[event.aggregate_id]
    for claim_id, wording in payload["changed"].items():
        variant.items[claim_id] = wording
    for claim_id in payload["removed"]:
        variant.items.pop(claim_id, None)
    variant.revision = payload["revision"]
    variant.signoffs = {}
    variant.checks = []
    variant.checks_revision = None
    variant.impacted -= set(payload["changed"]) | set(payload["removed"])
    if not variant.impacted and variant.status == "needs_revision":
        variant.status = "draft"


def _correction_published(state: State, event: Event) -> None:
    payload = event.payload
    state.notices[event.aggregate_id] = NoticeState(
        notice_id=event.aggregate_id,
        variant_id=payload["variant_id"],
        study_id=payload["study_id"],
        kind=payload["kind"],
        claims=list(payload["claims"]),
        disposition=payload["disposition"],
        published_at=event.occurred_at,
        required_recipients=list(payload["required_recipients"]),
    )
    state.variants[payload["variant_id"]].corrections.append(event.aggregate_id)


def _receipt_confirmed(state: State, event: Event) -> None:
    notice = state.notices[event.aggregate_id]
    notice.receipts[event.payload["department"]] = event.occurred_at


_HANDLERS = {
    "STUDY_REGISTERED": _study_registered,
    "CLAIM_MAPPED": _claim_mapped,
    "MATERIAL_DRAFTED": _material_drafted,
    "CHECKS_RECORDED": _checks_recorded,
    "SIGNOFF_RECORDED": _signoff_recorded,
    "CONTENT_APPROVED": _content_approved,
    "CONTENT_DISTRIBUTED": _content_distributed,
    "EVIDENCE_UPDATED": _evidence_updated,
    "MATERIAL_FLAGGED": _material_flagged,
    "MATERIAL_REVISED": _material_revised,
    "CORRECTION_PUBLISHED": _correction_published,
    "RECEIPT_CONFIRMED": _receipt_confirmed,
}


def build_state(events: Iterable[Event]) -> State:
    state = State()
    for event in events:
        handler = _HANDLERS.get(event.event_type)
        if handler is not None:
            handler(state, event)
    return state
