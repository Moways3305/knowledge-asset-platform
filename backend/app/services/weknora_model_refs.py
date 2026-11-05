"""Stable, one-way references shared by runtime model selection and onboarding."""

import hashlib
import hmac

from fastapi import HTTPException

from app.core.config import get_settings


def model_ref(model_id: str) -> str:
    """WeKnora server-only model_id → 对前端不可逆的 model_ref（单向 HMAC-SHA256）。

    防御：空 / "None" 的 id 直接拒绝，避免生成 HMAC("None") 这类「假成功」ref。
    """
    mid = str(model_id or "").strip()
    if not mid or mid == "None":
        raise HTTPException(
            502,
            detail={
                "denied_reason": "weknora_model_ref_invalid",
                "message": "底座返回的模型标识无效",
            },
        )
    key = (get_settings().weknora_model_ref_secret or "kap-weknora-model-ref-v1").encode("utf-8")
    return hmac.new(key, mid.encode("utf-8"), hashlib.sha256).hexdigest()
