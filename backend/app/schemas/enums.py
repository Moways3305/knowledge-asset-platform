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
# 知识资产相关枚举
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
    """可见性：public / project_only / confidential。"""

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
    # deleted：误上传 / 撤下的软删除态。与 archived（生命周期归档）语义不同：
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
    """摘要类型。

    摘要以窄表存储：每种 summary_type 对应一行 content。
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
    """原文访问申请状态。"""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class AccessGrantStatus(str, Enum):
    """原文访问授权状态。expired 为读时惰性判定 + 落库。"""

    active = "active"
    revoked = "revoked"
    expired = "expired"


class AccessGrantType(str, Enum):
    """授权类型。"""

    original_access = "original_access"


class PersonalSubmissionType(str, Enum):
    """个人知识写动作的提交类型。

    submit_to_project：个人知识提交进项目资料区（生成 personal_to_project 审核任务）。
    internal_sharing_candidate / client_validation_candidate：用户登记内部分享 / 客户验证
    证据线索作为候选；系统只登记，不证明分享/验证真实发生。
    """

    submit_to_project = "submit_to_project"
    internal_sharing_candidate = "internal_sharing_candidate"
    client_validation_candidate = "client_validation_candidate"


class PersonalSubmissionStatus(str, Enum):
    """个人知识提交记录状态。"""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class ReviewType(str, Enum):
    """审核类型。当前仅实现 material_to_asset；其余为前向占位。"""

    personal_to_project = "personal_to_project"
    material_to_asset = "material_to_asset"
    project_to_company = "project_to_company"
    lifecycle_change = "lifecycle_change"
    asset_update = "asset_update"
    chunk_invalidation = "chunk_invalidation"
    version_supersede = "version_supersede"


class ReviewTaskStatus(str, Enum):
    """审核任务状态。

    采用 pending_evidence / pending_reviewer / approved / rejected 的状态机：
    先收集证据，再交由审核人裁决。
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
    """审计日志大类。"""

    operation = "operation"
    exception = "exception"
    login = "login"


class AlertSeverity(str, Enum):
    """严重级别（强审计标记）。"""

    critical = "critical"
    error = "error"
    warning = "warning"


class AuditAction(str, Enum):
    """会写入的审计 action（点分命名）。

    action 在 DB 中是 varchar，不做原生 enum；此枚举用于应用层取值收敛与测试断言，
    仅覆盖已实现模块的 action（未实现模块的 action 暂不在此枚举内）。
    """

    # 入库
    ingest_task_created = "ingest.task_created"
    ingest_confirmed = "ingest.confirmed"
    # 入库失败（含抽取失败/空文件/WeKnora 写入失败），exception。
    ingest_failed = "ingest.failed"
    # 原文已推进 WeKnora 底座并回写 doc id，operation。
    ingest_weknora_indexed = "ingest.weknora_indexed"
    # 资产已确认落库，但底座建库/初始化/上传索引失败，exception。
    # 资产保留 + 人工校正不丢，index_status=index_failed，可重试；区别于 ingest.failed
    # （后者=人工确认前整单失败）。extra 只放安全 error_code / stage，绝不含 kb/doc id。
    ingest_index_failed = "ingest.index_failed"
    # 外部 LLM 内容处理完成（AI 提取完成），operation。
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
    # 检索（两阶段检索读路径）。
    knowledge_searched = "knowledge.searched"
    # Agent
    agent_called = "agent.called"
    agent_allowed = "agent.allowed"
    agent_denied = "agent.denied"
    agent_a4_original_denied = "agent.a4_original_denied"
    agent_workbuddy_token_rotated = "agent.workbuddy_token_rotated"
    agent_workbuddy_token_revoked = "agent.workbuddy_token_revoked"
    # 跨模块 admin 边界
    admin_business_denied = "admin.business_denied"
    # 审计异常处理（追加事件，不改原始事实）
    audit_exception_processed = "audit.exception_processed"
    # 生命周期治理
    lifecycle_archive_warning = "lifecycle.archive_warning"
    lifecycle_archive_candidate = "lifecycle.archive_candidate"
    lifecycle_archived = "lifecycle.archived"
    asset_status_changed = "asset.status_changed"
    lifecycle_reenable_requested = "lifecycle.reenable_requested"
    lifecycle_reenabled = "lifecycle.reenabled"
    # 知识资产受控删除 / 撤下。
    knowledge_asset_deleted = "knowledge.asset_deleted"
    # 底座索引重试。requested=发起（operation）；retried=成功（operation）；
    # retry_failed=重试后底座仍失败（exception）。区别于 ingest.index_failed（confirm 阶段失败）。
    knowledge_index_retry_requested = "knowledge.index_retry_requested"
    knowledge_index_retried = "knowledge.index_retried"
    knowledge_index_retry_failed = "knowledge.index_retry_failed"
    # 批量索引运维：批量 retry-index / 显式 reparse 的发起与完成（operation）。
    # extra 只放安全 job_id / filters / counts / safe code / trace_id，绝不含标题 / 原文 / 内部 id。
    knowledge_index_batch_retry_requested = "knowledge.index_batch_retry_requested"
    knowledge_index_batch_retry_completed = "knowledge.index_batch_retry_completed"
    knowledge_index_reparse_requested = "knowledge.index_reparse_requested"
    knowledge_index_reparse_completed = "knowledge.index_reparse_completed"
    # WeKnora 模型配置中心。extra 只放安全字段（provider / type / 名称），
    # 绝不含 api_key / base_url / 真实 model_id / weknora_kb_id。
    weknora_model_created = "weknora.model_created"
    weknora_model_updated = "weknora.model_updated"
    weknora_model_deleted = "weknora.model_deleted"
    weknora_kb_config_updated = "weknora.kb_config_updated"
    # PBC-38 平台默认模型配置变更。extra 只放安全 model_ref / 名称，绝不含真实 model_id。
    weknora_default_models_updated = "weknora.default_models_updated"
    # 个人知识库管理（PBC-29）：显式创建 / 改名（仅安全元数据：可读名 + sync_ok，无 kb_id）。
    config_personal_kb_created = "config.personal_kb_created"
    config_personal_kb_updated = "config.personal_kb_updated"
    # 项目知识库（项目空间）创建。
    project_created = "project.created"
    config_alert_rule_updated = "config.alert_rule_updated"
    # Dify 接入注册变更：创建 / 启停 / 更新 capability·scope·token（config）。
    config_agent_registry_updated = "config.agent_registry_updated"
    # 人员治理：公司角色 / 项目成员关系 upsert（config）。
    config_people_company_role_updated = "config.people_company_role_updated"
    config_people_project_membership_updated = "config.people_project_membership_updated"
    # 权限规则配置：阈值 / 开关规则更新（config）。只记安全配置值，不含 secret。
    config_permission_rule_updated = "config.permission_rule_updated"
    # 项目设置：项目设置更新 / 项目成员角色·状态更新（operation）。
    # 只记安全配置值与安全枚举/UUID；wecom_group_id 全文绝不入审计（只记 bound）。
    project_settings_updated = "project.settings_updated"
    project_member_updated = "project.member_updated"
    # 个人知识写动作：本人资产确认 / 提交到项目 / 证据候选登记（operation）。
    # 只记安全枚举/UUID（zone/status/submission_type/evidence_type）；绝不含原文/摘要全文。
    review_personal_asset_confirmed = "review.personal_asset_confirmed"
    submission_created = "submission.created"
    evidence_validation_registered = "evidence.validation_registered"
    # 原文访问申请与授权：申请 / 审批通过(建 grant) / 拒绝 / 撤销授权（operation）。
    # 只记安全枚举/UUID/status/expires_at；绝不含原文 / reason 中的敏感附件 / URL / token。
    access_original_requested = "access.original_requested"
    access_original_approved = "access.original_approved"
    access_original_rejected = "access.original_rejected"
    access_original_grant_revoked = "access.original_grant_revoked"
    # 跨项目复用升格推荐（异步扫描，仅产生人审候选信号，不自动升格）。
    knowledge_upgrade_recommended = "knowledge.upgrade_recommended"
    # 企微微盘扫描（Path A）：配置创建 / 变更 / 触发 / 完成 / 失败。
    wecom_scan_config_created = "wecom_scan.config_created"
    wecom_scan_config_updated = "wecom_scan.config_updated"
    wecom_scan_triggered = "wecom_scan.triggered"
    wecom_scan_completed = "wecom_scan.completed"
    wecom_scan_failed = "wecom_scan.failed"
    # 通知真实下发：发送成功 / 失败（安全元数据，不含正文/密钥）。
    notification_sent = "notification.sent"
    notification_failed = "notification.failed"
    # 运维告警：信号超阈值触发（仅安全元数据：信号/计数/阈值/时间窗/安全 error_code 聚合）。
    ops_alert_triggered = "ops.alert_triggered"
    # 会话 / 登录。真实 OAuth 接入前为本地会话最小闭环。
    login_success = "login.success"
    login_failed = "login.failed"
    login_logout = "login.logout"
    # 企微 OAuth 专用登录事件。extra 仅含 operation / created / login_method /
    # company_role / reason_code 等安全枚举，不含 code/token/state/raw userid/ip。
    auth_wecom_user_created = "auth.wecom_user_created"
    auth_wecom_login_success = "auth.wecom_login_success"
    auth_wecom_login_denied = "auth.wecom_login_denied"
    # 登录失败风控。锁定 / 限流均为系统事件（actor=None），extra 只含不可逆 hash
    # 前缀 / reason_code / 计数 / 窗口，绝不含 raw email / password / token / cookie / 原始 IP。
    login_locked = "login.locked"
    login_rate_limited = "login.rate_limited"
    # 登录风控运维：admin 手动解除 identifier 短时锁定。extra 只含 target_user_id /
    # identifier_hash_prefix / reset_attempt_id / 安全数字，绝不含 raw email / IP / token。
    auth_lockout_unlocked = "auth.lockout_unlocked"
    # 会话撤销：账号停用 / 改密 / admin 强制下线时撤销平台会话。extra 只含
    # target_user_id / revoked_count / trigger / reason / preserved_current_session，绝不含
    # token / token_hash / cookie / OAuth state / 密码 / 原始 IP。
    auth_sessions_revoked = "auth.sessions_revoked"
    # 用户启停：admin 改 users.status（active ↔ inactive）。停用联动撤销会话。
    config_people_status_updated = "config.people_status_updated"
    # 企微身份生命周期同步：成员失效时停用平台用户并撤销会话。extra 只含
    # target_user_id / trigger / wecom_status(归一 code) / previous_status / new_status /
    # sessions_revoked / dry_run / 批量计数，绝不含 access_token / app_secret / code / state /
    # raw wecom_user_id / 通讯录档案字段 / 上游 errmsg。
    identity_wecom_user_synced = "identity.wecom_user_synced"
    identity_user_deactivated_by_wecom_sync = "identity.user_deactivated_by_wecom_sync"
    # 管理员设置 / 重置用户密码。extra 只放安全元数据，绝不含 password/hash/salt。
    auth_password_set = "auth.password_set"


# 强审计风险等级（写入 extra.risk_level，供告警系统按等级分发）。
class AuditRiskLevel(str, Enum):
    high = "high"
    critical = "critical"


class AgentProvider(str, Enum):
    """Agent 上层平台 provider 抽象（Gateway 内部的平台抽象标识，非敏感）。

    - internal_stub：早期关键词召回 + 确定性占位答案桩（已被 weknora_llm 取代，保留枚举
      仅为历史/兼容，不再用于新调用）。
    - weknora_llm：真实链路——WeKnora 检索召回 + 外部 LLM 自拼答案。它仍是平台
      抽象标识，**不**暴露 Dify app_id / workflow_id / dataset_id、WeKnora kb/doc id、
      LLM api_key 等任何内部敏感标识。
    """

    internal_stub = "internal_stub"
    weknora_llm = "weknora_llm"


class AgentCapability(str, Enum):
    """Agent 能力边界。当前只实现 qa（知识问答）；其余为前向占位，

    在网关被 agent_capability_denied 拒绝（候选生成/总结等暂未实现）。
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
    """资产生命周期事件类型。

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
    """生命周期事件触发方。system 为系统预警/扫描；user 为人工动作。"""

    system = "system"
    user = "user"


class NotificationChannel(str, Enum):
    """通知渠道。in_app（站内/控制台）默认落地；wecom 经部署开关启用真实下发；
    email 为占位渠道，未实现真实发送。"""

    in_app = "in_app"
    wecom = "wecom"
    email = "email"


class NotificationStatus(str, Enum):
    """通知发送状态。新建记录为 pending，由通知下发流程更新为 sent / failed。"""

    pending = "pending"
    sent = "sent"
    failed = "failed"


class IngestSource(str, Enum):
    """入库来源。path_a_wecom = 企业微信微盘扫描；path_b_upload = 本地上传。"""

    path_a_wecom = "path_a_wecom"
    path_b_upload = "path_b_upload"


class IngestStatus(str, Enum):
    """入库任务状态。

    `pending_confirmation` 表示"已生成 AI 建议、等待人工确认"；
    waiting_review 保留给审核流场景。
    """

    pending = "pending"
    processing = "processing"
    pending_confirmation = "pending_confirmation"
    waiting_review = "waiting_review"
    completed = "completed"
    failed = "failed"
