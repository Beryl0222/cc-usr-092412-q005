"""事件回放投影。

把只追加的事件流折叠成当前状态，或折叠到某个历史时点。所有查询
（溯源、撤稿影响面、历史解释）都基于同一份投影逻辑，保证口径一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .events import (
    CLAIM_MAPPED,
    CLAIM_REVISED,
    CORRECTION_ACKNOWLEDGED,
    CORRECTION_ISSUED,
    EVIDENCE_FLAGGED,
    STUDY_REGISTERED,
    STUDY_VERSION_RECORDED,
    VARIANT_APPROVAL_MARKED,
    VARIANT_DISTRIBUTED,
    VARIANT_DRAFTED,
    VARIANT_FROZEN,
    VARIANT_WORDING_REPLACED,
)


@dataclass
class WordingRevision:
    revision: int
    wording: str
    claim_id: str
    claim_revision: int
    usage_scenarios: list[str]
    reason: str | None = None
    approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    frozen_at: str | None = None
    distributed_at: str | None = None
    recipients: list[str] = field(default_factory=list)


@dataclass
class Variant:
    variant_id: str
    department: str
    audience: str
    wording_revisions: dict[int, WordingRevision] = field(default_factory=dict)
    current_revision: int = 0

    @property
    def current(self) -> WordingRevision:
        return self.wording_revisions[self.current_revision]

    @property
    def status(self) -> str:
        wr = self.current
        if wr.distributed_at:
            return "distributed"
        if wr.frozen_at:
            return "frozen"
        return "draft"

    def distributed_revisions(self) -> list[WordingRevision]:
        return [wr for wr in self.wording_revisions.values() if wr.distributed_at]


@dataclass
class CorrectionNotice:
    notice_id: str
    variant_id: str
    study_id: str
    study_version: int
    change_type: str
    risk_handling: str
    requires_ack: bool
    issued_at: str
    affected_wording_revisions: list[int] = field(default_factory=list)
    acks: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class State:
    studies: dict[str, dict[str, Any]] = field(default_factory=dict)
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)
    variants: dict[str, Variant] = field(default_factory=dict)
    notices: dict[str, CorrectionNotice] = field(default_factory=dict)

    # ---- 便捷读取 ----

    def study_version(self, study_id: str, version: int) -> dict[str, Any]:
        return self.studies[study_id]["versions"][version]

    def latest_flag(self, study_id: str, version: int) -> dict[str, Any] | None:
        return self.studies[study_id]["flags"].get(version)

    def claim_revision(self, claim_id: str, revision: int) -> dict[str, Any]:
        return self.claims[claim_id]["revisions"][revision]

    def claim_current(self, claim_id: str) -> dict[str, Any]:
        claim = self.claims[claim_id]
        return claim["revisions"][claim["current_revision"]]

    def variants_referencing(self, study_id: str, study_version: int) -> list[Variant]:
        result: list[Variant] = []
        for variant in self.variants.values():
            refs = set()
            for wr in variant.wording_revisions.values():
                claim_rev = self.claims[wr.claim_id]["revisions"][wr.claim_revision]
                refs.add((claim_rev["study_id"], claim_rev["study_version"]))
            if (study_id, study_version) in refs:
                result.append(variant)
        return result


def project(events: list[dict[str, Any]]) -> State:
    """把事件流（可为某历史时点的切片）折叠成状态。"""
    state = State()

    for event in events:
        etype = event["event_type"]
        payload = event.get("payload", {})
        at = event["occurred_at"]

        if etype == STUDY_REGISTERED:
            state.studies[payload["study_id"]] = {
                "title": payload["title"],
                "registered_at": at,
                "versions": {},
                "flags": {},
            }

        elif etype == STUDY_VERSION_RECORDED:
            study = state.studies[payload["study_id"]]
            study["versions"][payload["study_version"]] = payload

        elif etype == EVIDENCE_FLAGGED:
            study = state.studies[payload["study_id"]]
            # 只保留最新标记；标记本身仍作为独立事件留痕
            study["flags"][payload["study_version"]] = {
                **payload,
                "flagged_at": at,
                "event_id": event["event_id"],
            }

        elif etype == CLAIM_MAPPED:
            state.claims[payload["claim_id"]] = {
                "revisions": {payload["revision"]: payload},
                "current_revision": payload["revision"],
            }

        elif etype == CLAIM_REVISED:
            claim = state.claims[payload["claim_id"]]
            claim["revisions"][payload["revision"]] = payload
            claim["current_revision"] = payload["revision"]

        elif etype == VARIANT_DRAFTED:
            wr = WordingRevision(
                revision=payload["wording_revision"],
                wording=payload["wording"],
                claim_id=payload["claim_id"],
                claim_revision=payload["claim_revision"],
                usage_scenarios=list(payload["usage_scenarios"]),
            )
            variant = Variant(
                variant_id=payload["variant_id"],
                department=payload["department"],
                audience=payload["audience"],
                wording_revisions={wr.revision: wr},
                current_revision=wr.revision,
            )
            state.variants[payload["variant_id"]] = variant

        elif etype == VARIANT_WORDING_REPLACED:
            variant = state.variants[event["aggregate_id"]]
            wr = WordingRevision(
                revision=payload["wording_revision"],
                wording=payload["wording"],
                claim_id=payload["claim_id"],
                claim_revision=payload["claim_revision"],
                usage_scenarios=list(variant.current.usage_scenarios),
                reason=payload["reason"],
            )
            variant.wording_revisions[wr.revision] = wr
            variant.current_revision = wr.revision

        elif etype == VARIANT_APPROVAL_MARKED:
            variant = state.variants[event["aggregate_id"]]
            wr = variant.wording_revisions[payload["wording_revision"]]
            wr.approvals[payload["role"]] = {
                "reviewer": payload["reviewer"],
                "decision": payload["decision"],
                "at": at,
                "event_id": event["event_id"],
            }

        elif etype == VARIANT_FROZEN:
            variant = state.variants[event["aggregate_id"]]
            wr = variant.wording_revisions[payload["wording_revision"]]
            wr.frozen_at = at
            wr.usage_scenarios = list(payload["usage_scenarios"])

        elif etype == VARIANT_DISTRIBUTED:
            variant = state.variants[event["aggregate_id"]]
            wr = variant.wording_revisions[payload["wording_revision"]]
            wr.distributed_at = at
            wr.usage_scenarios = list(payload["usage_scenarios"])
            wr.recipients = list(payload["recipients"])

        elif etype == CORRECTION_ISSUED:
            notice = CorrectionNotice(
                notice_id=payload["notice_id"],
                variant_id=payload["variant_id"],
                study_id=payload["study_id"],
                study_version=payload["study_version"],
                change_type=payload["change_type"],
                risk_handling=payload["risk_handling"],
                requires_ack=payload["requires_ack"],
                issued_at=at,
                affected_wording_revisions=list(payload.get("affected_wording_revisions", [])),
            )
            state.notices[payload["notice_id"]] = notice

        elif etype == CORRECTION_ACKNOWLEDGED:
            notice = state.notices[payload["notice_id"]]
            notice.acks[payload["receiver"]] = {
                "received_at": payload["received_at"],
                "at": at,
                "event_id": event["event_id"],
            }

    return state
