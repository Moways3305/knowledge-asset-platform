"""知识资产核心 ORM 模型。

落地 6 张表：knowledge_assets / knowledge_asset_versions / knowledge_asset_chunks /
knowledge_asset_file_objects / knowledge_asset_summaries / knowledge_asset_tags。

本模块只定义数据层（模型 + 约束 + relationship）；API、权限判断、入库、审核、审计、
预览、Agent、检索与文件存储由各自的服务模块实现。枚举值以 String 存储，取值约束
由应用层 `app.schemas.enums` 保证。

字段命名说明：部分字段为精简/重命名（如 version_no / file_size /
file_hash / token_count / invalid_reason）；摘要采用窄表 summaries 存储。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.utils import utc_now


class KnowledgeAsset(Base):
    """知识资产聚合根。

    - scope=personal：个人知识库，归属业务用户本人，project_id 为空，默认私密、
      不参与他人检索。**owner 必须是业务用户**（拥有 active 公司角色
      boss/consulting_director/consultant）；仅 admin 身份不得作为 personal owner。
      该跨表业务约束不在 DB 层强制，由权限/服务层校验。
    - scope=project：项目知识库，project_id 标识所属项目。
    - scope=company：公司知识库（跨项目复用）。
    - zone=material/asset 是同一知识库内的状态标签，不是两个物理库。
    - archived / deprecated 资产不进入默认检索 / RAG / Agent 上下文（由检索/网关层落实）。
    """

    __tablename__ = "knowledge_assets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    zone: Mapped[str] = mapped_column(String(20), nullable=False, default="material")
    asset_type: Mapped[str] = mapped_column(String(30), nullable=False)

    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    maintainer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    source_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=True
    )
    # current_version_id 在逻辑上指向 knowledge_asset_versions.id，但为避免
    # assets <-> versions 的循环外键在 SQLite 迁移上的复杂度，这里只作为普通
    # UUID 列保存（不建 DB 级外键），其一致性由服务层维护。
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)

    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="project_only")
    confidentiality_level: Mapped[str] = mapped_column(String(2), nullable=False, default="L1")
    ai_access_level: Mapped[str] = mapped_column(String(2), nullable=False, default="A1")
    asset_status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # User-facing canonical filename. It never controls or reveals the storage key.
    canonical_name: Mapped[str | None] = mapped_column(String(500), nullable=True)

    lifecycle_route_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lifecycle_phase_key: Mapped[str | None] = mapped_column(String(50), nullable=True)

    last_called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archive_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 受控删除 / 撤下追溯。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    delete_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    # 容器关系（一对多）。删除资产时级联清理其版本/分块/文件/摘要/标签。
    versions: Mapped[list[KnowledgeAssetVersion]] = relationship(
        back_populates="asset",
        foreign_keys="KnowledgeAssetVersion.asset_id",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list[KnowledgeAssetChunk]] = relationship(
        back_populates="asset",
        foreign_keys="KnowledgeAssetChunk.asset_id",
        cascade="all, delete-orphan",
    )
    file_objects: Mapped[list[KnowledgeAssetFileObject]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    summaries: Mapped[list[KnowledgeAssetSummary]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    tags: Mapped[list[KnowledgeAssetTag]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )

    # 自引用：个人知识提交到项目时，新资产的 source_asset_id 指向原始个人资产。
    source_asset: Mapped[KnowledgeAsset | None] = relationship(
        remote_side="KnowledgeAsset.id", foreign_keys=[source_asset_id]
    )


class KnowledgeAssetVersion(Base):
    """知识资产版本。

    - 同一资产同一时间有且仅有一个 active 版本（业务约束，详见类内注释）。
    - 旧版本被替代后置 superseded，不物理删除，保留用于审计追溯。
    - superseded / deprecated / archived 版本不参与默认 RAG / Agent 检索。
    """

    __tablename__ = "knowledge_asset_versions"
    __table_args__ = (
        # 同一资产下版本号唯一。
        UniqueConstraint("asset_id", "version_no", name="uq_asset_version_no"),
        # 同一资产至多一个 active 版本：部分唯一索引（partial unique index）。
        # PostgreSQL 与 SQLite（>=3.8）均支持带 WHERE 的部分唯一索引，因此该约束
        # 在两种库上都生效；服务层仍应在激活版本时做防御性校验。
        Index(
            "uq_asset_one_active_version",
            "asset_id",
            unique=True,
            sqlite_where=text("version_status = 'active'"),
            postgresql_where=text("version_status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    version_no: Mapped[str] = mapped_column(String(20), nullable=False)
    version_status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # 内容指纹：哈希仅用于重复识别/变化检测，不能据此自动判定政策失效。
    file_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    supersedes_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_asset_versions.id"), nullable=True
    )
    # WeKnora 底座回写。三者均为 server-only 内部标识 / 状态：
    # weknora_kb_id / weknora_doc_id 视同 storage_ref，**绝不进任何响应 / 审计 / 日志**；
    # weknora_parse_status 是安全业务状态（pending/processing/completed/failed），可对外。
    # chunk 级标识由 WeKnora 维护，本表不加 weknora_chunk_id。
    weknora_kb_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    weknora_doc_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    weknora_parse_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 平台级索引状态。把「人工确认=资产落库」与「底座索引」解耦：confirm 成功
    # 即落库，底座建库/初始化/上传失败不回滚资产，而是在此标失败并可重试。
    # index_status: not_indexed | indexing | indexed | index_failed | skipped（安全业务状态，可对外）。
    # index_error_code 为安全错误码（如 weknora_upload_failed / weknora_init_failed）；
    # index_error_message 为安全中文文案——**绝不**写 kb_id / doc_id / api_key / 原始 payload。
    index_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_indexed", server_default="not_indexed"
    )
    index_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    index_error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Published naming facts captured at confirmation time. Historical versions
    # remain stable when later naming policies are published.
    naming_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    naming_rule_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Stable governed directory assignment for this formal version. Display paths
    # are derived from the published template and current project name.
    directory_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    directory_rule_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    directory_confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    asset: Mapped[KnowledgeAsset] = relationship(back_populates="versions", foreign_keys=[asset_id])
    chunks: Mapped[list[KnowledgeAssetChunk]] = relationship(
        back_populates="version",
        foreign_keys="KnowledgeAssetChunk.version_id",
        cascade="all, delete-orphan",
    )
    file_objects: Mapped[list[KnowledgeAssetFileObject]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    summaries: Mapped[list[KnowledgeAssetSummary]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )

    # 自引用：新版本 supersedes 旧版本。
    supersedes_version: Mapped[KnowledgeAssetVersion | None] = relationship(
        remote_side="KnowledgeAssetVersion.id", foreign_keys=[supersedes_version_id]
    )


class KnowledgeAssetChunk(Base):
    """知识资产分块（RAG / Agent 默认检索的最小单元）。

    - chunk_status=active 参与默认检索；pending_review 参与但带风险提示。
    - invalid / superseded 默认不进入 RAG / Agent 上下文。
    - 局部 chunk 失效不等于整个资产归档。
    - 业务约束：chunk_status=invalid 时应有 invalidated_by / invalidated_at，
      由测试与注释表达，不做 DB 级 check。
    """

    __tablename__ = "knowledge_asset_chunks"
    __table_args__ = (
        # 同一版本内 chunk 顺序位置唯一。
        UniqueConstraint("version_id", "chunk_index", name="uq_version_chunk_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_asset_versions.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    # 定位元数据（D1 v1.3 阶段3）：来源页码 / 章节，供「查看原文」与父文件定位。
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_section: Mapped[str | None] = mapped_column(String(200), nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    chunk_status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    invalid_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalidated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_asset_chunks.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    asset: Mapped[KnowledgeAsset] = relationship(back_populates="chunks", foreign_keys=[asset_id])
    version: Mapped[KnowledgeAssetVersion] = relationship(
        back_populates="chunks", foreign_keys=[version_id]
    )
    # 自引用：本 chunk 被新 chunk 替代。
    replaced_by_chunk: Mapped[KnowledgeAssetChunk | None] = relationship(
        remote_side="KnowledgeAssetChunk.id", foreign_keys=[replaced_by_chunk_id]
    )


class KnowledgeAssetFileObject(Base):
    """知识资产文件对象（支持 original / desensitized / summary / preview_render 变体）。

    安全要求：`storage_ref` 是服务端内部存储引用（如对象存储 key），
    **不得出现在任何 API / Pydantic 响应 schema 中**，不向前端明文返回。
    """

    __tablename__ = "knowledge_asset_file_objects"
    __table_args__ = (
        # 同一版本同一变体只有一个文件对象。
        UniqueConstraint(
            "asset_id", "version_id", "file_variant", name="uq_asset_version_file_variant"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_asset_versions.id"), nullable=False
    )
    file_variant: Mapped[str] = mapped_column(String(20), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # 内部存储引用——禁止进入任何前端响应。
    storage_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidentiality_level: Mapped[str] = mapped_column(String(2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    asset: Mapped[KnowledgeAsset] = relationship(back_populates="file_objects")
    version: Mapped[KnowledgeAssetVersion] = relationship(back_populates="file_objects")


class KnowledgeAssetSummary(Base):
    """知识资产摘要（窄表：每种 summary_type 一行 content）。

    L3 / L4 对外展示必须使用脱敏/安全摘要（redacted_one_liner + redacted_summary，
    兼容 safe_summary）；redacted_summary_pending 仅是回填待处理状态，不是展示内容；
    L5 不向总经理 / 咨询总监以外用户返回摘要或存在信息（由权限层落实）。
    """

    __tablename__ = "knowledge_asset_summaries"
    __table_args__ = (
        UniqueConstraint(
            "asset_id", "version_id", "summary_type", name="uq_asset_version_summary_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_asset_versions.id"), nullable=False
    )
    summary_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    asset: Mapped[KnowledgeAsset] = relationship(back_populates="summaries")
    version: Mapped[KnowledgeAssetVersion] = relationship(back_populates="summaries")


class KnowledgeAssetTag(Base):
    """知识资产标签。"""

    __tablename__ = "knowledge_asset_tags"
    __table_args__ = (UniqueConstraint("asset_id", "tag_name", name="uq_asset_tag_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    tag_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    asset: Mapped[KnowledgeAsset] = relationship(back_populates="tags")
