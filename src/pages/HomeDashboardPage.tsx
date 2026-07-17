import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  BriefcaseBusiness,
  FolderKanban,
  LibraryBig,
  ListChecks,
  RefreshCw,
  UploadCloud,
} from "lucide-react";
import { fetchWorkbenchOverview } from "../api/workbench";
import { useAuth } from "../auth/AuthContext";
import { can } from "../auth/permissions";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import type {
  WorkbenchOperationCardDTO,
  WorkbenchOverviewDTO,
  WorkbenchSectionStatus,
  WorkbenchTodoItemDTO,
} from "../types/workbench";
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

type PageState = "loading" | "ready" | "error";
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
  className = "",
  children,
}: {
  title: string;
  icon: ReactNode;
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
}: {
  status: UiSectionStatus;
  emptyText: string;
  loadingText: string;
  onRetry: () => void;
  emptyAction?: ReactNode;
}) {
  if (status === "loading") {
    return <div className="wb81-section-state is-loading">{loadingText}</div>;
  }
  if (status === "forbidden") {
    return <div className="wb81-section-state">当前身份暂无访问权限</div>;
  }
  if (status === "error") {
    return (
      <div className="wb81-section-state is-error" role="alert">
        <span>内容暂时未能加载</span>
        <button type="button" onClick={onRetry}>
          重新加载
        </button>
      </div>
    );
  }
  return (
    <div className="wb81-section-state is-empty">
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

function OperationCard({ item }: { item: WorkbenchOperationCardDTO }) {
  return (
    <div className={`wb81-operation ${safeTone(item.severity)}`}>
      <span>{OPERATION_LABEL[item.key] ?? SAFE_FALLBACK}</span>
      <strong>{item.count}</strong>
    </div>
  );
}

export default function HomeDashboardPage() {
  const { authMe, capabilities } = useAuth();
  const [overview, setOverview] = useState<WorkbenchOverviewDTO | null>(null);
  const [pageState, setPageState] = useState<PageState>("loading");
  const requestRef = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++requestRef.current;
    setPageState("loading");
    try {
      const next = await fetchWorkbenchOverview();
      if (requestId !== requestRef.current) return;
      setOverview(next);
      setPageState("ready");
    } catch {
      if (requestId !== requestRef.current) return;
      setOverview(null);
      setPageState("error");
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      requestRef.current += 1;
    };
  }, [load]);

  const fallbackStatus: UiSectionStatus = pageState === "loading" ? "loading" : "error";
  const todosStatus = overview?.todos.status ?? fallbackStatus;
  const operationsStatus = overview?.operations.status ?? fallbackStatus;
  const projectsStatus = overview?.projects.status ?? fallbackStatus;
  const recentStatus = overview?.recent_activity.status ?? fallbackStatus;
  const todoItems = overview?.todos.items.filter((item) => item.count > 0) ?? [];
  const operationCards = overview?.operations.data?.cards ?? [];
  const canShowAssetTitles =
    overview?.operations.status === "available" && overview.operations.data?.title_visible === true;

  const roleText =
    authMe?.companyRoles.map((role) => COMPANY_ROLE[role] ?? SAFE_FALLBACK).join(" / ") ||
    SAFE_FALLBACK;

  return (
    <ProductPage className="today-workbench wb81-workbench">
      <PageHeader
        eyebrow="今日工作台"
        title={
          <>
            今日工作台 <span className="wb81-user-name">{authMe?.name?.trim() || "同事"}</span>
          </>
        }
        description={`当前身份：${roleText}`}
        actions={
          <div className="wb81-header-actions">
            <time className="wb81-date">{todayLabel()}</time>
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

      <div className="wb81-grid">
        <WorkbenchPanel title="我的待办" icon={<ListChecks size={17} />} className="is-todos">
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
          className="is-operations"
        >
          {operationsStatus === "available" && operationCards.length > 0 ? (
            <div className="wb81-operation-grid">
              {operationCards.map((item, index) => (
                <OperationCard key={`${item.key}-${index}`} item={item} />
              ))}
            </div>
          ) : (
            <SectionMessage
              status={operationsStatus === "available" ? "empty" : operationsStatus}
              loadingText="正在加载资产运行状态…"
              emptyText="当前没有需要处理的运营事项"
              onRetry={() => void load()}
            />
          )}
        </WorkbenchPanel>

        <WorkbenchPanel title="协作空间" icon={<FolderKanban size={17} />} className="is-projects">
          {projectsStatus === "available" && overview && overview.projects.items.length > 0 ? (
            <div className="wb81-project-list">
              {overview.projects.items.map((project) => (
                <Link
                  key={project.project_id}
                  to={`/project/${encodeURIComponent(project.project_id)}`}
                >
                  <span className="wb81-project-mark" aria-hidden="true">
                    {project.name.trim().slice(0, 1) || "项"}
                  </span>
                  <span className="wb81-project-copy">
                    <strong>{project.name.trim() || "待确认项目"}</strong>
                    <small>
                      {PROJECT_ROLE[project.project_role] ?? SAFE_FALLBACK} ·{" "}
                      {PROJECT_STATUS[project.status] ?? SAFE_FALLBACK}
                    </small>
                  </span>
                  <ArrowRight size={15} aria-hidden="true" />
                </Link>
              ))}
            </div>
          ) : (
            <SectionMessage
              status={projectsStatus === "available" ? "empty" : projectsStatus}
              loadingText="正在加载协作空间…"
              emptyText="当前没有可访问的项目"
              onRetry={() => void load()}
            />
          )}
        </WorkbenchPanel>

        <WorkbenchPanel title="最近动态" icon={<LibraryBig size={17} />} className="is-recent">
          {recentStatus === "available" && overview && overview.recent_activity.items.length > 0 ? (
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
    </ProductPage>
  );
}
