import { useCallback, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Archive,
  ArrowRight,
  ArrowUpRight,
  BriefcaseBusiness,
  Clock3,
  DatabaseZap,
  FileWarning,
  FolderKanban,
  LibraryBig,
  ListChecks,
  CircleCheckBig,
  Gauge,
  TriangleAlert,
  Plus,
  RefreshCw,
  SearchX,
  ShieldAlert,
  UploadCloud,
  type LucideIcon,
} from "lucide-react";
import { fetchPeople } from "../api/admin";
import { createProject } from "../api/project";
import { useAuth } from "../auth/AuthContext";
import { can, type Capabilities } from "../auth/permissions";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import TaskModal from "../components/TaskModal";
import TaskCenterDrawer, { type TaskCenterGroup } from "../components/TaskCenterDrawer";
import Button from "../components/Button";
import WorkbuddyAccessCard from "../components/WorkbuddyAccessCard";
import type { PersonDTO } from "../types/people";
import type {
  WorkbenchOperationCardDTO,
  WorkbenchSectionStatus,
  WorkbenchTodoItemDTO,
  WorkbenchTaskItemDTO,
} from "../types/workbench";
import { useWorkbench } from "../workbench/WorkbenchContext";
import { formatBeijingTime } from "../utils/time";
import "./HomeDashboardPage.css";

const SAFE_FALLBACK = "信息待确认";

const COMPANY_ROLE: Record<string, string> = {
  admin: "系统管理员",
  boss: "总经理",
  consulting_director: "咨询总监",
  consultant: "顾问",
};

const PROJECT_ROLE: Record<string, string> = {
  project_manager: "项目经理",
  coach: "辅导老师",
  consultant: "顾问",
};

const PROJECT_STATUS: Record<string, string> = {
  active: "进行中",
  inactive: "已停用",
  archived: "已归档",
};

const SCOPE_LABEL: Record<string, string> = {
  personal: "个人知识",
  project: "项目知识",
  company: "公司知识",
};

const TODO_LABEL: Record<string, string> = {
  review_approval_failed: "处理失败审核",
  review_pending: "处理知识审核",
  ingest_pending: "确认待入库资料",
  ingest_failed: "处理失败入库任务",
  original_access_pending: "审批原文访问",
};

const TODO_ACTION: Record<string, string> = {
  resolve_review: "重新处理未完成的知识审核",
  decide_review: "确认当前由你负责的审核事项",
  confirm_ingest: "补充信息并确认知识资产入库",
  decide_original_access: "处理当前由你负责的原文访问申请",
};

const TODO_ROUTE: Record<string, string> = {
  reviews: "/review",
  upload: "/upload",
  original_access: "/original-access",
  ingest: "/admin/ingest",
  admin_ingest: "/admin/ingest",
};

const OPERATION_LABEL: Record<string, string> = {
  index_failed: "索引失败",
  parse_failed: "解析失败",
  kb_init_failed: "知识库初始化失败",
  pending_original_requests: "原文申请待处理",
  overdue_original_requests: "原文申请超时",
  archive_candidates: "归档候选",
  reuse_upgrade_candidates: "升格推荐",
};

const OPERATION_ICON: Record<string, LucideIcon> = {
  index_failed: SearchX,
  parse_failed: FileWarning,
  kb_init_failed: DatabaseZap,
  pending_original_requests: Clock3,
  overdue_original_requests: ShieldAlert,
  archive_candidates: Archive,
  reuse_upgrade_candidates: ArrowUpRight,
};

const OPERATION_ROUTE: Record<string, string> = {
  index_failed: "/admin/ingest",
  parse_failed: "/admin/ingest",
  pending_original_requests: "/original-access",
  overdue_original_requests: "/original-access",
  archive_candidates: "/knowledge",
  reuse_upgrade_candidates: "/knowledge",
};

type UiSectionStatus = WorkbenchSectionStatus | "loading";

function todayLabel(): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(new Date());
}

function safeTone(value: string): string {
  if (value === "error") return "is-critical";
  if (value === "warning") return "is-attention";
  return "is-standard";
}

function WorkbenchPanel({
  title,
  icon,
  meta,
  className = "",
  children,
}: {
  title: string;
  icon: ReactNode;
  meta?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`wb81-panel ${className}`.trim()}>
      <header className="wb81-panel-header">
        <span className="wb81-panel-icon" aria-hidden="true">
          {icon}
        </span>
        <h2>{title}</h2>
        {meta && <span className="wb81-panel-meta">{meta}</span>}
      </header>
      <div className="wb81-panel-body">{children}</div>
    </section>
  );
}

function SectionMessage({
  status,
  emptyText,
  loadingText,
  onRetry,
  emptyAction,
  errorText,
}: {
  status: UiSectionStatus;
  emptyText: string;
  loadingText: string;
  onRetry: () => void;
  emptyAction?: ReactNode;
  errorText?: string;
}) {
  if (status === "loading") {
    return (
      <div className="wb81-section-state is-loading" data-section-state="loading">
        {loadingText}
      </div>
    );
  }
  if (status === "forbidden") {
    return (
      <div className="wb81-section-state is-forbidden" data-section-state="forbidden">
        当前身份暂无访问权限
      </div>
    );
  }
  if (status === "error") {
    return (
      <div className="wb81-section-state is-error" data-section-state="error" role="alert">
        <span>{errorText ?? "内容暂时未能加载"}</span>
        <button type="button" onClick={onRetry}>
          重新加载
        </button>
      </div>
    );
  }
  return (
    <div className="wb81-section-state is-empty" data-section-state="empty">
      <span>{emptyText}</span>
      {emptyAction}
    </div>
  );
}

function TodoRow({ item }: { item: WorkbenchTodoItemDTO }) {
  if (item.count <= 0) return null;
  const title = TODO_LABEL[item.key] ?? "待处理事项";
  const description = TODO_ACTION[item.action_key] ?? SAFE_FALLBACK;
  const route = TODO_ROUTE[item.route_key];
  const content = (
    <>
      <span className={`wb81-todo-marker ${safeTone(item.severity)}`} aria-hidden="true" />
      <span className="wb81-todo-copy">
        <strong>{title}</strong>
        <small>{description}</small>
      </span>
      <span className="wb81-todo-count">{item.count}</span>
      {route && <ArrowRight size={15} aria-hidden="true" />}
    </>
  );
  return route ? (
    <Link className="wb81-todo-row" to={route}>
      {content}
    </Link>
  ) : (
    <div className="wb81-todo-row is-readonly">{content}</div>
  );
}

const TASK_STATUS_LABEL: Record<string, string> = {
  needs_action: "待处理",
  submitted: "已提交",
  processing: "处理中",
  completed: "已完成",
  partial: "部分完成",
  failed: "失败",
};

function PriorityTaskRow({ item, onOpen }: { item: WorkbenchTaskItemDTO; onOpen: () => void }) {
  return (
    <button type="button" className="tc90-priority-row" onClick={onOpen}>
      <span className={`tc90-priority-rail is-${item.priority}`} aria-hidden="true" />
      <span className="tc90-priority-copy">
        <strong>{item.object_name}</strong>
        <small>
          {item.project_name || item.responsibility} · {item.next_action_label}
        </small>
      </span>
      <span className={`tc90-status is-${item.status}`}>
        {TASK_STATUS_LABEL[item.status] || item.status}
      </span>
      <ArrowRight size={15} aria-hidden="true" />
    </button>
  );
}

function operationRoute(
  item: WorkbenchOperationCardDTO,
  capabilities: Capabilities,
  authMe: ReturnType<typeof useAuth>["authMe"],
): string | undefined {
  if (item.key !== "kb_init_failed") return OPERATION_ROUTE[item.key];
  if (capabilities.isAdmin) return "/admin/weknora-models";
  if (item.scope === "company") {
    return capabilities.isGovernance ? "/admin/company-kb" : undefined;
  }
  if (item.scope === "personal") return capabilities.isBusinessUser ? "/my/knowledge" : undefined;
  if (item.scope === "project" && item.project_id) {
    if (
      capabilities.isGovernance ||
      authMe?.projects.some(
        (project) =>
          project.projectId === item.project_id && project.projectRole === "project_manager",
      )
    ) {
      return "/admin/weknora-models";
    }
    return authMe?.projects.some((project) => project.projectId === item.project_id)
      ? `/project/${encodeURIComponent(item.project_id)}`
      : undefined;
  }
  return undefined;
}

function OperationCard({
  item,
  capabilities,
  authMe,
}: {
  item: WorkbenchOperationCardDTO;
  capabilities: Capabilities;
  authMe: ReturnType<typeof useAuth>["authMe"];
}) {
  const Icon = OPERATION_ICON[item.key] ?? BriefcaseBusiness;
  const route = operationRoute(item, capabilities, authMe);
  const label = OPERATION_LABEL[item.key] ?? SAFE_FALLBACK;
  const content = (
    <>
      <div className="wb81-operation-heading">
        <span>
          {label}
          {item.context_label ? ` · ${item.context_label}` : ""}
        </span>
        <span className="wb81-operation-icon" aria-hidden="true">
          <Icon size={17} />
        </span>
      </div>
      <div className="wb81-operation-footer">
        <strong>{item.count}</strong>
        {route && (
          <span>
            查看
            <ArrowRight size={14} aria-hidden="true" />
          </span>
        )}
      </div>
    </>
  );
  return route ? (
    <Link className={`wb81-operation ${safeTone(item.severity)}`} to={route}>
      {content}
    </Link>
  ) : (
    <div className={`wb81-operation ${safeTone(item.severity)}`}>{content}</div>
  );
}

export default function HomeDashboardPage() {
  const { authMe, capabilities, reload } = useAuth();
  const navigate = useNavigate();
  const { overview, state: pageState, refresh: load } = useWorkbench();
  const [taskDrawerOpen, setTaskDrawerOpen] = useState(false);
  const [taskDrawerGroup, setTaskDrawerGroup] = useState<TaskCenterGroup>("my_tasks");

  // --- create project modal (governance users with no projects) ---
  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createPmId, setCreatePmId] = useState("");
  const [createProjectCode, setCreateProjectCode] = useState("");
  const [createDefaultConfidentiality, setCreateDefaultConfidentiality] = useState("L2");
  const [createPeople, setCreatePeople] = useState<PersonDTO[]>([]);
  const [createSaving, setCreateSaving] = useState(false);
  const [createError, setCreateError] = useState("");

  // 窄屏时同一行内多个面板通过下拉框切换显示。
  const [primaryTab, setPrimaryTab] = useState<"todos" | "operations" | "projects">("todos");
  const [secondaryTab, setSecondaryTab] = useState<"workbuddy" | "recent">("workbuddy");

  const openCreate = useCallback(() => {
    setCreateName("");
    setCreatePmId(authMe?.userId ?? "");
    setCreateProjectCode("");
    setCreateDefaultConfidentiality("L2");
    setCreateError("");
    setCreateOpen(true);
    fetchPeople()
      .then((res) => setCreatePeople(res.items))
      .catch(() => {});
  }, [authMe?.userId]);

  const submitCreate = useCallback(async () => {
    if (!createName.trim() || !createProjectCode.trim()) {
      setCreateError("请填写项目名称和项目代码");
      return;
    }
    if (!createPmId) {
      setCreateError("请选择项目经理");
      return;
    }
    setCreateSaving(true);
    setCreateError("");
    try {
      const created = await createProject({
        name: createName.trim(),
        project_manager_user_id: createPmId,
        project_code: createProjectCode.trim().toUpperCase(),
        project_code_active: true,
        naming_default_confidentiality: createDefaultConfidentiality,
      });
      setCreateOpen(false);
      await reload();
      navigate(`/project/${encodeURIComponent(created.id)}`);
    } catch {
      setCreateError("创建失败，请重试");
    } finally {
      setCreateSaving(false);
    }
  }, [createName, createPmId, createProjectCode, createDefaultConfidentiality, reload, navigate]);

  const fallbackStatus: UiSectionStatus = pageState === "loading" ? "loading" : "error";
  const todosStatus = overview?.todos.status ?? fallbackStatus;
  const operationsStatus = overview?.operations.status ?? fallbackStatus;
  const projectsStatus = overview?.projects.status ?? fallbackStatus;
  const recentStatus = overview?.recent_activity.status ?? fallbackStatus;
  const taskCenterStatus = overview?.task_center.status ?? fallbackStatus;
  const todoItems = overview?.todos.items.filter((item) => item.count > 0) ?? [];
  const operationCards = overview?.operations.data?.cards.filter((item) => item.count > 0) ?? [];
  const canShowAssetTitles =
    overview?.operations.status === "available" && overview.operations.data?.title_visible === true;

  const roleText = authMe?.activeCompanyRole
    ? (COMPANY_ROLE[authMe.activeCompanyRole] ?? SAFE_FALLBACK)
    : SAFE_FALLBACK;
  const displayName = authMe?.name?.trim() || "同事";
  const todoCount = todoItems.reduce((total, item) => total + item.count, 0);
  const taskCenter = overview?.task_center;
  const taskGroups = {
    my_tasks: taskCenter?.my_tasks ?? [],
    running_jobs: taskCenter?.running_jobs ?? [],
    attention_items: taskCenter?.attention_items ?? [],
    recent_completed: taskCenter?.recent_completed ?? [],
  };
  const openTaskGroup = (group: TaskCenterGroup) => {
    setTaskDrawerGroup(group);
    setTaskDrawerOpen(true);
  };

  return (
    <ProductPage className="today-workbench wb81-workbench">
      <PageHeader
        title={
          <>
            你好，<span className="wb81-user-name">{displayName}</span>
          </>
        }
        description={`${roleText} · ${todayLabel()}`}
        status={
          <StatusBadge
            tone={
              pageState === "error"
                ? "danger"
                : pageState === "loading"
                  ? "info"
                  : todoCount > 0
                    ? "warning"
                    : "success"
            }
            label={
              pageState === "error"
                ? "工作状态需要重新加载"
                : pageState === "loading"
                  ? "正在同步今日工作"
                  : todoCount > 0
                    ? `${todoCount} 项待处理`
                    : "今日工作已就绪"
            }
          />
        }
        actions={
          <div className="wb81-header-tools">
            {(can.viewKnowledge(capabilities) || can.viewUpload(capabilities)) && (
              <nav className="wb81-shortcuts" aria-label="快捷入口">
                {can.viewKnowledge(capabilities) && (
                  <Link to="/knowledge">
                    <LibraryBig size={15} aria-hidden="true" />
                    知识资产库
                  </Link>
                )}
                {can.viewUpload(capabilities) && (
                  <Link to="/upload">
                    <UploadCloud size={15} aria-hidden="true" />
                    上传资产化
                  </Link>
                )}
              </nav>
            )}
            <button
              className="wb81-refresh"
              type="button"
              disabled={pageState === "loading"}
              onClick={() => void load()}
            >
              <RefreshCw size={15} aria-hidden="true" />
              刷新
            </button>
          </div>
        }
      />

      <div className="wb81-dashboard">
        <section className="tc90-command" aria-labelledby="tc90-command-title">
          <header className="tc90-command-header">
            <div>
              <span>今日任务调度</span>
              <h2 id="tc90-command-title">
                {taskCenter?.summary.needs_action
                  ? `有 ${taskCenter.summary.needs_action} 项需要你处理`
                  : "当前没有需要你立即处理的任务"}
              </h2>
              <p>已提交、处理中与最终结果分开呈现，避免重复确认。</p>
            </div>
            <button type="button" onClick={() => openTaskGroup("my_tasks")}>
              打开任务中心
            </button>
          </header>
          {taskCenterStatus === "available" || taskCenterStatus === "empty" ? (
            <>
              <div className="tc90-summary-grid">
                <button type="button" onClick={() => openTaskGroup("my_tasks")}>
                  <ListChecks size={18} />
                  <span>我的任务</span>
                  <strong>{taskCenter?.summary.needs_action ?? 0}</strong>
                  <small>需要动作</small>
                </button>
                <button type="button" onClick={() => openTaskGroup("running_jobs")}>
                  <Gauge size={18} />
                  <span>进行中的作业</span>
                  <strong>{taskCenter?.summary.running ?? 0}</strong>
                  <small>已提交 / 处理中</small>
                </button>
                <button type="button" onClick={() => openTaskGroup("attention_items")}>
                  <TriangleAlert size={18} />
                  <span>需要关注</span>
                  <strong>{taskCenter?.summary.attention ?? 0}</strong>
                  <small>风险与异常</small>
                </button>
                <button type="button" onClick={() => openTaskGroup("recent_completed")}>
                  <CircleCheckBig size={18} />
                  <span>最近完成</span>
                  <strong>{taskCenter?.summary.completed_today ?? 0}</strong>
                  <small>今日业务终态</small>
                </button>
              </div>
              <div className="tc90-priority-board">
                <div className="tc90-priority-heading">
                  <span>优先处理</span>
                  <small>按失败、超时与责任关系排序</small>
                </div>
                {taskCenter?.priority_items.length ? (
                  taskCenter.priority_items
                    .slice(0, 4)
                    .map((item) => (
                      <PriorityTaskRow
                        key={item.task_ref}
                        item={item}
                        onOpen={() =>
                          openTaskGroup(
                            item.task_type === "review" ||
                              item.task_type === "ingest" ||
                              item.task_type === "original_access"
                              ? "my_tasks"
                              : "attention_items",
                          )
                        }
                      />
                    ))
                ) : (
                  <div className="tc90-priority-empty">
                    优先队列已清空，可以继续关注进行中的作业。
                  </div>
                )}
              </div>
            </>
          ) : (
            <SectionMessage
              status={taskCenterStatus}
              loadingText="正在同步任务状态…"
              emptyText="当前没有任务"
              onRetry={() => void load()}
              errorText="任务状态暂时不可用，请重新加载"
            />
          )}
        </section>
        <div className="wb81-row wb81-row-primary">
          <div className="wb81-row-tabs" aria-label="工作台主栏切换">
            <select
              value={primaryTab}
              onChange={(e) => setPrimaryTab(e.target.value as typeof primaryTab)}
            >
              <option value="todos">我的待办</option>
              <option value="operations">资产运行概览</option>
              <option value="projects">项目概览</option>
            </select>
          </div>

          <WorkbenchPanel
            title="我的待办"
            icon={<ListChecks size={17} />}
            meta={todosStatus === "available" ? `${todoCount} 项` : undefined}
            className={`is-todos ${primaryTab === "todos" ? "is-active-mobile" : ""}`}
          >
            {todosStatus === "available" && todoItems.length > 0 ? (
              <div className="wb81-todo-list">
                {todoItems.map((item, index) => (
                  <TodoRow key={`${item.key}-${index}`} item={item} />
                ))}
              </div>
            ) : (
              <SectionMessage
                status={todosStatus === "available" ? "empty" : todosStatus}
                loadingText="正在加载待办事项…"
                emptyText="今天没有待处理事项"
                onRetry={() => void load()}
                emptyAction={
                  can.viewKnowledge(capabilities) ? <Link to="/knowledge">浏览知识资产</Link> : null
                }
              />
            )}
          </WorkbenchPanel>

          <WorkbenchPanel
            title="资产运行概览"
            icon={<BriefcaseBusiness size={17} />}
            className={`is-operations ${primaryTab === "operations" ? "is-active-mobile" : ""}`}
          >
            {operationsStatus === "available" && operationCards.length > 0 ? (
              <div className="wb81-operation-grid">
                {operationCards.map((item, index) => (
                  <OperationCard
                    key={`${item.key}-${index}`}
                    item={item}
                    capabilities={capabilities}
                    authMe={authMe}
                  />
                ))}
              </div>
            ) : (
              <SectionMessage
                status={operationsStatus === "available" ? "empty" : operationsStatus}
                loadingText="正在加载资产运行状态…"
                emptyText="当前没有需要处理的运营事项"
                errorText="运行数据暂时不可用，请重新加载"
                onRetry={() => void load()}
              />
            )}
          </WorkbenchPanel>

          <WorkbenchPanel
            title="项目概览"
            icon={<FolderKanban size={17} />}
            meta={
              projectsStatus === "available" && overview
                ? `${overview.projects.items.length} 个项目`
                : undefined
            }
            className={`is-projects ${primaryTab === "projects" ? "is-active-mobile" : ""}`}
          >
            {projectsStatus === "available" && overview && overview.projects.items.length > 0 ? (
              <div className="wb81-project-list">
                {overview.projects.items.map((project) => (
                  <Link
                    key={project.project_id}
                    to={`/project/${encodeURIComponent(project.project_id)}`}
                  >
                    <span className="wb81-project-copy">
                      <strong>{project.name.trim() || "待确认项目"}</strong>
                      <span className="wb81-project-facts">
                        <small>{PROJECT_ROLE[project.project_role] ?? SAFE_FALLBACK}</small>
                        <small>{PROJECT_STATUS[project.status] ?? SAFE_FALLBACK}</small>
                      </span>
                    </span>
                    <span className="wb81-project-entry">
                      进入项目
                      <ArrowRight size={15} aria-hidden="true" />
                    </span>
                  </Link>
                ))}
              </div>
            ) : (
              <SectionMessage
                status={projectsStatus === "available" ? "empty" : projectsStatus}
                loadingText="正在加载协作空间…"
                emptyText="当前没有可访问的项目"
                emptyAction={
                  capabilities.isGovernance ? (
                    <button type="button" className="wb81-empty-action" onClick={openCreate}>
                      <Plus size={16} />
                      新建项目
                    </button>
                  ) : undefined
                }
                onRetry={() => void load()}
              />
            )}
          </WorkbenchPanel>
        </div>

        <div className="wb81-row wb81-row-secondary">
          <div className="wb81-row-tabs" aria-label="工作台副栏切换">
            <select
              value={secondaryTab}
              onChange={(e) => setSecondaryTab(e.target.value as typeof secondaryTab)}
            >
              {capabilities.isBusinessUser && <option value="workbuddy">WorkBuddy 接入</option>}
              <option value="recent">最近动态</option>
            </select>
          </div>

          {capabilities.isBusinessUser && (
            <WorkbenchPanel
              title="WorkBuddy 接入"
              icon={<BriefcaseBusiness size={17} />}
              className={`is-workbuddy ${secondaryTab === "workbuddy" ? "is-active-mobile" : ""}`}
            >
              <WorkbuddyAccessCard />
            </WorkbenchPanel>
          )}

          <WorkbenchPanel
            title="最近动态"
            icon={<LibraryBig size={17} />}
            meta={
              recentStatus === "available" && overview
                ? `${overview.recent_activity.items.length} 条更新`
                : undefined
            }
            className={`is-recent ${secondaryTab === "recent" ? "is-active-mobile" : ""}`}
          >
            {recentStatus === "available" &&
            overview &&
            overview.recent_activity.items.length > 0 ? (
              <div className="wb81-recent-list">
                {overview.recent_activity.items.map((item) => (
                  <Link key={item.asset_id} to={`/knowledge/${encodeURIComponent(item.asset_id)}`}>
                    <span className="wb81-activity-copy">
                      <strong>
                        {canShowAssetTitles ? item.title.trim() || "待确认资产" : "业务标题已隐藏"}
                      </strong>
                      <small>
                        {SCOPE_LABEL[item.scope] ?? SAFE_FALLBACK}
                        {item.project_name?.trim() ? ` · ${item.project_name}` : ""}
                      </small>
                    </span>
                    <time>{formatBeijingTime(item.updated_at)}</time>
                    <ArrowRight size={15} aria-hidden="true" />
                  </Link>
                ))}
              </div>
            ) : (
              <SectionMessage
                status={recentStatus === "available" ? "empty" : recentStatus}
                loadingText="正在加载最近动态…"
                emptyText="当前没有最近更新的资产"
                onRetry={() => void load()}
              />
            )}
          </WorkbenchPanel>
        </div>
      </div>

      <TaskCenterDrawer
        key={taskDrawerGroup}
        open={taskDrawerOpen}
        initialGroup={taskDrawerGroup}
        groups={taskGroups}
        onClose={() => setTaskDrawerOpen(false)}
      />

      <TaskModal
        open={createOpen}
        title="新建项目"
        description="填写基本信息后创建项目，创建成功后再进入项目空间补充详细配置。"
        onClose={() => setCreateOpen(false)}
        busy={createSaving}
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setCreateOpen(false)}
              disabled={createSaving}
            >
              取消
            </Button>
            <Button
              variant="primary"
              onClick={submitCreate}
              disabled={
                createSaving || !createName.trim() || !createPmId || !createProjectCode.trim()
              }
            >
              {createSaving ? "创建中…" : "创建项目"}
            </Button>
          </>
        }
      >
        <div className="wb81-modal-body">
          <label className="wb81-field">
            <span>项目名称</span>
            <input
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              placeholder="输入项目名称"
              maxLength={100}
            />
          </label>
          <label className="wb81-field">
            <span>项目经理</span>
            <select value={createPmId} onChange={(e) => setCreatePmId(e.target.value)}>
              <option value="">选择人员</option>
              {createPeople.map((p) => (
                <option key={p.user_id} value={p.user_id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label className="wb81-field">
            <span>项目代码</span>
            <input
              value={createProjectCode}
              onChange={(event) => setCreateProjectCode(event.target.value.toUpperCase())}
              placeholder="如 BW-2601"
              maxLength={20}
            />
            <small>创建后立即启用，作为规范命名必需项。</small>
          </label>
          <label className="wb81-field">
            <span>默认保密级别</span>
            <select
              value={createDefaultConfidentiality}
              onChange={(event) => setCreateDefaultConfidentiality(event.target.value)}
            >
              {["L1", "L2", "L3", "L4", "L5"].map((level) => (
                <option key={level}>{level}</option>
              ))}
            </select>
          </label>
          {createError && (
            <p className="wb81-field-error" role="alert">
              {createError}
            </p>
          )}
        </div>
      </TaskModal>
    </ProductPage>
  );
}
