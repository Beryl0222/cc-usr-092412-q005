"""领域错误类型。

所有违反证据边界、签署门禁或事件一致性的情况都抛出
:class:`DomainError`，便于调用方与测试统一捕获。
"""


class DomainError(Exception):
    """业务规则被违反（区别于信封层面的格式错误）。"""
