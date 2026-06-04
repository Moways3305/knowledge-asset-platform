"""ORM 模型聚合导入。

集中导入所有模型，确保 `Base.metadata` 在 Alembic / 测试建表时完整。
当前已集中导入：身份与项目成员模型（IMPLEMENT-01）、知识资产核心模型（IMPLEMENT-02）。
"""

from app.models.agent import (
    AgentCall,
    AgentCallCitation,
    AgentGatewayDecision,
    AgentGatewayDecisionItem,
)
from app.models.agent_registry import AgentWhitelistRule
from app.models.audit import AuditEvent
from app.models.auth_session import UserSession
from app.models.identity import (
    Project,
    ProjectMember,
    User,
    UserCompanyRole,
)
from app.models.ingest import IngestTask, IngestTaskAiResult
from app.models.lifecycle import (
    AlertRule,
    AssetLifecycleEvent,
    NotificationRecord,
)
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.models.permission_rule import PermissionRule
from app.models.preview import PreviewCredential
from app.models.wecom import WecomScanConfig, WecomScanRecord
from app.models.weknora import WeknoraKbMapping
from app.models.review import (
    PersonalKnowledgeSubmission,
    ReviewTask,
    ReviewTaskEvidence,
    ValidationEvidence,
)
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetChunk,
    KnowledgeAssetFileObject,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)

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
    "ValidationEvidence",
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
    "UserSession",
    "WeknoraKbMapping",
    "WecomScanConfig",
    "WecomScanRecord",
]
