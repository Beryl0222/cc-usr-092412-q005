"""事件信封与只增日志。

事件一旦被接收，其标识、发生时间和版本不会被原地改写；
业务更正以后继事件表达。版本号按聚合递增，事件标识全局递增，
保证测试与联调结果可复现。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.validator import validate_event


class DomainError(ValueError):
    """违反领域规则时抛出。"""


_ENVELOPE_KEYS = (
    "event_id",
    "event_type",
    "aggregate_type",
    "aggregate_id",
    "occurred_at",
    "version",
    "summary",
)


def parse_time(value: str) -> datetime:
    """解析带时区偏移的 ISO 8601 时间；拒绝无时区时间，避免比较歧义。"""
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise DomainError(f"不是合法的 ISO 8601 时间：{value!r}") from exc
    if parsed.tzinfo is None:
        raise DomainError(f"时间必须携带时区偏移：{value!r}")
    return parsed


@dataclass(frozen=True)
class Event:
    """一条已被接收的领域事件。"""

    event_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    occurred_at: str
    version: int
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        record = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "occurred_at": self.occurred_at,
            "version": self.version,
            "summary": self.summary,
        }
        record.update(deepcopy(self.payload))
        return record


class EventLog:
    """只增事件日志；不提供任何改写或删除入口。"""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._versions: dict[str, int] = {}

    def append(
        self,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        occurred_at: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        parse_time(occurred_at)
        payload = deepcopy(payload) if payload else {}
        overlap = set(_ENVELOPE_KEYS) & payload.keys()
        if overlap:
            raise DomainError(f"payload 与信封字段重名：{sorted(overlap)}")
        version = self._versions.get(aggregate_id, 0) + 1
        event = Event(
            event_id=f"evt-{len(self._events) + 1:06d}",
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            occurred_at=occurred_at,
            version=version,
            summary=summary,
            payload=payload,
        )
        errors = validate_event(event.as_dict())
        if errors:
            raise DomainError("事件信封不合法：" + "；".join(errors))
        self._events.append(event)
        self._versions[aggregate_id] = version
        return event

    def all(self) -> list[Event]:
        return list(self._events)

    def up_to(self, as_of: str) -> list[Event]:
        """按发生时间截断日志，用于历史时点重放。"""
        cutoff = parse_time(as_of)
        return [event for event in self._events if parse_time(event.occurred_at) <= cutoff]
