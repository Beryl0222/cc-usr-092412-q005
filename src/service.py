"""研究到临床释义的命令侧服务。

服务主线：
1. 登记研究：研究版本、人群、终点、限制条件、统计结论分别留痕；
2. 映射主张：每条面向患者或医务人员的主张声明证据范围与不适用情形；
3. 材料版本：科室起草措辞，系统体检提示遗漏与过度外推，
   方法学确认解释、临床确认边界（高风险人群内容另需复核）后，
   版本才能批准进入指定使用场景，发放即冻结；
4. 证据传播：降级、撤稿、随访更新只标记引用它的未冻结材料；
   已发放版本不被改写，追加风险处置并要求接收确认。
"""

from __future__ import annotations

from typing import Any

from src.checks import check_wording
from src.events import DomainError, Event, EventLog
from src.state import ClaimState, State, StudyState, VariantState, build_state

AUDIENCES = ("patient", "clinician")
POPULATION_RISKS = ("general", "high")
UPDATE_KINDS = ("downgrade", "retraction", "followup")
SIGNOFF_ROLES = ("methodology", "clinical", "high_risk_review")
# 各签署角色确认的内容：方法学确认解释，临床确认边界，高风险内容另需复核。
ROLE_ASPECTS = {
    "methodology": "解释",
    "clinical": "边界",
    "high_risk_review": "高风险复核",
}
DEFAULT_DISPOSITIONS = {
    "downgrade": "证据等级下调：相关表述降格为参考信息，使用前须复核",
    "retraction": "研究撤稿：立即停止相关表述的使用，并通知已接收对象",
    "followup": "随访更新：补充最新随访结论，原表述须对照复核",
}


class TranslationService:
    """更年期研究结论适用性释义服务。"""

    def __init__(self) -> None:
        self.log = EventLog()
        self.state = build_state(self.log.all())

    # ---- 内部工具 ----

    def _refresh(self) -> None:
        self.state = build_state(self.log.all())

    def _study(self, study_id: str) -> StudyState:
        study = self.state.studies.get(study_id)
        if study is None:
            raise DomainError(f"未知研究：{study_id}")
        return study

    def _claim(self, claim_id: str) -> ClaimState:
        claim = self.state.claims.get(claim_id)
        if claim is None:
            raise DomainError(f"未知主张：{claim_id}")
        return claim

    def _variant(self, variant_id: str) -> VariantState:
        variant = self.state.variants.get(variant_id)
        if variant is None:
            raise DomainError(f"未知材料版本：{variant_id}")
        return variant

    # ---- 1. 研究登记 ----

    def register_study(
        self,
        study_id: str,
        *,
        version_label: str,
        population: dict,
        endpoints: list[dict],
        limitations: list[str],
        statistics: list[dict],
        occurred_at: str,
        summary: str | None = None,
    ) -> Event:
        """登记一个研究版本；同一研究再次登记产生新版本，旧版本留痕。"""
        if not endpoints:
            raise DomainError("研究必须登记至少一个终点")
        if not limitations:
            raise DomainError("研究必须登记限制条件")
        names = [endpoint.get("name") for endpoint in endpoints]
        if any(not name for name in names):
            raise DomainError("每个终点都必须具有名称")
        if len(set(names)) != len(names):
            raise DomainError("终点名称重复")
        for stat in statistics:
            if stat.get("endpoint") not in names:
                raise DomainError(f"统计结论引用了未登记的终点：{stat.get('endpoint')}")
        study = self.state.studies.get(study_id)
        if study is not None and study.version(version_label) is not None:
            raise DomainError(f"研究 {study_id} 已存在版本 {version_label}")
        event = self.log.append(
            "STUDY_REGISTERED",
            "research_study",
            study_id,
            occurred_at,
            summary or f"登记研究 {study_id} 版本 {version_label}",
            {
                "study_version": version_label,
                "population": population,
                "endpoints": endpoints,
                "limitations": limitations,
                "statistics": statistics,
            },
        )
        self._refresh()
        return event

    # ---- 2. 主张映射 ----

    def map_claim(
        self,
        claim_id: str,
        *,
        study_id: str,
        audience: str,
        statement: str,
        evidence_scope: dict,
        non_applicable: list[str],
        occurred_at: str,
        study_version: str | None = None,
    ) -> Event:
        """登记一条面向患者或医务人员的主张及其证据范围与不适用情形。"""
        study = self._study(study_id)
        if claim_id in self.state.claims:
            raise DomainError(f"主张标识已存在：{claim_id}")
        if audience not in AUDIENCES:
            raise DomainError(f"受众必须是 {AUDIENCES} 之一：{audience}")
        if not statement:
            raise DomainError("主张表述不能为空")
        version_label = study_version or study.current.label
        version = study.version(version_label)
        if version is None:
            raise DomainError(f"研究 {study_id} 不存在版本 {version_label}")
        endpoints = (evidence_scope or {}).get("endpoints") or []
        if not endpoints:
            raise DomainError("主张必须声明所依赖的终点")
        known = {endpoint["name"] for endpoint in version.endpoints}
        unknown = [name for name in endpoints if name not in known]
        if unknown:
            raise DomainError(f"证据范围引用了该版本未登记的终点：{unknown}")
        if non_applicable is None:
            raise DomainError("必须声明不适用情形（无则声明为空列表）")
        event = self.log.append(
            "CLAIM_MAPPED",
            "public_claim",
            claim_id,
            occurred_at,
            f"映射主张 {claim_id}（{audience}）至研究 {study_id} 版本 {version_label}",
            {
                "study_id": study_id,
                "study_version": version_label,
                "audience": audience,
                "statement": statement,
                "evidence_scope": evidence_scope,
                "non_applicable": non_applicable,
            },
        )
        self._refresh()
        return event

    # ---- 3. 材料版本生命周期 ----

    def draft_material(
        self,
        variant_id: str,
        *,
        department: str,
        audience: str,
        items: dict[str, str],
        population_risk: str = "general",
        occurred_at: str,
    ) -> Event:
        """科室起草材料版本：同一主张可换措辞，但受众须与主张一致。"""
        if variant_id in self.state.variants:
            raise DomainError(f"材料版本标识已存在：{variant_id}")
        if audience not in AUDIENCES:
            raise DomainError(f"受众必须是 {AUDIENCES} 之一：{audience}")
        if population_risk not in POPULATION_RISKS:
            raise DomainError(f"人群风险必须是 {POPULATION_RISKS} 之一：{population_risk}")
        if not items:
            raise DomainError("材料至少引用一条主张")
        for claim_id, wording in items.items():
            claim = self._claim(claim_id)
            if claim.audience != audience:
                raise DomainError(
                    f"主张 {claim_id} 面向 {claim.audience}，不能进入 {audience} 材料"
                )
            if not wording:
                raise DomainError(f"主张 {claim_id} 的措辞不能为空")
        event = self.log.append(
            "MATERIAL_DRAFTED",
            "content_variant",
            variant_id,
            occurred_at,
            f"{department} 起草材料 {variant_id}（{len(items)} 条主张）",
            {
                "department": department,
                "audience": audience,
                "population_risk": population_risk,
                "items": items,
                "revision": 1,
            },
        )
        self._refresh()
        return event

    def run_checks(self, variant_id: str, *, occurred_at: str) -> list[dict]:
        """记录系统体检提示；提示是建议性的，不替代人工签署。"""
        variant = self._variant(variant_id)
        if variant.status not in ("draft", "needs_revision"):
            raise DomainError(f"当前状态 {variant.status} 不能记录体检提示")
        prompts: list[dict[str, Any]] = []
        for claim_id, wording in variant.items.items():
            claim = self._claim(claim_id)
            study = self._study(claim.study_id)
            version = study.version(claim.study_version)
            for prompt in check_wording(
                evidence_scope=claim.evidence_scope,
                non_applicable=claim.non_applicable,
                study_population=version.population,
                wording=wording,
            ):
                prompts.append({**prompt, "claim_id": claim_id})
        self.log.append(
            "CHECKS_RECORDED",
            "content_variant",
            variant_id,
            occurred_at,
            f"材料 {variant_id} 第 {variant.revision} 修订体检：{len(prompts)} 条提示",
            {"revision": variant.revision, "prompts": prompts},
        )
        self._refresh()
        return prompts

    def sign_off(
        self,
        variant_id: str,
        *,
        role: str,
        reviewer: str,
        note: str,
        occurred_at: str,
    ) -> Event:
        """记录一次签署：方法学确认解释，临床确认边界，高风险内容另需复核。"""
        variant = self._variant(variant_id)
        if role not in SIGNOFF_ROLES:
            raise DomainError(f"签署角色必须是 {SIGNOFF_ROLES} 之一：{role}")
        if variant.status != "draft":
            raise DomainError(f"当前状态 {variant.status} 不能签署；待修订材料请先修订")
        if role == "high_risk_review" and variant.population_risk != "high":
            raise DomainError("该材料不属于高风险人群内容，无需额外复核")
        if variant.checks_revision != variant.revision:
            raise DomainError("请先对当前修订记录体检提示，再签署")
        if role in variant.signoffs:
            raise DomainError(f"角色 {role} 已签署本修订；如需更改请先修订材料")
        event = self.log.append(
            "SIGNOFF_RECORDED",
            "content_variant",
            variant_id,
            occurred_at,
            f"{reviewer} 以 {role} 身份确认材料 {variant_id} 的{ROLE_ASPECTS[role]}",
            {
                "role": role,
                "aspect": ROLE_ASPECTS[role],
                "reviewer": reviewer,
                "note": note,
                "revision": variant.revision,
            },
        )
        self._refresh()
        return event

    def approve(self, variant_id: str, *, scenarios: list[str], occurred_at: str) -> Event:
        """双签署齐备后，材料版本才能进入指定使用场景。"""
        variant = self._variant(variant_id)
        if variant.status != "draft":
            raise DomainError(f"当前状态 {variant.status} 不能批准")
        if not scenarios:
            raise DomainError("必须指定使用场景")
        missing = [role for role in ("methodology", "clinical") if role not in variant.signoffs]
        if missing:
            raise DomainError(f"缺少签署：{missing}")
        if variant.population_risk == "high" and "high_risk_review" not in variant.signoffs:
            raise DomainError("高风险人群内容需要额外复核签署")
        event = self.log.append(
            "CONTENT_APPROVED",
            "content_variant",
            variant_id,
            occurred_at,
            f"材料 {variant_id} 第 {variant.revision} 修订获准进入场景 {scenarios}",
            {"revision": variant.revision, "scenarios": scenarios},
        )
        self._refresh()
        return event

    def distribute(
        self,
        variant_id: str,
        *,
        occurred_at: str,
        recipients: list[str] | None = None,
    ) -> Event:
        """发放即冻结：此后证据更新不再改写该版本，只追加风险处置。"""
        variant = self._variant(variant_id)
        if variant.status != "approved":
            raise DomainError(f"当前状态 {variant.status} 不能发放")
        recipients = recipients or [variant.department]
        event = self.log.append(
            "CONTENT_DISTRIBUTED",
            "content_variant",
            variant_id,
            occurred_at,
            f"材料 {variant_id} 第 {variant.revision} 修订发放至 {recipients}，版本冻结",
            {"revision": variant.revision, "recipients": recipients},
        )
        self._refresh()
        return event

    def revise_material(
        self,
        variant_id: str,
        *,
        changes: dict[str, str] | None = None,
        removals: list[str] | None = None,
        occurred_at: str,
    ) -> Event:
        """修订措辞或移除条目；修订后签署与体检失效，须重新进行。"""
        variant = self._variant(variant_id)
        if variant.status == "distributed":
            raise DomainError("已发放版本被冻结，不能修订；请通过证据更新发布风险处置")
        if variant.status == "approved":
            raise DomainError("已批准版本请先由证据更新标记为待修订，或退回草稿")
        changes = changes or {}
        removals = removals or []
        if not changes and not removals:
            raise DomainError("修订内容为空")
        for claim_id in list(changes) + list(removals):
            if claim_id not in variant.items:
                raise DomainError(f"材料未引用主张：{claim_id}")
        for claim_id, wording in changes.items():
            if not wording:
                raise DomainError(f"主张 {claim_id} 的措辞不能为空")
        if len(variant.items) - len(removals) < 1:
            raise DomainError("材料至少保留一条主张")
        event = self.log.append(
            "MATERIAL_REVISED",
            "content_variant",
            variant_id,
            occurred_at,
            f"材料 {variant_id} 进入第 {variant.revision + 1} 修订",
            {
                "revision": variant.revision + 1,
                "changed": changes,
                "removed": removals,
            },
        )
        self._refresh()
        return event

    # ---- 4. 证据更新与传播 ----

    def update_evidence(
        self,
        study_id: str,
        *,
        kind: str,
        endpoints: list[str] | str,
        rationale: str,
        occurred_at: str,
        disposition: str | None = None,
    ) -> dict[str, list[str]]:
        """登记证据降级、撤稿或随访更新，并传播到引用它的材料。

        未冻结材料标记为待修订；已发放版本不被改写，追加风险处置
        （更正通知）并要求接收方确认。
        """
        study = self._study(study_id)
        if kind not in UPDATE_KINDS:
            raise DomainError(f"证据更新类型必须是 {UPDATE_KINDS} 之一：{kind}")
        if not rationale:
            raise DomainError("证据更新必须说明理由")
        if endpoints != "all":
            if not endpoints:
                raise DomainError("必须指定受影响的终点，或用 all 表示全部")
            unknown = [name for name in endpoints if name not in study.endpoint_names()]
            if unknown:
                raise DomainError(f"研究未登记终点：{unknown}")
        self.log.append(
            "EVIDENCE_UPDATED",
            "research_study",
            study_id,
            occurred_at,
            f"研究 {study_id} 证据更新（{kind}）：{rationale}",
            {"kind": kind, "endpoints": endpoints, "rationale": rationale},
        )

        impacted_claims = {
            claim.claim_id
            for claim in self.state.claims.values()
            if claim.study_id == study_id
            and (
                endpoints == "all"
                or set(claim.evidence_scope["endpoints"]) & set(endpoints)
            )
        }
        flagged: list[str] = []
        notices: list[str] = []
        for variant in self.state.variants.values():
            claims_hit = sorted(impacted_claims & set(variant.items))
            if not claims_hit:
                continue
            if variant.status == "distributed":
                notice_id = f"notice-{variant.variant_id}-{len(variant.corrections) + 1:02d}"
                self.log.append(
                    "CORRECTION_PUBLISHED",
                    "correction_notice",
                    notice_id,
                    occurred_at,
                    f"对已发放材料 {variant.variant_id} 追加风险处置（{kind}）",
                    {
                        "variant_id": variant.variant_id,
                        "study_id": study_id,
                        "kind": kind,
                        "claims": claims_hit,
                        "disposition": disposition or DEFAULT_DISPOSITIONS[kind],
                        "required_recipients": list(variant.recipients),
                    },
                )
                notices.append(notice_id)
            else:
                self.log.append(
                    "MATERIAL_FLAGGED",
                    "content_variant",
                    variant.variant_id,
                    occurred_at,
                    f"证据{kind}影响材料 {variant.variant_id}，涉及主张 {claims_hit}",
                    {"study_id": study_id, "kind": kind, "claims": claims_hit},
                )
                flagged.append(variant.variant_id)
        self._refresh()
        return {"flagged": flagged, "notices": notices}

    def confirm_receipt(self, notice_id: str, *, department: str, occurred_at: str) -> Event:
        """接收方确认已收到风险处置。"""
        notice = self.state.notices.get(notice_id)
        if notice is None:
            raise DomainError(f"未知更正通知：{notice_id}")
        if department not in notice.required_recipients:
            raise DomainError(f"{department} 不在通知 {notice_id} 的接收范围")
        if department in notice.receipts:
            raise DomainError(f"{department} 已确认过通知 {notice_id}，请勿重复确认")
        event = self.log.append(
            "RECEIPT_CONFIRMED",
            "correction_notice",
            notice_id,
            occurred_at,
            f"{department} 确认接收通知 {notice_id}",
            {"department": department},
        )
        self._refresh()
        return event
