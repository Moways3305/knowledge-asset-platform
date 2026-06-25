"""个人知识库管理 API 的请求 / 响应 schema（PBC-29）。

只暴露**安全元数据**：用户可读名称、状态枚举、资产计数、index 状态分布、对前端不可逆的
embedding model_ref（PBC-11A 安全映射）、时间戳。绝不返回 WeKnora 内部库标识 /
raw 模型 id / api_key / 底座分块 / 底座存储配置 / 任何底座原始 payload。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class PersonalKbCreateRequest(BaseModel):
    """显式创建个人知识库。display_name 可选（缺省用「我的知识库」）。

    PBC-38：可选模型选择（model_ref，对底座 id 不可逆，绝不接收真实 model_id）。
    缺省走平台默认；显式选择在首建个人 KB 时生效。
    """

    display_name: str | None = Field(default=None, max_length=100)
    embedding_model_ref: str | None = Field(default=None)
    rerank_model_ref: str | None = Field(default=None)


class PersonalKbRenameRequest(BaseModel):
    """个人知识库改名。display_name 必填，前后空白会被 trim，trim 后不得为空。"""

    display_name: str = Field(min_length=1, max_length=100)

    @field_validator("display_name")
    @classmethod
    def _strip_non_empty(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("display_name 不能为空白")
        return s


class PersonalKbOut(BaseModel):
    """个人知识库安全状态视图。

    无映射时仅 `exists=False`。有映射时给出可读名 / 状态 / 计数 / index 分布 /
    安全 embedding model_ref。`weknora_sync_failed` 仅改名场景有意义（底座同步失败时
    平台侧已保存、标记待重试）。
    """

    exists: bool
    display_name: str | None = None
    status: str | None = None  # active / init_failed
    knowledge_count: int = 0
    index_distribution: dict[str, int] = Field(default_factory=dict)
    embedding_model_ref: str | None = None
    created_at: datetime | None = None
    weknora_sync_failed: bool = False
