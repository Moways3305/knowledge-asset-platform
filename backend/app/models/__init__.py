"""ORM 模型聚合导入。

集中导入所有模型，确保 `Base.metadata` 在 Alembic / 测试建表时完整。
当前已集中导入：身份与项目成员模型、知识资产核心模型。
"""

from app.models.agent import (
    AgentCall,
    AgentCallCitation,
    AgentGatewayDecision,
    AgentGatewayDecisionItem,
)
from app.models.agent_registry import AgentWhitelistRule
from app.models.audit import AuditEvent
from app.models.auth_security import AuthLoginAttempt
from app.models.auth_session import UserSession
from app.models.generation_model import ContentGenerationModel, ContentGenerationSettings
from app.models.identity import (
    Project,
    ProjectMember,
    User,
    UserCompanyRole,
)
from app.models.indexing_job import IndexingOperationJob, IndexingOpsSnapshot, OpsRuntimeHeartbeat
from app.models.ingest import (
    IngestTask,
    IngestTaskAiResult,
    IngestTaskDerivative,
    UploadSession,
    UploadSessionItem,
)
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetChunk,
    KnowledgeAssetFileObject,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.models.lifecycle import (
    AlertRule,
    AssetLifecycleEvent,
    NotificationRecord,
)
from app.models.llm_usage import LLMUsageEvent
from app.models.naming import NamingRuleRevision
from app.models.notification import BusinessNotification
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.models.permission_rule import PermissionRule
from app.models.preview import PreviewCredential
from app.models.review import (
    CompanyAssetReviewDecision,
    PersonalKnowledgeSubmission,
    ReviewTask,
    ReviewTaskEvidence,
    ValidationEvidence,
)
from app.models.wecom import WecomProjectScanSpace, WecomScanConfig, WecomScanRecord
from app.models.weknora import WeknoraKbMapping
from app.models.weknora_defaults import WeknoraDefaultModels

__all__ = [
    "User",
    "UserCompanyRole",
    "Project",
    "ProjectMember",
    "KnowledgeAsset",
    "KnowledgeAssetVersion",
    "KnowledgeAssetChunk",
    "KnowledgeAssetFileObject",
    "KnowledgeAssetSummary",
    "KnowledgeAssetTag",
    "IngestTask",
    "IngestTaskAiResult",
    "IngestTaskDerivative",
    "UploadSession",
    "UploadSessionItem",
    "IndexingOperationJob",
    "IndexingOpsSnapshot",
    "OpsRuntimeHeartbeat",
    "ValidationEvidence",
    "CompanyAssetReviewDecision",
    "ReviewTask",
    "ReviewTaskEvidence",
    "PersonalKnowledgeSubmission",
    "PreviewCredential",
    "AgentCall",
    "AgentGatewayDecision",
    "AgentGatewayDecisionItem",
    "AgentCallCitation",
    "AgentWhitelistRule",
    "PermissionRule",
    "OriginalAccessRequest",
    "AccessGrant",
    "AuditEvent",
    "AssetLifecycleEvent",
    "AlertRule",
    "NotificationRecord",
    "LLMUsageEvent",
    "NamingRuleRevision",
    "BusinessNotification",
    "UserSession",
    "AuthLoginAttempt",
    "ContentGenerationModel",
    "ContentGenerationSettings",
    "WeknoraKbMapping",
    "WeknoraDefaultModels",
    "WecomScanConfig",
    "WecomScanRecord",
    "WecomProjectScanSpace",
]
