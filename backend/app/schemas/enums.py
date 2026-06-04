"""身份与项目相关的枚举定义。

枚举值（key）严格沿用 `docs/backend/01-数据模型DATA_MODEL.md` 的英文技术 key，
不做本地化翻译。仅在注释中用中文解释边界含义。
"""

from __future__ import annotations

from enum import Enum


class CompanyRole(str, Enum):
    """公司角色。boss / consulting_director / consultant 为业务角色；admin 为系统身份。"""

    boss = "boss"
    consulting_director = "consulting_director"
    consultant = "consultant"
    admin = "admin"


class ProjectRole(str, Enum):
    """项目内角色。coach（辅导老师）不负责任何 scope 下的资产确认。"""

    consultant = "consultant"
    project_manager = "project_manager"
    coach = "coach"


class UserStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class RoleStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class MemberStatus(str, Enum):
    active = "active"
    inactive = "inactive"


class ProjectStatus(str, Enum):
    active = "active"
    completed = "completed"
    archived = "archived"


# 业务用户判定集合：拥有其中任一 active 公司角色即视为业务用户。
# admin 不在其中——admin 仅是系统管理身份，不等于业务治理权限。
BUSINESS_COMPANY_ROLES: frozenset[str] = frozenset(
    {CompanyRole.boss.value, CompanyRole.consulting_director.value, CompanyRole.consultant.value}
)

# 可发现 L5 的公司角色集合：仅 boss 与 consulting_director。
# admin 不因系统身份获得 L5 发现能力。
L5_DISCOVERY_ROLES: frozenset[str] = frozenset(
    {CompanyRole.boss.value, CompanyRole.consulting_director.value}
)


# ============================================================
# 知识资产相关枚举（IMPLEMENT-02）
# 枚举值（key）沿用英文技术 key；以 String 存储 + 应用层枚举校验，
# 保持 PostgreSQL / SQLite 测试兼容。
# ============================================================


class KnowledgeScope(str, Enum):
    """知识库归属范围。

    personal：个人知识库，属于业务用户本人，默认私密、不参与他人检索。
    project：项目知识库，归属某个 project。
    company：公司知识库，跨项目复用的公司级资产。
    """

    personal = "personal"
    project = "project"
    company = "company"


class KnowledgeZone(str, Enum):
    """资产化状态标签。

    material（资料区）/ asset（资产区）是【同一个知识库内】的状态标签，
    不是两个物理知识库。material → asset 的确认人按 scope 不同而不同。
    """

    material = "material"
    asset = "asset"


class AssetType(str, Enum):
    methodology = "methodology"
    deliverable = "deliverable"
    case = "case"
    template = "template"
    insight = "insight"


class Visibility(str, Enum):
    """可见性。沿用 BE-02 与前端 mock 的取值：public / project_only / confidential。

    注意：IMPLEMENT-02 任务文本的枚举小节误写为 private/project/company，
    此处以正式蓝图 `docs/backend/01-数据模型DATA_MODEL.md` 与前端 mock 为准。
    """

    public = "public"
    project_only = "project_only"
    confidential = "confidential"


class ConfidentialityLevel(str, Enum):
    """保密级别，L1-L5 敏感度递增。L2 是内部一般资料，不强制脱敏。"""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class AiAccessLevel(str, Enum):
    """AI 调用级别 A1-A4。A4 资产不进入 Agent 原文上下文（与人工预览是不同边界）。"""

    A1 = "A1"
    A2 = "A2"
    A3 = "A3"
    A4 = "A4"


class AssetStatus(str, Enum):
    """资产宏观状态。archived / deprecated 不进入默认检索 / RAG / Agent 上下文。"""

    active = "active"
    needs_update = "needs_update"
    deprecated = "deprecated"
    archived = "archived"
    # deleted：误上传 / 撤下的软删除态（PBC-10B）。与 archived（生命周期归档）语义不同：
    # deleted 立即退出列表 / 检索 / 问答 / 预览 / Agent / 原文授权运行时，仅保留审计追溯。
    deleted = "deleted"


class VersionStatus(str, Enum):
    """版本状态。同一资产同一时间至多一个 active 版本；superseded/deprecated/archived 不参与默认检索。"""

    draft = "draft"
    active = "active"
    superseded = "superseded"
    deprecated = "deprecated"
    archived = "archived"


class ChunkStatus(str, Enum):
    """chunk 状态。invalid / superseded 默认不进入 RAG / Agent 上下文。"""

    active = "active"
    invalid = "invalid"
    superseded = "superseded"
    pending_review = "pending_review"


class ChunkType(str, Enum):
    paragraph = "paragraph"
    clause = "clause"
    table_row = "table_row"
    qa_pair = "qa_pair"
    policy_article = "policy_article"


class FileVariant(str, Enum):
    """文件变体。original 为原文；preview_render 等由保密等级/场景/授权决定是否实际保存。"""

    original = "original"
    desensitized = "desensitized"
    summary = "summary"
    preview_render = "preview_render"


class SummaryType(str, Enum):
    """摘要类型（IMPLEMENT-02 采用 summary_type + content 的窄表结构）。

    注意：BE-02 的 knowledge_asset_summaries 为宽表（one_liner/detailed/... 多列）；
    本阶段按任务要求落地为窄表（每种 summary_type 一行 content），差异留待 reviewer 确认。
    """

    one_liner = "one_liner"
    detailed = "detailed"
    key_points = "key_points"
    safe_summary = "safe_summary"
    redacted_summary = "redacted_summary"


class EvidenceType(str, Enum):
    internal_sharing = "internal_sharing"
    client_validation = "client_validation"


class EvidenceCategory(str, Enum):
    meeting_minutes = "meeting_minutes"
    wecom_record = "wecom_record"
    client_email = "client_email"
    acceptance_doc = "acceptance_doc"
    delivery_adoption = "delivery_adoption"


class AccessRequestStatus(str, Enum):
    """原文访问申请状态（PBC-06）。"""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class AccessGrantStatus(str, Enum):
    """原文访问授权状态（PBC-06）。expired 为读时惰性判定 + 落库。"""

    active = "active"
    revoked = "revoked"
    expired = "expired"


class AccessGrantType(str, Enum):
    """授权类型（PBC-06 本阶段仅 original_access）。"""

    original_access = "original_access"


class PersonalSubmissionType(str, Enum):
    """个人知识写动作的提交类型（PBC-05）。

    submit_to_project：个人知识提交进项目资料区（生成 personal_to_project 审核任务）。
    internal_sharing_candidate / client_validation_candidate：用户登记内部分享 / 客户验证
    证据线索作为候选；系统只登记，不证明分享/验证真实发生。
    """

    submit_to_project = "submit_to_project"
    internal_sharing_candidate = "internal_sharing_candidate"
    client_validation_candidate = "client_validation_candidate"


class PersonalSubmissionStatus(str, Enum):
    """个人知识提交记录状态（PBC-05）。"""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ReviewType(str, Enum):
    """审核类型。本阶段（IMPLEMENT-06）仅实现 material_to_asset；其余为前向占位。"""

    personal_to_project = "personal_to_project"
    material_to_asset = "material_to_asset"
    project_to_company = "project_to_company"
    lifecycle_change = "lifecycle_change"
    asset_update = "asset_update"
    chunk_invalidation = "chunk_invalidation"
    version_supersede = "version_supersede"


class ReviewTaskStatus(str, Enum):
    """审核任务状态（IMPLEMENT-06 最小闭环）。

    注意：BE-02 的 ReviewStatus 为 pending_consultant_confirm / pending_pm_review /
    pending_boss_review / approved / rejected；本阶段按任务要求采用
    pending_evidence / pending_reviewer / approved / rejected 的简化状态机，
    差异留待 reviewer 确认。
    """

    pending_evidence = "pending_evidence"
    pending_reviewer = "pending_reviewer"
    approved = "approved"
    rejected = "rejected"


class PreviewType(str, Enum):
    """预览类型。由保密等级 + 访问场景 + 授权共同决定，不固定绑定保密级别。"""

    full = "full"
    desensitized = "desensitized"
    summary_only = "summary_only"


class CredentialStatus(str, Enum):
    active = "active"
    expired = "expired"
    revoked = "revoked"


class AuditLogType(str, Enum):
    """审计日志大类（BE-09 §4）。"""

    operation = "operation"
    exception = "exception"
    login = "login"


class AlertSeverity(str, Enum):
    """严重级别（BE-09 §6 强审计标记）。"""

    critical = "critical"
    error = "error"
    warning = "warning"


class AuditAction(str, Enum):
    """本轮（IMPLEMENT-09）真实会写入的审计 action（点分命名，对齐 BE-09 §5）。

    action 在 DB 中是 varchar，不做原生 enum；此枚举用于应用层取值收敛与测试断言，
    不是穷举 BE-09 全集（未实现模块的 action 留待后续任务）。
    """

    # 入库
    ingest_task_created = "ingest.task_created"
    ingest_confirmed = "ingest.confirmed"
    # 入库失败（含抽取失败/空文件/WeKnora 写入失败），exception（对齐 BE-09 §5 `ingest.failed`）。
    ingest_failed = "ingest.failed"
    # 原文已推进 WeKnora 底座并回写 doc id（R1），operation。
    ingest_weknora_indexed = "ingest.weknora_indexed"
    # 外部 LLM 内容处理完成（R2；BE-09 §5.3 既有 "AI 提取完成"），operation。
    ingest_ai_extracted = "ingest.ai_extracted"
    # 审核
    review_evidence_bound = "review.evidence_bound"
    review_created = "review.created"
    review_approved = "review.approved"
    review_rejected = "review.rejected"
    asset_zone_changed = "asset.zone_changed"
    # 预览
    preview_requested = "preview.requested"
    preview_issued = "preview.issued"
    preview_denied = "preview.denied"
    preview_used = "preview.used"
    preview_l5_used = "preview.l5_used"
    l5_original_access = "l5_original_access"
    # 检索（R3 两阶段检索；BE-09 §5 检索读路径。新增 action，已回写说明见报告）
    knowledge_searched = "knowledge.searched"
    # Agent
    agent_called = "agent.called"
    agent_allowed = "agent.allowed"
    agent_denied = "agent.denied"
    agent_a4_original_denied = "agent.a4_original_denied"
    # 跨模块 admin 边界
    admin_business_denied = "admin.business_denied"
    # 审计异常处理（追加事件，不改原始事实）
    audit_exception_processed = "audit.exception_processed"
    # 生命周期治理（IMPLEMENT-10）
    lifecycle_archive_warning = "lifecycle.archive_warning"
    lifecycle_archive_candidate = "lifecycle.archive_candidate"
    lifecycle_archived = "lifecycle.archived"
    asset_status_changed = "asset.status_changed"
    lifecycle_reenable_requested = "lifecycle.reenable_requested"
    lifecycle_reenabled = "lifecycle.reenabled"
    # 知识资产受控删除 / 撤下（PBC-10B，软删除：asset_status=deleted，保留审计追溯）。
    knowledge_asset_deleted = "knowledge.asset_deleted"
    # 项目知识库（项目空间）创建（PBC-10B）。
    project_created = "project.created"
    config_alert_rule_updated = "config.alert_rule_updated"
    # Dify 接入注册变更（R4）：创建 / 启停 / 更新 capability·scope·token（config）。
    config_agent_registry_updated = "config.agent_registry_updated"
    # 人员治理（PBC-02）：公司角色 / 项目成员关系 upsert（config）。
    config_people_company_role_updated = "config.people_company_role_updated"
    config_people_project_membership_updated = "config.people_project_membership_updated"
    # 权限规则配置（PBC-03）：阈值 / 开关规则更新（config）。只记安全配置值，不含 secret。
    config_permission_rule_updated = "config.permission_rule_updated"
    # 项目设置（PBC-04）：项目设置更新 / 项目成员角色·状态更新（operation）。
    # 只记安全配置值与安全枚举/UUID；wecom_group_id 全文绝不入审计（只记 bound）。
    project_settings_updated = "project.settings_updated"
    project_member_updated = "project.member_updated"
    # 个人知识写动作（PBC-05）：本人资产确认 / 提交到项目 / 证据候选登记（operation）。
    # 只记安全枚举/UUID（zone/status/submission_type/evidence_type）；绝不含原文/摘要全文。
    review_personal_asset_confirmed = "review.personal_asset_confirmed"
    submission_created = "submission.created"
    evidence_validation_registered = "evidence.validation_registered"
    # 原文访问申请与授权（PBC-06）：申请 / 审批通过(建 grant) / 拒绝 / 撤销授权（operation）。
    # 只记安全枚举/UUID/status/expires_at；绝不含原文 / reason 中的敏感附件 / URL / token。
    access_original_requested = "access.original_requested"
    access_original_approved = "access.original_approved"
    access_original_rejected = "access.original_rejected"
    access_original_grant_revoked = "access.original_grant_revoked"
    # 跨项目复用升格推荐（R5 异步扫描，仅产生人审候选信号，不自动升格）。
    knowledge_upgrade_recommended = "knowledge.upgrade_recommended"
    # 企微微盘扫描（R6 Path A）：配置创建 / 变更 / 触发 / 完成 / 失败。
    wecom_scan_config_created = "wecom_scan.config_created"
    wecom_scan_config_updated = "wecom_scan.config_updated"
    wecom_scan_triggered = "wecom_scan.triggered"
    wecom_scan_completed = "wecom_scan.completed"
    wecom_scan_failed = "wecom_scan.failed"
    # 通知真实下发（R7）：发送成功 / 失败（安全元数据，不含正文/密钥）。
    notification_sent = "notification.sent"
    notification_failed = "notification.failed"
    # 会话 / 登录（IMPLEMENT-12）。真实 OAuth 接入前为本地会话最小闭环。
    login_success = "login.success"
    login_failed = "login.failed"
    login_logout = "login.logout"


# 强审计风险等级（写入 extra.risk_level，供告警系统按等级分发）。
class AuditRiskLevel(str, Enum):
    high = "high"
    critical = "critical"


class AgentProvider(str, Enum):
    """Agent 上层平台 provider 抽象（Gateway 内部的平台抽象标识，非敏感）。

    - internal_stub：IMPLEMENT-08 的关键词召回 + 确定性占位答案桩（R3 已取代，保留枚举
      仅为历史/兼容，不再用于新调用）。
    - weknora_llm：R3 起的真实链路——WeKnora 检索召回 + 外部 LLM 自拼答案。它仍是平台
      抽象标识，**不**暴露 Dify app_id / workflow_id / dataset_id、WeKnora kb/doc id、
      LLM api_key 等任何内部敏感标识。
    """

    internal_stub = "internal_stub"
    weknora_llm = "weknora_llm"


class AgentCapability(str, Enum):
    """Agent 能力边界。本阶段只实现 qa（知识问答）；其余为前向占位，

    在网关被 agent_capability_denied 拒绝（候选生成/总结等留待后续任务）。
    """

    qa = "qa"
    summarize = "summarize"
    recommend_upgrade = "recommend_upgrade"
    recommend_update = "recommend_update"
    extract_risk = "extract_risk"


class AgentCallStatus(str, Enum):
    """Agent 调用整体状态（allowed = 至少一条候选可用并已生成回答）。"""

    allowed = "allowed"
    denied = "denied"


class GatewayDecisionStatus(str, Enum):
    """网关调用级决策聚合状态。"""

    allowed = "allowed"
    denied = "denied"


class LifecycleEventType(str, Enum):
    """资产生命周期事件类型（IMPLEMENT-10，落 asset_lifecycle_events.event_type）。

    archive_warning / archive_candidate 仅是预警/候选，不改 asset_status；
    archived / reenabled 是经人工确认的状态变更事实；status_changed 为通用兜底。
    """

    archive_warning = "archive_warning"
    archive_candidate = "archive_candidate"
    archived = "archived"
    reenable_requested = "reenable_requested"
    reenabled = "reenabled"
    status_changed = "status_changed"


class LifecycleTriggeredBy(str, Enum):
    """生命周期事件触发方。system 为系统预警（本阶段不实现扫描）；user 为人工动作。"""

    system = "system"
    user = "user"


class NotificationChannel(str, Enum):
    """通知渠道。本阶段仅站内/控制台通知（in_app）落地；wecom/email 为后续集成渠道，
    仅作为 alert_rules 配置取值出现，不实现真实发送。"""

    in_app = "in_app"
    wecom = "wecom"
    email = "email"


class NotificationStatus(str, Enum):
    """通知发送状态。本阶段不真实发送，新建记录恒为 pending。"""

    pending = "pending"
    sent = "sent"
    failed = "failed"


class IngestSource(str, Enum):
    """入库来源。Path A（企微微盘）本阶段不真实实现。"""

    path_a_wecom = "path_a_wecom"
    path_b_upload = "path_b_upload"


class IngestStatus(str, Enum):
    """入库任务状态。

    注意：BE-02 的 IngestStatus 为 pending/processing/waiting_review/completed/failed；
    本阶段为表达"已生成 AI 建议、等待人工确认"额外引入 `pending_confirmation`，
    与 BE-02 的差异留待 reviewer 确认（waiting_review 仍保留给真正的审核流场景）。
    """

    pending = "pending"
    processing = "processing"
    pending_confirmation = "pending_confirmation"
    waiting_review = "waiting_review"
    completed = "completed"
    failed = "failed"
