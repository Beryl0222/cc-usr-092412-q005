"""信封层校验（保留基线入口，规则以 :mod:`src.events` 为准）。"""

from .events import validate_envelope as validate_event

REQUIRED = (
    "event_id",
    "event_type",
    "aggregate_type",
    "aggregate_id",
    "occurred_at",
    "version",
    "summary",
)

__all__ = ["validate_event", "REQUIRED"]
