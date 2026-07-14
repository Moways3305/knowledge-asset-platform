import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  Clock3,
  FileCheck2,
  FolderKanban,
  KeyRound,
  LibraryBig,
  Lightbulb,
  ListChecks,
  RefreshCw,
  ShieldCheck,
  UploadCloud,
  UserRound,
} from "lucide-react";
import { ApiError } from "../api/http";
import { fetchKnowledgeOpsInsights, fetchOriginalAccessRequests } from "../api/knowledge";
import { fetchReviews } from "../api/review";
import { fetchPendingIngestTasks } from "../api/ingest";
import { fetchProjects } from "../api/project";
import { useAuth } from "../auth/AuthContext";
import { can } from "../auth/permissions";
import { EmptyState, PageHeader, ProductPage, StatusStrip } from "../components/ProductLayout";
import type { KnowledgeOpsInsightsDTO } from "../types/insights";
import type { ProjectListItemDTO } from "../types/project";

const roleLabel: Record<string, string> = {
  boss: "Boss",
  consulting_director: "咨询总监",
  consultant: "顾问",
  admin: "管理员",
};

const projectRoleLabel: Record<string, string> = {
  project_manager: "项目经理",
  consultant: "顾问",
  coach: "辅导老师",
};

type LoadStatus = "loading" | "ready" | "unavailable" | "error";
type LoadState<T> = { status: LoadStatus; data: T | null };
type CountSource = LoadState<number>;

type Todo = {
  key: string;
  label: string;
  description: string;
  count: number;
  to: string;
  severity: "default" | "warning" | "danger";
};

const loadingState = <T,>(): LoadState<T> => ({ status: "loading", data: null });
const unavailableState = <T,>(): LoadState<T> => ({ status: "unavailable", data: null });

function greeting(): string {
  const hour = Number(
    new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Shanghai",
      hour: "2-digit",
      hour12: false,
    }).format(new Date()),
  );
  if (hour < 6) return "夜深了";
  if (hour < 11) return "上午好";
  if (hour < 13) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

function todayLabel(): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(new Date());
}

function statusFromError<T>(error: unknown): LoadState<T> {
  return error instanceof ApiError && error.status === 403
    ? unavailableState<T>()
    : { status: "error", data: null };
}

function SectionState({
  status,
  loadingText,
  unavailableText,
  onRetry,
}: {
  status: LoadStatus;
  loadingText: string;
  unavailableText: string;
  onRetry: () => void;
}) {
  if (status === "loading") return <p className="workbench-state">{loadingText}</p>;
  if (status === "unavailable") return <p className="workbench-state">{unavailableText}</p>;
  if (status === "error") {
    return (
      <div className="workbench-state is-error" role="alert">
        <span>数据未加载成功。</span>
        <button type="button" className="btn-secondary btn-small" onClick={onRetry}>
          <RefreshCw size={14} aria-hidden="true" />
          重新加载
        </button>
      </div>
    );
  }
  return null;
}

function WorkbenchSection({
  title,
  description,
  icon,
  children,
  className = "",
}: {
  title: string;
  description?: string;
  icon: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`workbench-section ${className}`.trim()}>
      <header className="workbench-section-header">
        <span className="workbench-section-icon" aria-hidden="true">
          {icon}
        </span>
        <div>
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
      </header>
      {children}
    </section>
  );
}

export default function HomeDashboardPage() {
  const { authMe, status: authStatus, capabilities } = useAuth();
  const [insights, setInsights] = useState<LoadState<KnowledgeOpsInsightsDTO>>(loadingState);
  const [projects, setProjects] = useState<LoadState<ProjectListItemDTO[]>>(loadingState);
  const [pendingIngest, setPendingIngest] = useState<CountSource>(loadingState);
  const [pendingReviews, setPendingReviews] = useState<CountSource>(loadingState);
  const [originalInbox, setOriginalInbox] = useState<CountSource>(loadingState);
  const [originalMine, setOriginalMine] = useState<CountSource>(loadingState);

  const isAuthenticated = authStatus === "authenticated";
  const businessEnabled = isAuthenticated && capabilities.isBusinessUser;
  const insightsEnabled = isAuthenticated && (capabilities.isBusinessUser || capabilities.isAdmin);
  const projectsEnabled = isAuthenticated && can.viewProject(capabilities);

  const loadInsights = useCallback(async () => {
    if (!insightsEnabled) {
      setInsights(unavailableState());
      return;
    }
    setInsights(loadingState());
    try {
      setInsights({
        status: "ready",
        data: await fetchKnowledgeOpsInsights({ scope: "company" }),
      });
    } catch (error) {
      setInsights(statusFromError(error));
    }
  }, [insightsEnabled]);

  const loadProjects = useCallback(async () => {
    if (!projectsEnabled) {
      setProjects(unavailableState());
      return;
    }
    setProjects(loadingState());
    try {
      const response = await fetchProjects();
      setProjects({ status: "ready", data: response.items });
    } catch (error) {
      setProjects(statusFromError(error));
    }
  }, [projectsEnabled]);

  const loadPendingIngest = useCallback(async () => {
    if (!businessEnabled) {
      setPendingIngest(unavailableState());
      return;
    }
    setPendingIngest(loadingState());
    try {
      setPendingIngest({ status: "ready", data: (await fetchPendingIngestTasks()).length });
    } catch (error) {
      setPendingIngest(statusFromError(error));
    }
  }, [businessEnabled]);

  const loadPendingReviews = useCallback(async () => {
    if (!businessEnabled) {
      setPendingReviews(unavailableState());
      return;
    }
    setPendingReviews(loadingState());
    try {
      const reviews = await fetchReviews({});
      setPendingReviews({
        status: "ready",
        data: reviews.filter(
          (review) =>
            review.can_decide && ["pending_reviewer", "approval_failed"].includes(review.status),
        ).length,
      });
    } catch (error) {
      setPendingReviews(statusFromError(error));
    }
  }, [businessEnabled]);

  const loadOriginalInbox = useCallback(async () => {
    if (!businessEnabled) {
      setOriginalInbox(unavailableState());
      return;
    }
    setOriginalInbox(loadingState());
    try {
      const response = await fetchOriginalAccessRequests("inbox");
      setOriginalInbox({
        status: "ready",
        data: response.items.filter((request) => request.status === "pending").length,
      });
    } catch (error) {
      setOriginalInbox(statusFromError(error));
    }
  }, [businessEnabled]);

  const loadOriginalMine = useCallback(async () => {
    if (!businessEnabled) {
      setOriginalMine(unavailableState());
      return;
    }
    setOriginalMine(loadingState());
    try {
      const response = await fetchOriginalAccessRequests("mine");
      setOriginalMine({
        status: "ready",
        data: response.items.filter((request) => request.status === "pending").length,
      });
    } catch (error) {
      setOriginalMine(statusFromError(error));
    }
  }, [businessEnabled]);

  useEffect(() => {
    void loadInsights();
    void loadProjects();
    void loadPendingIngest();
    void loadPendingReviews();
    void loadOriginalInbox();
    void loadOriginalMine();
  }, [
    loadInsights,
    loadOriginalInbox,
    loadOriginalMine,
    loadPendingIngest,
    loadPendingReviews,
    loadProjects,
  ]);

  const todoSources = [pendingIngest, pendingReviews, originalInbox, originalMine, insights];
  const todoLoading = todoSources.some((source) => source.status === "loading");
  const todoErrors = [
    { label: "待确认入库", state: pendingIngest, retry: loadPendingIngest },
    { label: "升级审核", state: pendingReviews, retry: loadPendingReviews },
    { label: "待审批原文申请", state: originalInbox, retry: loadOriginalInbox },
    { label: "我发起的原文申请", state: originalMine, retry: loadOriginalMine },
    { label: "运营状态", state: insights, retry: loadInsights },
  ].filter((source) => source.state.status === "error");
  const hasReadyTodoSource = todoSources.some((source) => source.status === "ready");

  const todos = useMemo(() => {
    const items: Todo[] = [];
    const add = (item: Todo, source: CountSource) => {
      if (source.status === "ready" && source.data && source.data > 0) items.push(item);
    };
    add(
      {
        key: "ingest",
        label: "确认待入库资料",
        description: "处理微盘扫描产生的资产化确认任务",
        count: pendingIngest.data ?? 0,
        to: "/upload",
        severity: "default",
      },
      pendingIngest,
    );
    add(
      {
        key: "reviews",
        label: "处理升级审核",
        description: "审核知识升级与资产化确认申请",
        count: pendingReviews.data ?? 0,
        to: "/review",
        severity: "default",
      },
      pendingReviews,
    );
    add(
      {
        key: "original-inbox",
        label: "审批原文访问",
        description: "处理需要你审批的原文授权申请",
        count: originalInbox.data ?? 0,
        to: "/original-access",
        severity: "warning",
      },
      originalInbox,
    );
    add(
      {
        key: "original-mine",
        label: "跟进原文申请",
        description: "查看仍在处理中的原文访问申请",
        count: originalMine.data ?? 0,
        to: "/original-access",
        severity: "default",
      },
      originalMine,
    );
    if (insights.status === "ready" && insights.data) {
      add(
        {
          key: "index-failed",
          label: "处理索引失败",
          description: "检查失败资产并发起可用的重试操作",
          count: insights.data.indexing.index_failed,
          to: capabilities.isAdmin || capabilities.isGovernance ? "/admin/ingest" : "/knowledge",
          severity: "danger",
        },
        { status: "ready", data: insights.data.indexing.index_failed },
      );
      add(
        {
          key: "original-overdue",
          label: "处理超时原文申请",
          description: "跟进超过处理时限的原文访问申请",
          count: insights.data.access.overdue_original_requests,
          to: "/original-access",
          severity: "warning",
        },
        { status: "ready", data: insights.data.access.overdue_original_requests },
      );
      add(
        {
          key: "needs-update",
          label: "更新知识资产",
          description: "处理已标记为需要更新的知识资产",
          count: insights.data.lifecycle.needs_update,
          to: "/knowledge",
          severity: "warning",
        },
        { status: "ready", data: insights.data.lifecycle.needs_update },
      );
    }
    const severityRank = { danger: 0, warning: 1, default: 2 };
    return items.sort(
      (left, right) =>
        severityRank[left.severity] - severityRank[right.severity] || right.count - left.count,
    );
  }, [
    capabilities.isAdmin,
    capabilities.isGovernance,
    insights,
    originalInbox,
    originalMine,
    pendingIngest,
    pendingReviews,
  ]);

  const projectRows = useMemo(() => {
    if (projects.status === "ready" && projects.data) {
      return projects.data.map((project) => {
        const membership = authMe?.projects.find((item) => item.projectId === project.id);
        return {
          id: project.id,
          name: project.name,
          status: project.status,
          role: membership
            ? (projectRoleLabel[membership.projectRole] ?? membership.projectRole)
            : null,
          canManage: project.can_manage,
        };
      });
    }
    return (authMe?.projects ?? []).map((project) => ({
      id: project.projectId,
      name: project.projectName,
      status: null,
      role: projectRoleLabel[project.projectRole] ?? project.projectRole,
      canManage: project.projectRole === "project_manager",
    }));
  }, [authMe?.projects, projects]);

  const roleText = authMe?.companyRoles.map((role) => roleLabel[role] ?? role).join(" / ");
  const headerActions = [
    can.viewKnowledge(capabilities) && {
      to: "/knowledge",
      label: "进入知识资产库",
      icon: LibraryBig,
    },
    can.viewUpload(capabilities) && { to: "/upload", label: "上传资产化", icon: UploadCloud },
  ].filter(Boolean) as { to: string; label: string; icon: typeof LibraryBig }[];

  const statusItems = insights.data
    ? [
        {
          label: (
            <Link
              to={
                capabilities.isAdmin || capabilities.isGovernance ? "/admin/ingest" : "/knowledge"
              }
            >
              索引失败
            </Link>
          ),
          value: insights.data.indexing.index_failed,
          tone:
            insights.data.indexing.index_failed > 0 ? ("danger" as const) : ("neutral" as const),
        },
        {
          label: <Link to="/knowledge">未索引</Link>,
          value: insights.data.indexing.skipped + insights.data.indexing.not_indexed,
        },
        {
          label: <Link to="/original-access">原文待处理</Link>,
          value: insights.data.access.pending_original_requests,
          tone:
            insights.data.access.pending_original_requests > 0
              ? ("warning" as const)
              : ("neutral" as const),
        },
        {
          label: <Link to="/knowledge">待更新</Link>,
          value: insights.data.lifecycle.needs_update,
          tone:
            insights.data.lifecycle.needs_update > 0 ? ("warning" as const) : ("neutral" as const),
        },
        {
          label: <Link to="/knowledge">归档候选</Link>,
          value: insights.data.lifecycle.archive_candidates,
        },
        {
          label: <Link to="/knowledge">复用升格候选</Link>,
          value: insights.data.lifecycle.reuse_upgrade_candidates,
        },
      ]
    : [];

  return (
    <ProductPage className="today-workbench">
      <PageHeader
        eyebrow="今日工作台"
        title={
          <>
            {greeting()}，{authMe?.name ?? "同事"}
          </>
        }
        description={`当前身份：${roleText || "未识别"}${
          authMe && !authMe.isBusinessUser ? " · 系统运营视图" : ""
        }`}
        actions={<time className="workbench-date">{todayLabel()}</time>}
      />

      {headerActions.length > 0 && (
        <nav className="workbench-primary-actions" aria-label="主要工作入口">
          {headerActions.map(({ to, label, icon: Icon }) => (
            <Link key={to} to={to} className="btn-secondary">
              <Icon size={16} aria-hidden="true" />
              {label}
            </Link>
          ))}
        </nav>
      )}

      <div className="workbench-command-grid">
        <div className="workbench-main-column">
          <WorkbenchSection
            title="我的待办"
            description="按风险与数量排序，只显示当前身份可处理的真实工作"
            icon={<ListChecks size={18} />}
            className="workbench-todos-section"
          >
            {todoLoading && todos.length === 0 ? (
              <p className="workbench-state">正在汇总待办…</p>
            ) : (
              <>
                {todos.length > 0 && (
                  <div className="workbench-todo-list">
                    {todos.map((todo) => (
                      <Link
                        key={todo.key}
                        to={todo.to}
                        className={`workbench-todo is-${todo.severity}`}
                      >
                        <span className="workbench-todo-count">{todo.count}</span>
                        <span className="workbench-todo-copy">
                          <strong>{todo.label}</strong>
                          <span>{todo.description}</span>
                        </span>
                        <ArrowRight size={17} aria-hidden="true" />
                      </Link>
                    ))}
                  </div>
                )}
                {todoErrors.length > 0 && (
                  <div className="workbench-source-errors" role="alert">
                    <strong>部分待办数据未加载成功</strong>
                    {todoErrors.map((source) => (
                      <div key={source.label}>
                        <span>{source.label}</span>
                        <button type="button" onClick={source.retry}>
                          重新加载
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {!todoLoading &&
                  todos.length === 0 &&
                  todoErrors.length === 0 &&
                  (hasReadyTodoSource ? (
                    <EmptyState
                      title="今天没有待处理事项"
                      description="当前可用工作队列均为 0，可继续浏览知识资产或进入项目空间。"
                      action={
                        can.viewKnowledge(capabilities) ? (
                          <Link className="btn-secondary" to="/knowledge">
                            浏览知识资产
                          </Link>
                        ) : undefined
                      }
                    />
                  ) : (
                    <EmptyState
                      title="当前身份没有可用待办队列"
                      description="此工作台不会向无权限的接口发起请求。"
                    />
                  ))}
              </>
            )}
          </WorkbenchSection>

          <WorkbenchSection
            title="资产运行概览"
            description={
              insights.data
                ? `${insights.data.window_days} 天运营窗口${
                    insights.data.title_visible ? "" : " · 业务标题已按权限隐藏"
                  }`
                : "按当前身份裁剪的知识运营状态"
            }
            icon={<FileCheck2 size={18} />}
          >
            {insights.status === "ready" ? (
              <StatusStrip items={statusItems} label="知识资产运营状态" />
            ) : (
              <SectionState
                status={insights.status}
                loadingText="正在加载资产运行状态…"
                unavailableText="当前身份不可查看资产运行状态。"
                onRetry={() => void loadInsights()}
              />
            )}
          </WorkbenchSection>
        </div>

        <WorkbenchSection
          title="今日洞察与建议"
          description="来自当前运营洞察，不生成额外判断"
          icon={<Lightbulb size={18} />}
          className="workbench-insight-column"
        >
          {insights.status !== "ready" ? (
            <SectionState
              status={insights.status}
              loadingText="正在加载今日建议…"
              unavailableText="当前身份不可查看运营建议。"
              onRetry={() => void loadInsights()}
            />
          ) : insights.data && insights.data.recommendations.length > 0 ? (
            <ul className="workbench-recommendations">
              {insights.data.recommendations.map((recommendation) => (
                <li key={recommendation.key} className={`is-${recommendation.severity}`}>
                  <span>{recommendation.message}</span>
                  {recommendation.target && (
                    <Link to={recommendation.target}>
                      前往处理 <ArrowRight size={14} aria-hidden="true" />
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="今天没有运营建议" description="当前接口没有返回需要展示的建议。" />
          )}
        </WorkbenchSection>
      </div>

      <div className="workbench-context-grid">
        <WorkbenchSection
          title="协作空间"
          description="当前身份可访问的项目知识空间"
          icon={<Building2 size={18} />}
        >
          {projects.status === "loading" ? (
            <p className="workbench-state">正在加载项目范围…</p>
          ) : projectRows.length > 0 ? (
            <div className="workbench-project-list">
              {projectRows.map((project) => (
                <Link key={project.id} to={`/project/${project.id}/knowledge`}>
                  <span className="workbench-project-mark" aria-hidden="true">
                    <FolderKanban size={17} />
                  </span>
                  <span className="workbench-project-copy">
                    <strong>{project.name}</strong>
                    <span>
                      {[project.role, project.status === "active" ? "进行中" : project.status]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                  <ArrowRight size={16} aria-hidden="true" />
                </Link>
              ))}
            </div>
          ) : projects.status === "error" ? (
            <SectionState
              status="error"
              loadingText=""
              unavailableText=""
              onRetry={() => void loadProjects()}
            />
          ) : projects.status === "unavailable" ? (
            <EmptyState
              title="当前身份没有可访问项目"
              description="项目入口仅在真实项目成员关系或治理权限存在时显示。"
            />
          ) : (
            <EmptyState
              title="暂无可访问项目"
              description="项目列表已加载，当前没有可进入的项目。"
            />
          )}
          {projects.status === "error" && projectRows.length > 0 && (
            <div className="workbench-fallback-note" role="alert">
              <span>项目列表加载失败，以上入口来自当前登录身份中的有效项目关系。</span>
              <button type="button" onClick={() => void loadProjects()}>
                重新加载
              </button>
            </div>
          )}
        </WorkbenchSection>

        <WorkbenchSection
          title="知识流转与最近动态"
          description="只展示运营洞察返回的最近项目"
          icon={<Clock3 size={18} />}
        >
          {insights.status !== "ready" ? (
            <SectionState
              status={insights.status}
              loadingText="正在加载最近动态…"
              unavailableText="当前身份不可查看最近动态。"
              onRetry={() => void loadInsights()}
            />
          ) : insights.data && insights.data.recent_items.length > 0 ? (
            <div className="workbench-recent-list">
              {insights.data.recent_items.map((item) => (
                <div key={item.asset_id}>
                  <span className="workbench-activity-status">{item.status}</span>
                  <span className="workbench-activity-copy">
                    {insights.data?.title_visible && item.title ? (
                      <Link to={`/knowledge/${item.asset_id}`}>{item.title}</Link>
                    ) : (
                      <strong>业务标题已隐藏</strong>
                    )}
                    {item.message && <span>{item.message}</span>}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="暂无最近动态" description="当前运营窗口内没有可展示的活动记录。" />
          )}
        </WorkbenchSection>
      </div>

      <nav className="workbench-secondary-actions" aria-label="更多工作入口">
        {can.viewMyKnowledge(capabilities) && (
          <Link to="/my/knowledge">
            <UserRound size={16} aria-hidden="true" /> 个人知识
          </Link>
        )}
        {can.viewReview(capabilities) && (
          <Link to="/review">
            <ShieldCheck size={16} aria-hidden="true" /> 升级审核
          </Link>
        )}
        {can.viewOriginalAccess(capabilities) && (
          <Link to="/original-access">
            <KeyRound size={16} aria-hidden="true" /> 原文访问
          </Link>
        )}
        {can.viewIngestAdmin(capabilities) && (
          <Link to="/admin/ingest">
            <AlertTriangle size={16} aria-hidden="true" /> 入库管理
          </Link>
        )}
      </nav>
    </ProductPage>
  );
}
