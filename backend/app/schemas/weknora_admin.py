"""模型配置中心 API 的 schema。

安全红线：**绝不**承载 WeKnora `api_key` / `base_url` 真实值 / server-only `model_id` /
`weknora_kb_id` / `weknora_doc_id` / 内部存储引用 / 原始 WeKnora payload。前端用对底座 id
不可逆的 `model_ref` 选择模型；写操作的 secret（访问密钥 / API 地址）只单向上送、后端代理写
WeKnora，绝不回显。
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel

# 前端模型类型别名（与 WeKnora ModelType 双向映射，对外只用别名）。
ModelTypeAlias = str  # chat | embedding | rerank | vllm | asr


class ProviderOut(BaseModel):
    value: str
    label: str
    description: str | None = None
    model_types: list[str] = []


class ProviderListResponse(BaseModel):
    items: list[ProviderOut]


class ModelOut(BaseModel):
    """安全模型视图：无 server-only id / 无 key / 无 base_url。"""

    model_ref: str
    name: str
    type: str  # 前端别名
    source: str | None = None
    provider: str | None = None
    enabled: bool = True
    is_builtin: bool = False
    description: str | None = None


class ModelListResponse(BaseModel):
    items: list[ModelOut]


class ModelMutateRequest(BaseModel):
    """创建 / 更新模型请求。base_url / api_key 仅上送、由后端代理写 WeKnora，绝不回显。"""

    name: str
    type: str  # 前端别名 chat|embedding|rerank|vllm|asr
    source: str = "remote"  # remote | local
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    description: str | None = None
    dimension: int | None = None  # 仅 embedding 用


class ModelMutateResponse(BaseModel):
    """变更结果：仅安全状态 + 新 model_ref，绝不回显 secret / 真实 id。"""

    model_ref: str
    name: str
    type: str
    provider: str | None = None
    status: str = "ok"


class ModelDeleteResponse(BaseModel):
    deleted: bool = True


class ModelCheckRequest(BaseModel):
    """连通性测试：api_url / api_key 仅上送，结果只回 success + 安全文案。"""

    model_type: str  # chat|embedding|rerank|vllm
    api_url: str
    api_key: str
    model: str


class ModelCheckResponse(BaseModel):
    success: bool
    message: str


class ModelSlotOut(BaseModel):
    """KB 初始化配置中某一槽位（chat/embedding/rerank/multimodal）的安全模型定位。"""

    model_ref: str | None = None
    name: str | None = None
    type: str | None = None
    provider: str | None = None


class KbConfigOut(BaseModel):
    """KB 初始化配置安全视图：用平台 mapping_id 定位，绝不含 weknora_kb_id。"""

    mapping_id: uuid.UUID
    scope: str
    kb_name: str
    display_name: str | None = None  # 用户可读名称（PBC-29；personal KB 必有）
    project_name: str | None = None
    owner_name: str | None = None
    mapping_status: str
    chat: ModelSlotOut | None = None
    embedding: ModelSlotOut | None = None
    rerank: ModelSlotOut | None = None
    multimodal: ModelSlotOut | None = None
    config_error: str | None = None  # 读取底座配置失败时的安全提示（不含内部标识）


class KbConfigListResponse(BaseModel):
    items: list[KbConfigOut]


class KbInitUpdateRequest(BaseModel):
    """更新 KB 初始化配置：前端提交 model_ref（对底座 id 不可逆），后端解析为 server-only id。"""

    chat_model_ref: str | None = None
    embedding_model_ref: str | None = None
    rerank_model_ref: str | None = None
    multimodal_ref: str | None = None


class KbInitUpdateResponse(BaseModel):
    mapping_id: uuid.UUID
    mapping_status: str
    updated: bool = True
