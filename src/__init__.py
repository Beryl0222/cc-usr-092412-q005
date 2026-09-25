"""更年期研究释义台。

事件契约见 :mod:`src.events`，业务流程入口为
:class:`src.service.TranslationService`。
"""

from .errors import DomainError
from .events import (
    FLAG_DOWNGRADE,
    FLAG_FOLLOWUP_UPDATE,
    FLAG_RETRACTION,
    ROLE_CLINICIAN,
    ROLE_EXTRA_REVIEW,
    ROLE_METHODOLOGY,
)
from .service import TranslationService
from .store import EventStore

__all__ = [
    "TranslationService",
    "EventStore",
    "DomainError",
    "FLAG_DOWNGRADE",
    "FLAG_RETRACTION",
    "FLAG_FOLLOWUP_UPDATE",
    "ROLE_METHODOLOGY",
    "ROLE_CLINICIAN",
    "ROLE_EXTRA_REVIEW",
]
