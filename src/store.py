"""只追加的事件存储。

事件一经接收，event_id、occurred_at 与 version 不再原地改写；更正一律
产生后继事件。存储负责：信封校验、event_id 唯一、聚合内 version 严格
递增、事件类型与聚合类型匹配。回放顺序即追加顺序，occurred_at 相同
时保持稳定，保证历史时点查询可重复。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .events import validate_envelope
from .errors import DomainError

_AGGREGATE_EVENT_TYPES: dict[str, frozenset[str]] = {}


def register_events(aggregate_type: str, event_types: Iterable[str]) -> None:
    _AGGREGATE_EVENT_TYPES[aggregate_type] = frozenset(event_types)


# 默认注册（避免循环导入，此处直接内联事件名）
register_events(
    "research_study",
    ("STUDY_REGISTERED", "STUDY_VERSION_RECORDED", "EVIDENCE_FLAGGED"),
)
register_events("public_claim", ("CLAIM_MAPPED", "CLAIM_REVISED"))
register_events(
    "content_variant",
    (
        "VARIANT_DRAFTED",
        "VARIANT_WORDING_REPLACED",
        "VARIANT_APPROVAL_MARKED",
        "VARIANT_FROZEN",
        "VARIANT_DISTRIBUTED",
    ),
)
register_events(
    "correction_notice",
    ("CORRECTION_ISSUED", "CORRECTION_ACKNOWLEDGED"),
)


class EventStore:
    """内存事件流；可从已有事件列表初始化（用于复放与持久化对接）。"""

    def __init__(self, initial: list[dict[str, Any]] | None = None) -> None:
        self._events: list[dict[str, Any]] = []
        self._ids: set[str] = set()
        self._aggregate_versions: dict[str, int] = {}
        for event in initial or []:
            self._append_checked(event)

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        self._append_checked(event)
        return event

    def _append_checked(self, event: dict[str, Any]) -> None:
        errors = validate_envelope(event)
        if errors:
            raise DomainError("；".join(errors))
        event_id = event["event_id"]
        if event_id in self._ids:
            raise DomainError(f"event_id 重复：{event_id}")
        aggregate_id = event["aggregate_id"]
        aggregate_type = event["aggregate_type"]
        allowed = _AGGREGATE_EVENT_TYPES.get(aggregate_type, frozenset())
        if event["event_type"] not in allowed:
            raise DomainError(
                f"{event['event_type']} 不属于聚合 {aggregate_type}（{aggregate_id}）"
            )
        expected = self._aggregate_versions.get(aggregate_id, 0) + 1
        if event["version"] != expected:
            raise DomainError(
                f"聚合 {aggregate_id} 版本应为 {expected}，收到 {event['version']}"
            )
        self._aggregate_versions[aggregate_id] = expected
        self._ids.add(event_id)
        self._events.append(event)

    def stream(
        self,
        *,
        aggregate_id: str | None = None,
        occurred_by: str | None = None,
    ) -> list[dict[str, Any]]:
        """按追加顺序读取；可限定聚合与历史时点（occurred_at <= 时点）。"""
        result = self._events
        if aggregate_id is not None:
            result = [e for e in result if e["aggregate_id"] == aggregate_id]
        if occurred_by is not None:
            result = [e for e in result if e["occurred_at"] <= occurred_by]
        return list(result)

    def next_version(self, aggregate_id: str) -> int:
        return self._aggregate_versions.get(aggregate_id, 0) + 1
