import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowRight, Clock3, FolderKanban, Plus, RefreshCw } from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { can } from "../auth/permissions";
import CreateProjectModal from "../components/CreateProjectModal";
import TaskCenterDrawer, { type TaskCenterGroup } from "../components/TaskCenterDrawer";
import { taskStatusLabel, taskTypeLabel } from "../components/taskCenterLabels";
import WorkbuddyStatusPanel from "../components/WorkbuddyStatusPanel";
import { ProductPage } from "../components/ProductLayout";
import type { WorkbenchSectionStatus, WorkbenchTaskItemDTO } from "../types/workbench";
import { formatBeijingTime } from "../utils/time";
import { useWorkbench } from "../workbench/WorkbenchContext";
import "./HomeDashboardPage.css";

type WorkTab = "my_tasks" | "running_jobs" | "recent_completed";
type UiSectionStatus = WorkbenchSectionStatus | "loading";

const WORK_TABS: Array<{ key: WorkTab; label: string }> = [
  { key: "my_tasks", label: "待处理" },
  { key: "running_jobs", label: "进行中" },
  { key: "recent_completed", label: "已完成" },
];

function todayLabel(): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(new Date());
}

function waitLabel(minutes: number | null): string | null {
  if (minutes === null) return null;
  if (minutes < 60) return `等待 ${Math.max(1, minutes)} 分钟`;
  if (minutes < 24 * 60) return `等待 ${Math.floor(minutes / 60)} 小时`;
  return `等待 ${Math.floor(minutes / (24 * 60))} 天`;
}

function taskMaterialClass(taskType: string): string {
  if (taskType === "review" || taskType.includes("original")) return "material-review";
  if (taskType === "ingest" || taskType === "parsing" || taskType === "markdown_backfill")
    return "material-source";
  if (taskType.includes("archive") || taskType.includes("reuse") || taskType.includes("migration"))
    return "material-project";
  return "material-summary";
}

function recentMaterialClass(
  assetType: string,
  accessMode: "member" | "summary_visible" | null,
): string {
  if (accessMode === "summary_visible") return "material-summary";
  if (assetType.includes("summary")) return "material-summary";
  if (assetType.includes("review")) return "material-review";
  return "material-source";
}

function TaskRow({
  item,
  group,
  onOpen,
}: {
  item: WorkbenchTaskItemDTO;
  group: WorkTab;
  onOpen: (group: TaskCenterGroup, taskRef: string) => void;
}) {
  const handled =
    item.progress_total === null
      ? null
      : (item.progress_success ?? 0) + (item.progress_failed ?? 0);
  const rightLabel =
    group === "recent_completed"
      ? `${taskStatusLabel(item.status)} · ${formatBeijingTime(item.updated_at)}`
      : group === "running_jobs" && handled !== null
        ? `${taskStatusLabel(item.status)} · ${handled}/${item.progress_total}`
        : waitLabel(item.waiting_minutes) || taskStatusLabel(item.status);
  return (
    <button
      type="button"
      className={`workbench-task-row is-${item.status} ${taskMaterialClass(item.task_type)}`}
      onClick={() => onOpen(group, item.task_ref)}
    >
      <span className="workbench-task-rail" aria-hidden="true" />
      <span className="workbench-task-copy">
        <span className="workbench-task-title">
          <strong>{item.object_name}</strong>
          <span>{taskTypeLabel(item.task_type)}</span>
        </span>
      </span>
      <span className="workbench-task-context">
        <strong>{item.project_name || item.responsibility}</strong>
        <small>
          {group === "recent_completed" && item.result_summary
            ? item.result_summary
            : item.next_action_label}
        </small>
      </span>
      <span className="workbench-task-state">{rightLabel}</span>
      <ArrowRight size={16} aria-hidden="true" />
    </button>
  );
}

function SectionState({
  status,
  kind,
  onRetry,
  emptyAction,
}: {
  status: UiSectionStatus;
  kind: "tasks" | "running" | "completed" | "recent" | "projects";
  onRetry: () => void;
  emptyAction?: ReactNode;
}) {
  if (status === "loading")
    return <div className="workbench-state is-loading">正在同步工作状态…</div>;
  if (status === "error")
    return (
      <div className="workbench-state is-error" role="alert">
        <span>工作状态暂时无法加载</span>
        <button type="button" onClick={onRetry}>
          重新加载
        </button>
      </div>
    );
  if (status === "forbidden")
    return <div className="workbench-state">当前身份没有可显示的工作事项</div>;
  const copy = {
    tasks: "当前没有需要你处理的事项",
    running: "当前没有进行中的作业",
    completed: "今天还没有已完成的事项",
    recent: "当前没有最近更新的内容",
    projects: "暂无可访问项目",
  }[kind];
  return (
    <div className="workbench-state is-empty">
      <span>{copy}</span>
      {emptyAction}
    </div>
  );
}

export default function HomeDashboardPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { capabilities, authMe } = useAuth();
  const { overview, state, refresh } = useWorkbench();
  const [activeTab, setActiveTab] = useState<WorkTab>("my_tasks");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerGroup, setDrawerGroup] = useState<TaskCenterGroup>("my_tasks");
  const [drawerTaskRef, setDrawerTaskRef] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [refractVersion, setRefractVersion] = useState(0);
  const [taskPage, setTaskPage] = useState(0);

  const taskCenterStatus: UiSectionStatus =
    overview?.task_center.status ?? (state === "loading" ? "loading" : "error");
  const recentStatus: UiSectionStatus =
    overview?.recent_activity.status ?? (state === "loading" ? "loading" : "error");
  const projectsStatus: UiSectionStatus =
    overview?.projects.status ?? (state === "loading" ? "loading" : "error");
  const center = overview?.task_center;
  const groups = useMemo(
    () => ({
      my_tasks: center?.my_tasks ?? [],
      running_jobs: center?.running_jobs ?? [],
      attention_items: center?.attention_items ?? [],
      recent_completed: center?.recent_completed ?? [],
    }),
    [center],
  );
  const actionableItems = useMemo(
    () =>
      groups.my_tasks.filter(
        (item) =>
          (item.status === "needs_action" || item.status === "failed") && item.next_action_key,
      ),
    [groups.my_tasks],
  );
  const activeItems = activeTab === "my_tasks" ? actionableItems : groups[activeTab];
  // The dashboard is an orientation surface, not a second task center. Keep the
  // first view deliberately short while leaving the complete, deep-linkable list
  // in TaskCenterDrawer.
  const dashboardTaskLimit = 6;
  const taskPageCount = Math.max(1, Math.ceil(activeItems.length / dashboardTaskLimit));
  const safeTaskPage = Math.min(taskPage, taskPageCount - 1);
  const visibleTaskItems = activeItems.slice(
    safeTaskPage * dashboardTaskLimit,
    (safeTaskPage + 1) * dashboardTaskLimit,
  );
  const needsActionCount = center?.summary.needs_action ?? actionableItems.length;
  const focusItem = actionableItems[0] ?? null;

  useEffect(() => {
    setTaskPage((page) => Math.min(page, taskPageCount - 1));
  }, [taskPageCount]);

  const handleRefresh = () => {
    setRefractVersion((version) => version + 1);
    void refresh();
  };

  const selectTab = (tab: WorkTab) => {
    setActiveTab(tab);
    setTaskPage(0);
  };

  const openTask = (group: TaskCenterGroup, taskRef: string | null = null) => {
    setDrawerGroup(group);
    setDrawerTaskRef(taskRef);
    setDrawerOpen(true);
    const next = new URLSearchParams(searchParams);
    next.set("task_group", group);
    setSearchParams(next, { replace: true });
  };

  useEffect(() => {
    const requested = searchParams.get("task_group");
    if (
      requested === "my_tasks" ||
      requested === "running_jobs" ||
      requested === "attention_items" ||
      requested === "recent_completed"
    ) {
      setDrawerGroup(requested);
      setDrawerTaskRef(null);
      setDrawerOpen(true);
    }
  }, [searchParams]);

  const closeDrawer = () => {
    setDrawerOpen(false);
    setDrawerTaskRef(null);
    if (searchParams.has("task_group")) {
      const next = new URLSearchParams(searchParams);
      next.delete("task_group");
      setSearchParams(next, { replace: true });
    }
  };

  const emptyAction = can.viewUpload(capabilities) ? (
    <Link to="/upload">上传资料</Link>
  ) : can.viewKnowledge(capabilities) ? (
    <Link to="/knowledge">浏览知识</Link>
  ) : undefined;
  const canOpenKnowledge = can.viewKnowledge(capabilities);
  const visibleRecentStatus: UiSectionStatus = canOpenKnowledge ? recentStatus : "forbidden";
  const canShowRecentTitles =
    canOpenKnowledge &&
    overview?.operations.status === "available" &&
    overview.operations.data?.title_visible === true;

  return (
    <ProductPage className="task-first-workbench">
      <div className="workbench-scene-shell">
        <span key={refractVersion} className="workbench-light-sweep" aria-hidden="true" />
        <header className="workbench-heading">
          <div className="workbench-heading-copy">
            <span>{todayLabel()}</span>
            <h1>我的工作</h1>
            <p aria-live="polite">
              {state === "loading"
                ? "正在同步需要你处理的事项"
                : state === "error"
                  ? "工作状态需要重新加载"
                  : needsActionCount > 0
                    ? `${needsActionCount} 项需要你处理`
                    : "当前没有需要你处理的事项"}
            </p>
          </div>
          <button
            type="button"
            className="workbench-refresh"
            disabled={state === "loading"}
            onClick={handleRefresh}
          >
            <RefreshCw size={15} aria-hidden="true" />
            刷新
          </button>
        </header>

        <div className="workbench-layout">
          <div className="workbench-environment" aria-hidden="true">
            <i />
            <i />
            <i />
          </div>
          <main className="workbench-primary" aria-labelledby="workbench-list-title">
            <div className="workbench-section-heading">
              <div>
                <span>今日任务</span>
                <h2 id="workbench-list-title">按下一步行动排列</h2>
              </div>
            </div>
            {taskCenterStatus === "available" && focusItem ? (
              <button
                type="button"
                className={`workbench-focus is-${focusItem.status} ${taskMaterialClass(focusItem.task_type)}`}
                aria-label="打开今日焦点任务"
                onClick={() => openTask("my_tasks", focusItem.task_ref)}
              >
                <span className="workbench-focus-prism" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </span>
                <span className="workbench-focus-copy">
                  <small>优先处理</small>
                  <strong>{`今日焦点 · ${focusItem.object_name}`}</strong>
                  <span>
                    {focusItem.project_name || focusItem.responsibility} ·{" "}
                    {focusItem.next_action_label}
                  </span>
                </span>
                <span className="workbench-focus-action">
                  {waitLabel(focusItem.waiting_minutes) || taskStatusLabel(focusItem.status)}
                  <ArrowRight size={17} aria-hidden="true" />
                </span>
              </button>
            ) : (
              <div
                className={`workbench-focus ${taskCenterStatus === "available" ? "is-empty" : `is-${taskCenterStatus}`}`}
              >
                <span className="workbench-focus-prism" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </span>
                <span className="workbench-focus-copy">
                  <small>今日焦点</small>
                  <strong>
                    {taskCenterStatus === "loading"
                      ? "正在确定优先事项"
                      : taskCenterStatus === "error"
                        ? "焦点暂时无法加载"
                        : "工作台已清空"}
                  </strong>
                  <span>
                    {taskCenterStatus === "available"
                      ? "可以开始整理下一份知识资产"
                      : "任务列表仍可在下方查看和恢复"}
                  </span>
                </span>
              </div>
            )}
            <div className="workbench-tabs" role="tablist" aria-label="我的工作分组">
              {WORK_TABS.map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab.key}
                  className={activeTab === tab.key ? "is-active" : ""}
                  onClick={() => selectTab(tab.key)}
                >
                  {tab.label}
                  {tab.key !== "recent_completed" && (
                    <span>
                      {tab.key === "my_tasks" ? actionableItems.length : groups[tab.key].length}
                    </span>
                  )}
                </button>
              ))}
            </div>
            <div className="workbench-task-columns" aria-hidden="true">
              <span>任务对象 / 类型</span>
              <span>项目或范围 / 下一步</span>
              <span>等待时长 / 状态</span>
              <span />
            </div>
            <div className="workbench-task-list" role="tabpanel" aria-live="polite">
              {taskCenterStatus === "available" && activeItems.length > 0 ? (
                visibleTaskItems.map((item) => (
                  <TaskRow key={item.task_ref} item={item} group={activeTab} onOpen={openTask} />
                ))
              ) : (
                <SectionState
                  status={taskCenterStatus === "available" ? "empty" : taskCenterStatus}
                  kind={
                    activeTab === "my_tasks"
                      ? "tasks"
                      : activeTab === "running_jobs"
                        ? "running"
                        : "completed"
                  }
                  onRetry={handleRefresh}
                  emptyAction={activeTab === "my_tasks" ? emptyAction : undefined}
                />
              )}
            </div>
            {taskCenterStatus === "available" && activeItems.length > dashboardTaskLimit && (
              <div className="workbench-task-pager" aria-label="任务列表分页">
                <span>
                  显示 {safeTaskPage * dashboardTaskLimit + 1}–
                  {Math.min((safeTaskPage + 1) * dashboardTaskLimit, activeItems.length)} /{" "}
                  {activeItems.length}
                </span>
                <div>
                  <button
                    type="button"
                    disabled={safeTaskPage === 0}
                    onClick={() => setTaskPage(Math.max(0, safeTaskPage - 1))}
                  >
                    上一页
                  </button>
                  <button
                    type="button"
                    disabled={safeTaskPage >= taskPageCount - 1}
                    onClick={() => setTaskPage(Math.min(taskPageCount - 1, safeTaskPage + 1))}
                  >
                    下一页
                  </button>
                  <button type="button" onClick={() => openTask(activeTab)}>
                    查看全部
                  </button>
                </div>
              </div>
            )}
            {groups.attention_items.length > 0 && (
              <button
                type="button"
                className="workbench-attention-link"
                onClick={() => openTask("attention_items")}
              >
                另有 {groups.attention_items.length} 项需要关注
                <ArrowRight size={14} aria-hidden="true" />
              </button>
            )}
            <div className="workbench-rhythm" aria-label="今日工作节奏">
              {WORK_TABS.map((tab) => {
                const count =
                  tab.key === "my_tasks" ? actionableItems.length : groups[tab.key].length;
                return (
                  <button
                    key={tab.key}
                    type="button"
                    className={`${activeTab === tab.key ? "is-active " : ""}is-${tab.key}`}
                    aria-pressed={activeTab === tab.key}
                    onClick={() => selectTab(tab.key)}
                  >
                    <span>
                      <small>{tab.label}</small>
                      <strong>{count}</strong>
                    </span>
                    <i className="workbench-rhythm-meter" aria-hidden="true">
                      {Array.from({ length: 6 }, (_, index) => (
                        <b key={index} className={index < Math.min(count, 6) ? "is-filled" : ""} />
                      ))}
                    </i>
                  </button>
                );
              })}
            </div>
          </main>

          <aside className="workbench-context" aria-label="工作上下文">
            <section className="workbench-projects" aria-labelledby="workbench-projects-title">
              <div className="workbench-context-heading">
                <div>
                  <FolderKanban size={17} aria-hidden="true" />
                  <h2 id="workbench-projects-title">我的项目</h2>
                </div>
                {capabilities.isGovernance && (
                  <div className="workbench-create-wrap">
                    <span>仅治理角色可见</span>
                    <button type="button" onClick={() => setCreateOpen(true)}>
                      <Plus size={14} aria-hidden="true" />
                      新建项目
                    </button>
                  </div>
                )}
              </div>
              {projectsStatus === "available" && overview!.projects.items.length > 0 ? (
                <div className="workbench-project-list">
                  {overview!.projects.items.map((project) => (
                    <Link
                      key={project.project_id}
                      className={
                        project.access_mode === "member" ? "material-project" : "material-summary"
                      }
                      to={
                        project.access_mode === "member"
                          ? `/project/${encodeURIComponent(project.project_id)}`
                          : `/knowledge?scope=project&project_id=${encodeURIComponent(project.project_id)}`
                      }
                    >
                      <span>
                        <strong>{project.name}</strong>
                        <small>{project.access_label}</small>
                      </span>
                      <ArrowRight size={15} aria-hidden="true" />
                    </Link>
                  ))}
                </div>
              ) : (
                <SectionState
                  status={projectsStatus === "available" ? "empty" : projectsStatus}
                  kind="projects"
                  onRetry={handleRefresh}
                  emptyAction={
                    !capabilities.isGovernance && authMe?.projects[0] ? (
                      <Link to={`/project/${encodeURIComponent(authMe.projects[0].projectId)}`}>
                        进入项目空间
                      </Link>
                    ) : undefined
                  }
                />
              )}
            </section>
            {capabilities.isBusinessUser && <WorkbuddyStatusPanel />}
          </aside>

          <section className="workbench-recent" aria-labelledby="workbench-recent-title">
            <div className="workbench-section-heading">
              <div>
                <span>近期变化</span>
                <h2 id="workbench-recent-title">最近动态</h2>
              </div>
            </div>
            {visibleRecentStatus === "available" && overview!.recent_activity.items.length > 0 ? (
              <div className="workbench-recent-list">
                {overview!.recent_activity.items.slice(0, 3).map((item) => (
                  <Link
                    key={item.asset_id}
                    className={recentMaterialClass(item.asset_type, item.access_mode)}
                    to={`/knowledge/${encodeURIComponent(item.asset_id)}`}
                  >
                    <span>
                      <strong>{canShowRecentTitles ? item.title : "业务标题已隐藏"}</strong>
                      <small>{item.project_name || "个人知识"}</small>
                    </span>
                    <time>
                      <Clock3 size={13} aria-hidden="true" />
                      {formatBeijingTime(item.updated_at)}
                    </time>
                    <ArrowRight size={15} aria-hidden="true" />
                  </Link>
                ))}
              </div>
            ) : (
              <SectionState
                status={visibleRecentStatus === "available" ? "empty" : visibleRecentStatus}
                kind="recent"
                onRetry={handleRefresh}
              />
            )}
          </section>
        </div>
      </div>

      <CreateProjectModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={async (created) => {
          setCreateOpen(false);
          await refresh();
          navigate(`/project/${created.id}`);
        }}
      />
      <TaskCenterDrawer
        open={drawerOpen}
        initialGroup={drawerGroup}
        initialTaskRef={drawerTaskRef}
        groups={groups}
        onClose={closeDrawer}
      />
    </ProductPage>
  );
}
