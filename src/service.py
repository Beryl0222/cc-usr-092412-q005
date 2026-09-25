"""应用服务：从研究登记到材料发放、撤稿传播与溯源的全部用例。

调用方显式传入 ``occurred_at``，事件 id 由聚合与版本确定性生成，
因此同输入在任何机器上重放结果一致（确定性测试可直接断言事件流）。
"""

from __future__ import annotations

from typing import Any

from .boundaries import evaluate_scope
from .errors import DomainError
from .events import (
    AUDIENCE_PATIENT,
    CLAIM_MAPPED,
    CLAIM_REVISED,
    CONTENT_VARIANT,
    CORRECTION_ACKNOWLEDGED,
    CORRECTION_ISSUED,
    CORRECTION_NOTICE,
    EVIDENCE_FLAGGED,
    FLAG_DOWNGRADE,
    FLAG_FOLLOWUP_UPDATE,
    FLAG_RETRACTION,
    FLAG_TYPES,
    PUBLIC_CLAIM,
    RESEARCH_STUDY,
    ROLE_CLINICIAN,
    ROLE_EXTRA_REVIEW,
    ROLE_METHODOLOGY,
    REVIEW_ROLES,
    STUDY_REGISTERED,
    STUDY_VERSION_RECORDED,
    VARIANT_APPROVAL_MARKED,
    VARIANT_DISTRIBUTED,
    VARIANT_DRAFTED,
    VARIANT_FROZEN,
    VARIANT_WORDING_REPLACED,
    make_event,
)
from .projection import State, WordingRevision, project
from .store import EventStore

_CHANGE_LABELS = {
    FLAG_DOWNGRADE: "证据降级",
    FLAG_RETRACTION: "撤稿",
    FLAG_FOLLOWUP_UPDATE: "随访更新",
}


class TranslationService:
    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    # ---- 回放 ----

    def _state(self, as_of: str | None = None) -> State:
        return project(self.store.stream(occurred_by=as_of))

    # ---- 研究与证据 ----

    def register_study(self, *, study_id: str, title: str, occurred_at: str) -> dict[str, Any]:
        return self._emit(
            study_id,
            RESEARCH_STUDY,
            STUDY_REGISTERED,
            occurred_at,
            f"登记研究：{title}",
            {"study_id": study_id, "title": title},
        )

    def record_study_version(
        self,
        *,
        study_id: str,
        study_version: int,
        population_groups: list[str],
        age_range: tuple[int, int],
        treatment_windows: list[tuple[int, int]],
        endpoints: list[str],
        exclusions: list[str],
        limitations: list[str],
        statistical_conclusion: str,
        result_nature: str,
        evidence_grade: int,
        high_risk_populations: list[str],
        occurred_at: str,
    ) -> dict[str, Any]:
        if study_id not in self._state().studies:
            raise DomainError(f"研究未登记：{study_id}")
        payload = {
            "study_id": study_id,
            "study_version": study_version,
            "population_groups": list(population_groups),
            "age_range": list(age_range),
            "treatment_windows": [list(w) for w in treatment_windows],
            "endpoints": list(endpoints),
            "exclusions": list(exclusions),
            "limitations": list(limitations),
            "statistical_conclusion": statistical_conclusion,
            "result_nature": result_nature,
            "evidence_grade": evidence_grade,
            "high_risk_populations": list(high_risk_populations),
        }
        return self._emit(
            study_id,
            RESEARCH_STUDY,
            STUDY_VERSION_RECORDED,
            occurred_at,
            f"记录研究 {study_id} 版本 v{study_version}：{statistical_conclusion}",
            payload,
        )

    def flag_evidence(
        self,
        *,
        study_id: str,
        study_version: int,
        change_type: str,
        reason: str,
        risk_handling: str,
        occurred_at: str,
        require_ack: bool = True,
    ) -> dict[str, Any]:
        """记录证据降级/撤稿/随访更新，并按冻结状态定向传播。

        - 引用该版本的未冻结（草稿）材料：列入 affected_unfrozen；撤稿时
          后续冻结被硬阻断，降级/随访更新则随附强制提示供人工判断；
        - 已冻结未发放：列入 frozen_pending，冻结决定不被追溯改写，
          但发放前必须由人工处理（撤稿直接阻断发放）；
        - 已发放材料：自动追加更正通知（风险处置 + 接收确认）。
        """
        if change_type not in FLAG_TYPES:
            raise DomainError(f"未知证据变化类型：{change_type}")
        state = self._state()
        if study_id not in state.studies or study_version not in state.studies[study_id]["versions"]:
            raise DomainError(f"研究 {study_id} 不存在版本 v{study_version}")

        flag_event = self._emit(
            study_id,
            RESEARCH_STUDY,
            EVIDENCE_FLAGGED,
            occurred_at,
            f"{_CHANGE_LABELS[change_type]}：{study_id} v{study_version}（{reason}）",
            {
                "study_id": study_id,
                "study_version": study_version,
                "change_type": change_type,
                "reason": reason,
            },
        )

        affected_unfrozen: list[str] = []
        frozen_pending: list[str] = []
        notice_ids: list[str] = []

        for variant in state.variants.values():
            for wr in variant.wording_revisions.values():
                claim_rev = state.claims[wr.claim_id]["revisions"][wr.claim_revision]
                if (claim_rev["study_id"], claim_rev["study_version"]) != (study_id, study_version):
                    continue
                ref = f"{variant.variant_id}@r{wr.revision}"
                if wr.distributed_at:
                    notice_id = f"corr-{variant.variant_id}-r{wr.revision}-{flag_event['event_id']}"
                    self._emit(
                        notice_id,
                        CORRECTION_NOTICE,
                        CORRECTION_ISSUED,
                        occurred_at,
                        f"更正通知：{ref} 引用的 {study_id} v{study_version} 发生{_CHANGE_LABELS[change_type]}",
                        {
                            "notice_id": notice_id,
                            "variant_id": variant.variant_id,
                            "study_id": study_id,
                            "study_version": study_version,
                            "change_type": change_type,
                            "risk_handling": risk_handling,
                            "requires_ack": require_ack,
                            "affected_wording_revisions": [wr.revision],
                        },
                    )
                    notice_ids.append(notice_id)
                elif wr.frozen_at:
                    frozen_pending.append(ref)
                else:
                    affected_unfrozen.append(ref)

        return {
            "flag_event_id": flag_event["event_id"],
            "affected_unfrozen": affected_unfrozen,
            "frozen_pending_distribution": frozen_pending,
            "correction_notices": notice_ids,
        }

    def acknowledge_correction(
        self, *, notice_id: str, receiver: str, received_at: str
    ) -> dict[str, Any]:
        state = self._state()
        notice = state.notices.get(notice_id)
        if notice is None:
            raise DomainError(f"更正通知不存在：{notice_id}")
        recipients: set[str] = set()
        for rev in notice.affected_wording_revisions:
            recipients.update(state.variants[notice.variant_id].wording_revisions[rev].recipients)
        if receiver not in recipients:
            raise DomainError(f"接收人 {receiver} 不在该更正通知的发放名单内")
        if receiver in notice.acks:
            raise DomainError(f"接收人 {receiver} 已确认过该通知")
        return self._emit(
            notice_id,
            CORRECTION_NOTICE,
            CORRECTION_ACKNOWLEDGED,
            received_at,
            f"{receiver} 确认收到更正通知 {notice_id}",
            {"notice_id": notice_id, "receiver": receiver, "received_at": received_at},
        )

    # ---- 主张 ----

    def map_claim(
        self,
        *,
        claim_id: str,
        statement: str,
        study_id: str,
        study_version: int,
        scope: dict[str, Any],
        not_applicable: list[str],
        limitations_disclosed: list[str],
        result_nature: str,
        evidence_grade: int,
        high_risk_note: str = "",
        occurred_at: str,
    ) -> dict[str, Any]:
        """把一句公开表述映射到具体研究版本，并强制声明证据范围。"""
        if claim_id in self._state().claims:
            raise DomainError(f"主张已存在，应使用 revise_claim：{claim_id}")
        warnings, errors = self._check(
            statement=statement,
            scope=scope,
            not_applicable=not_applicable,
            limitations_disclosed=limitations_disclosed,
            result_nature=result_nature,
            evidence_grade=evidence_grade,
            high_risk_note=high_risk_note,
            study_id=study_id,
            study_version=study_version,
        )
        if errors:
            raise DomainError("主张超出证据边界：" + "；".join(errors))
        payload = {
            "claim_id": claim_id,
            "revision": 1,
            "statement": statement,
            "study_id": study_id,
            "study_version": study_version,
            "scope": _normalize_scope(scope),
            "not_applicable": list(not_applicable),
            "limitations_disclosed": list(limitations_disclosed),
            "result_nature": result_nature,
            "evidence_grade": evidence_grade,
            "high_risk_note": high_risk_note,
            "system_warnings": warnings,
        }
        event = self._emit(
            claim_id, PUBLIC_CLAIM, CLAIM_MAPPED, occurred_at,
            f"映射主张：{statement}", payload,
        )
        event["warnings"] = warnings
        return event

    def revise_claim(self, *, claim_id: str, occurred_at: str, **fields: Any) -> dict[str, Any]:
        state = self._state()
        if claim_id not in state.claims:
            raise DomainError(f"主张不存在：{claim_id}")
        current = state.claim_current(claim_id)
        merged = {
            "statement": current["statement"],
            "study_id": current["study_id"],
            "study_version": current["study_version"],
            "scope": dict(current["scope"]),
            "not_applicable": list(current["not_applicable"]),
            "limitations_disclosed": list(current["limitations_disclosed"]),
            "result_nature": current["result_nature"],
            "evidence_grade": current["evidence_grade"],
            "high_risk_note": current.get("high_risk_note", ""),
        }
        merged.update(fields)
        warnings, errors = self._check(
            statement=merged["statement"],
            scope=merged["scope"],
            not_applicable=merged["not_applicable"],
            limitations_disclosed=merged["limitations_disclosed"],
            result_nature=merged["result_nature"],
            evidence_grade=merged["evidence_grade"],
            high_risk_note=merged["high_risk_note"],
            study_id=merged["study_id"],
            study_version=merged["study_version"],
        )
        if errors:
            raise DomainError("修订后主张超出证据边界：" + "；".join(errors))
        revision = state.claims[claim_id]["current_revision"] + 1
        payload = {
            "claim_id": claim_id,
            "revision": revision,
            "supersedes_revision": current["revision"],
            "statement": merged["statement"],
            "study_id": merged["study_id"],
            "study_version": merged["study_version"],
            "scope": _normalize_scope(merged["scope"]),
            "not_applicable": merged["not_applicable"],
            "limitations_disclosed": merged["limitations_disclosed"],
            "result_nature": merged["result_nature"],
            "evidence_grade": merged["evidence_grade"],
            "high_risk_note": merged["high_risk_note"],
            "system_warnings": warnings,
        }
        event = self._emit(
            claim_id, PUBLIC_CLAIM, CLAIM_REVISED, occurred_at,
            f"修订主张 r{revision}：{merged['statement']}", payload,
        )
        event["warnings"] = warnings
        return event

    # ---- 科室措辞变体 ----

    def draft_variant(
        self,
        *,
        variant_id: str,
        department: str,
        claim_id: str,
        audience: str = AUDIENCE_PATIENT,
        wording: str,
        usage_scenarios: list[str],
        occurred_at: str,
        claim_revision: int | None = None,
    ) -> dict[str, Any]:
        state = self._state()
        if variant_id in state.variants:
            raise DomainError(f"变体已存在，应使用 replace_wording：{variant_id}")
        claim_rev = self._claim_at(state, claim_id, claim_revision)
        warnings, errors = self._check(
            statement=wording,
            scope=claim_rev["scope"],
            not_applicable=claim_rev["not_applicable"],
            limitations_disclosed=claim_rev["limitations_disclosed"],
            result_nature=claim_rev["result_nature"],
            evidence_grade=claim_rev["evidence_grade"],
            high_risk_note=claim_rev.get("high_risk_note", ""),
            study_id=claim_rev["study_id"],
            study_version=claim_rev["study_version"],
        )
        if errors:
            raise DomainError("科室措辞突破证据边界：" + "；".join(errors))
        payload = {
            "variant_id": variant_id,
            "department": department,
            "claim_id": claim_id,
            "claim_revision": claim_rev["revision"],
            "audience": audience,
            "wording": wording,
            "usage_scenarios": list(usage_scenarios),
            "wording_revision": 1,
            "system_warnings": warnings,
        }
        event = self._emit(
            variant_id, CONTENT_VARIANT, VARIANT_DRAFTED, occurred_at,
            f"{department}起草材料 r1：{wording}", payload,
        )
        event["warnings"] = warnings
        return event

    def replace_wording(
        self,
        *,
        variant_id: str,
        wording: str,
        reason: str,
        occurred_at: str,
        claim_revision: int | None = None,
    ) -> dict[str, Any]:
        """局部替换：新措辞产生新版本，旧版本保持不变、继续留痕。

        已发放的旧版本不因替换而消失；若仍在流转，其更正与回执另行追踪。
        """
        state = self._state()
        variant = state.variants.get(variant_id)
        if variant is None:
            raise DomainError(f"变体不存在：{variant_id}")
        current = variant.current
        target_claim_rev = self._claim_at(
            state, current.claim_id, claim_revision or current.claim_revision
        )
        warnings, errors = self._check(
            statement=wording,
            scope=target_claim_rev["scope"],
            not_applicable=target_claim_rev["not_applicable"],
            limitations_disclosed=target_claim_rev["limitations_disclosed"],
            result_nature=target_claim_rev["result_nature"],
            evidence_grade=target_claim_rev["evidence_grade"],
            high_risk_note=target_claim_rev.get("high_risk_note", ""),
            study_id=target_claim_rev["study_id"],
            study_version=target_claim_rev["study_version"],
        )
        if errors:
            raise DomainError("替换措辞突破证据边界：" + "；".join(errors))
        new_revision = current.revision + 1
        payload = {
            "wording_revision": new_revision,
            "old_wording": current.wording,
            "wording": wording,
            "claim_id": current.claim_id,
            "claim_revision": target_claim_rev["revision"],
            "reason": reason,
            "system_warnings": warnings,
        }
        event = self._emit(
            variant_id, CONTENT_VARIANT, VARIANT_WORDING_REPLACED, occurred_at,
            f"{variant.department}局部替换材料为 r{new_revision}：{reason}", payload,
        )
        event["warnings"] = warnings
        return event

    # ---- 签署、冻结、发放 ----

    def mark_approval(
        self,
        *,
        variant_id: str,
        role: str,
        reviewer: str,
        decision: str,
        occurred_at: str,
        wording_revision: int | None = None,
    ) -> dict[str, Any]:
        if role not in REVIEW_ROLES:
            raise DomainError(f"未知签署角色：{role}")
        if decision not in ("confirmed", "rejected"):
            raise DomainError("decision 只能是 confirmed 或 rejected")
        state = self._state()
        wr = self._wording(state, variant_id, wording_revision)
        if wr.frozen_at:
            raise DomainError(f"{variant_id} r{wr.revision} 已冻结，签署不可改写")
        payload = {
            "wording_revision": wr.revision,
            "role": role,
            "reviewer": reviewer,
            "decision": decision,
        }
        return self._emit(
            variant_id, CONTENT_VARIANT, VARIANT_APPROVAL_MARKED, occurred_at,
            f"{reviewer} 以 {role} 身份{'确认' if decision == 'confirmed' else '驳回'} r{wr.revision}",
            payload,
        )

    def review_status(self, variant_id: str, wording_revision: int | None = None) -> dict[str, Any]:
        """系统门禁预检：返回缺失签署与边界问题，但不代替人工确认。"""
        state = self._state()
        wr = self._wording(state, variant_id, wording_revision)
        claim_rev = state.claims[wr.claim_id]["revisions"][wr.claim_revision]
        warnings, errors = self._check(
            statement=wr.wording,
            scope=claim_rev["scope"],
            not_applicable=claim_rev["not_applicable"],
            limitations_disclosed=claim_rev["limitations_disclosed"],
            result_nature=claim_rev["result_nature"],
            evidence_grade=claim_rev["evidence_grade"],
            high_risk_note=claim_rev.get("high_risk_note", ""),
            study_id=claim_rev["study_id"],
            study_version=claim_rev["study_version"],
        )
        required = [ROLE_METHODOLOGY, ROLE_CLINICIAN]
        if self._is_high_risk(state, claim_rev):
            required.append(ROLE_EXTRA_REVIEW)
        missing = []
        rejected = []
        for role in required:
            approval = wr.approvals.get(role)
            if approval is None:
                missing.append(role)
            elif approval["decision"] != "confirmed":
                rejected.append(role)
        return {
            "required_roles": required,
            "missing_confirmations": missing,
            "rejected_roles": rejected,
            "boundary_warnings": warnings,
            "boundary_errors": errors,
            "high_risk": self._is_high_risk(state, claim_rev),
            "frozen": wr.frozen_at is not None,
            "distributed": wr.distributed_at is not None,
        }

    def freeze_for_scenarios(
        self, *, variant_id: str, usage_scenarios: list[str], occurred_at: str
    ) -> dict[str, Any]:
        """双签（高风险三签）齐备且边界无硬伤后，冻结进指定使用场景。"""
        if not usage_scenarios:
            raise DomainError("必须指定使用场景")
        state = self._state()
        wr = self._wording(state, variant_id)
        if wr.frozen_at:
            raise DomainError(f"{variant_id} r{wr.revision} 已冻结")
        status = self.review_status(variant_id, wr.revision)
        if status["missing_confirmations"]:
            raise DomainError(
                "签署不完整，缺少：" + "、".join(status["missing_confirmations"])
            )
        if status["rejected_roles"]:
            raise DomainError("存在驳回签署：" + "、".join(status["rejected_roles"]))
        if status["boundary_errors"]:
            raise DomainError("边界违规未消除：" + "；".join(status["boundary_errors"]))
        return self._emit(
            variant_id, CONTENT_VARIANT, VARIANT_FROZEN, occurred_at,
            f"冻结 r{wr.revision}，限定使用场景：{'、'.join(usage_scenarios)}",
            {"wording_revision": wr.revision, "usage_scenarios": list(usage_scenarios)},
        )

    def distribute(
        self, *, variant_id: str, recipients: list[str], occurred_at: str
    ) -> dict[str, Any]:
        if not recipients:
            raise DomainError("发放名单不能为空")
        state = self._state()
        wr = self._wording(state, variant_id)
        if not wr.frozen_at:
            raise DomainError(f"{variant_id} r{wr.revision} 尚未冻结，不能发放")
        if wr.distributed_at:
            raise DomainError(f"{variant_id} r{wr.revision} 已发放")
        status = self.review_status(variant_id, wr.revision)
        if status["boundary_errors"]:
            raise DomainError(
                "证据状态已变化，发放前必须人工处置：" + "；".join(status["boundary_errors"])
            )
        return self._emit(
            variant_id, CONTENT_VARIANT, VARIANT_DISTRIBUTED, occurred_at,
            f"发放 r{wr.revision} 至 {len(recipients)} 个接收方",
            {
                "wording_revision": wr.revision,
                "usage_scenarios": list(wr.usage_scenarios),
                "recipients": list(recipients),
            },
        )

    # ---- 溯源与历史时点 ----

    def trace(self, variant_id: str, wording_revision: int | None = None) -> dict[str, Any]:
        """从一句公开表述一路追到研究限制、签署、使用范围与更正。"""
        state = self._state()
        variant = state.variants.get(variant_id)
        if variant is None:
            raise DomainError(f"变体不存在：{variant_id}")
        wr = variant.wording_revisions[wording_revision] if wording_revision else variant.current
        claim_rev = state.claims[wr.claim_id]["revisions"][wr.claim_revision]
        study_version = state.study_version(claim_rev["study_id"], claim_rev["study_version"])
        flag = state.latest_flag(claim_rev["study_id"], claim_rev["study_version"])
        notices = [
            n for n in state.notices.values()
            if n.variant_id == variant_id and wr.revision in n.affected_wording_revisions
        ]
        if wr.distributed_at:
            wr_status = "distributed"
        elif wr.frozen_at:
            wr_status = "frozen"
        elif wr.revision == variant.current_revision:
            wr_status = "draft"
        else:
            wr_status = "superseded"
        return {
            "statement": wr.wording,
            "department": variant.department,
            "audience": variant.audience,
            "wording_revision": wr.revision,
            "status": wr_status,
            "claim": {
                "claim_id": wr.claim_id,
                "claim_revision": wr.claim_revision,
                "statement": claim_rev["statement"],
                "evidence_scope": claim_rev["scope"],
                "not_applicable": claim_rev["not_applicable"],
                "limitations_disclosed": claim_rev["limitations_disclosed"],
                "result_nature": claim_rev["result_nature"],
                "evidence_grade": claim_rev["evidence_grade"],
                "high_risk_note": claim_rev.get("high_risk_note", ""),
                "system_warnings": claim_rev.get("system_warnings", []),
            },
            "study": {
                "study_id": claim_rev["study_id"],
                "study_version": claim_rev["study_version"],
                "population_groups": study_version["population_groups"],
                "age_range": study_version["age_range"],
                "treatment_windows": study_version["treatment_windows"],
                "endpoints": study_version["endpoints"],
                "exclusions": study_version["exclusions"],
                "limitations": study_version["limitations"],
                "statistical_conclusion": study_version["statistical_conclusion"],
                "result_nature": study_version["result_nature"],
                "evidence_grade": study_version["evidence_grade"],
                "high_risk_populations": study_version["high_risk_populations"],
            },
            "evidence_flag": flag,
            "sign_offs": [
                {
                    "role": role,
                    "reviewer": detail["reviewer"],
                    "decision": detail["decision"],
                    "at": detail["at"],
                    "event_id": detail["event_id"],
                }
                for role, detail in sorted(wr.approvals.items())
            ],
            "usage": {
                "scenarios": wr.usage_scenarios,
                "frozen_at": wr.frozen_at,
                "distributed_at": wr.distributed_at,
                "recipients": wr.recipients,
            },
            "corrections": [
                {
                    "notice_id": n.notice_id,
                    "change_type": n.change_type,
                    "risk_handling": n.risk_handling,
                    "issued_at": n.issued_at,
                    "requires_ack": n.requires_ack,
                    "acknowledgements": [
                        {"receiver": r, "received_at": a["received_at"], "at": a["at"]}
                        for r, a in sorted(n.acks.items())
                    ],
                    "pending_receivers": sorted(
                        set(wr.recipients) - set(n.acks)
                    ) if n.requires_ack else [],
                }
                for n in notices
            ],
        }

    def explain_at(self, variant_id: str, as_of: str) -> dict[str, Any]:
        """历史时点解释：回放至 as_of，看当时这句表述的依据与边界。"""
        state = self._state(as_of)
        if variant_id not in state.variants:
            raise DomainError(f"{as_of} 时点尚不存在变体：{variant_id}")
        variant = state.variants[variant_id]
        wr = variant.current
        claim_rev = state.claims[wr.claim_id]["revisions"][wr.claim_revision]
        study_version = state.study_version(claim_rev["study_id"], claim_rev["study_version"])
        flag = state.latest_flag(claim_rev["study_id"], claim_rev["study_version"])
        return {
            "as_of": as_of,
            "statement": wr.wording,
            "wording_revision": wr.revision,
            "claim_revision": wr.claim_revision,
            "evidence_scope": claim_rev["scope"],
            "not_applicable": claim_rev["not_applicable"],
            "limitations_disclosed": claim_rev["limitations_disclosed"],
            "study_statistical_conclusion": study_version["statistical_conclusion"],
            "study_exclusions": study_version["exclusions"],
            "study_limitations": study_version["limitations"],
            "evidence_flag_at_that_time": flag,
            "evidence_changed_after_distribution": (
                flag is not None
                and wr.distributed_at is not None
                and flag["flagged_at"] > wr.distributed_at
            ),
            "sign_offs_at_that_time": {role: d["decision"] for role, d in wr.approvals.items()},
            "frozen_at_that_time": wr.frozen_at is not None,
            "distributed_at_that_time": wr.distributed_at is not None,
            "usage_scenarios": wr.usage_scenarios,
        }

    # ---- 内部辅助 ----

    def _emit(
        self,
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        occurred_at: str,
        summary: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        version = self.store.next_version(aggregate_id)
        event = make_event(
            event_id=f"{aggregate_id}-{version}",
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            occurred_at=occurred_at,
            version=version,
            summary=summary,
            payload=payload,
        )
        self.store.append(event)
        return event

    def _check(self, **fields: Any) -> tuple[list[str], list[str]]:
        state = self._state()
        study_id = fields.pop("study_id")
        study_version = fields.pop("study_version")
        if study_id not in state.studies or study_version not in state.studies[study_id]["versions"]:
            raise DomainError(f"研究版本不存在：{study_id} v{study_version}")
        study_version_payload = state.study_version(study_id, study_version)
        flagged = state.latest_flag(study_id, study_version)
        return evaluate_scope(
            study_version=study_version_payload, flagged=flagged, **fields
        )

    @staticmethod
    def _claim_at(state: State, claim_id: str, revision: int | None) -> dict[str, Any]:
        if claim_id not in state.claims:
            raise DomainError(f"主张不存在：{claim_id}")
        claim = state.claims[claim_id]
        revision = revision or claim["current_revision"]
        if revision not in claim["revisions"]:
            raise DomainError(f"主张 {claim_id} 不存在修订 r{revision}")
        return claim["revisions"][revision]

    @staticmethod
    def _wording(state: State, variant_id: str, revision: int | None = None) -> WordingRevision:
        variant = state.variants.get(variant_id)
        if variant is None:
            raise DomainError(f"变体不存在：{variant_id}")
        revision = revision or variant.current_revision
        if revision not in variant.wording_revisions:
            raise DomainError(f"{variant_id} 不存在措辞 r{revision}")
        return variant.wording_revisions[revision]

    @staticmethod
    def _is_high_risk(state: State, claim_rev: dict[str, Any]) -> bool:
        groups = set(claim_rev["scope"].get("population_groups", []))
        sv = state.study_version(claim_rev["study_id"], claim_rev["study_version"])
        return bool(groups & set(sv.get("high_risk_populations", []))) or bool(
            claim_rev.get("high_risk_note")
        )


def _normalize_scope(scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "population_groups": list(scope.get("population_groups", [])),
        "age_range": list(scope.get("age_range")),
        "treatment_windows": [list(w) for w in scope.get("treatment_windows", [])],
        "endpoints": list(scope.get("endpoints", [])),
    }
