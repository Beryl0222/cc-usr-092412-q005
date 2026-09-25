"""校验领域事件信封的基础字段、枚举取值与时间格式。

枚举取值直接读取 contracts/domain.schema.json，保证校验与契约同源。
"""

import json
from datetime import datetime
from pathlib import Path

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "contracts" / "domain.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

REQUIRED = tuple(_SCHEMA["required"])
EVENT_TYPES = tuple(_SCHEMA["properties"]["event_type"]["enum"])
AGGREGATE_TYPES = tuple(_SCHEMA["properties"]["aggregate_type"]["enum"])


def validate_event(record: dict) -> list[str]:
    errors = [f"缺少字段：{name}" for name in REQUIRED if name not in record]
    if "version" in record and (
        not isinstance(record["version"], int)
        or isinstance(record["version"], bool)
        or record["version"] < 1
    ):
        errors.append("version 必须是正整数")
    if "event_type" in record and record["event_type"] not in EVENT_TYPES:
        errors.append(f"event_type 不在约定范围：{record['event_type']}")
    if "aggregate_type" in record and record["aggregate_type"] not in AGGREGATE_TYPES:
        errors.append(f"aggregate_type 不在约定范围：{record['aggregate_type']}")
    if "occurred_at" in record:
        try:
            parsed = datetime.fromisoformat(str(record["occurred_at"]))
            if parsed.tzinfo is None:
                errors.append("occurred_at 必须携带时区偏移")
        except ValueError:
            errors.append("occurred_at 不是合法的 ISO 8601 时间")
    return errors
