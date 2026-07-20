"""公共错误工具。

集中定义通用 HTTP 拒绝响应构造函数，避免在多个模块重复实现 `_denied`。
"""

from __future__ import annotations

from fastapi import HTTPException


def denied(status_code: int, reason: str, message: str) -> HTTPException:
    """构造统一的拒绝响应 HTTPException。

    Args:
        status_code: HTTP 状态码（如 401 / 403 / 404 / 422 / 502）。
        reason: 机器可读的拒绝原因 code（进响应 detail.denied_reason，前端据此分支）。
        message: 面向用户的中文提示文案（进响应 detail.message）。

    Returns:
        HTTPException，可直接 `raise`。
    """
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )
