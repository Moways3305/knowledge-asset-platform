import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowRight, CheckCircle2, Clock3, RefreshCw } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { can } from "../auth/permissions";
import TaskCenterDrawer, { type TaskCenterGroup } from "../components/TaskCenterDrawer";
import { taskStatusLabel, taskTypeLabel } from "../components/taskCenterLabels";
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

function progressLabel(item: WorkbenchTaskItemDTO): string {
  if (item.progress_total !== null) {
    const handled = (item.progress_success ?? 0) + (item.progress_failed ?? 0);
    return `${handled}/${item.progress_total}`;
  }
  return taskStatusLabel(item.status);
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
  const rightLabel =
    group === "recent_completed"
      ? `${taskStatusLabel(item.status)} · ${formatBeijingTime(item.updated_at)}`
      : waitLabel(item.waiting_minutes) || taskStatusLabel(item.status);
  return (
    <button
      type="button"
      className={`workbench-task-row is-${item.status}`}
      onClick={() => onOpen(group, item.task_ref)}
    >
      <span className="workbench-task-rail" aria-hidden="true" />
      <span className="workbench-task-copy">
        <span className="workbench-task-title">
          <strong>{item.object_name}</strong>
          <span>{taskTypeLabel(item.task_type)}</span>
        </span>
        <small>
          {item.project_name || item.responsibility} · {item.next_action_label}
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
  kind: "tasks" | "running" | "completed" | "recent";
  onRetry: () => void;
  emptyAction?: ReactNode;
}) {
  if (status === "loading")
    return <div className="workbench-state is-loading">正在同步工作状态…</div>;
  if (status === "error") {
    return (
      <div className="workbench-state is-error" role="alert">
        <span>工作状态暂时无法加载</span>
        <button type="button" onClick={onRetry}>
          重新加载
        </button>
      </div>
    );
  }
  if (status === "forbidden")
    return <div className="workbench-state">当前身份没有可显示的工作事项</div>;
  const copy = {
    tasks: "当前没有需要你处理的事项",
    running: "当前没有进行中的作业",
    completed: "今天还没有已完成的事项",
    recent: "当前没有最近更新的内容",
  }[kind];
  return (
    <div className="workbench-state is-empty">
      <span>{copy}</span>
      {emptyAction}
    </div>
  );
}

export default function HomeDashboardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { capabilities } = useAuth();
  const { overview, state, refresh } = useWorkbench();
  const [activeTab, setActiveTab] = useState<WorkTab>("my_tasks");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerGroup, setDrawerGroup] = useState<TaskCenterGroup>("my_tasks");
  const [drawerTaskRef, setDrawerTaskRef] = useState<string | null>(null);

  const taskCenterStatus: UiSectionStatus =
    overview?.task_center.status ?? (state === "loading" ? "loading" : "error");
  const recentStatus: UiSectionStatus =
    overview?.recent_activity.status ?? (state === "loading" ? "loading" : "error");
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
  const needsActionCount = center?.summary.needs_action ?? actionableItems.length;

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
      if (!drawerOpen) setDrawerTaskRef(null);
      setDrawerOpen(true);
    }
  }, [drawerOpen, searchParams]);

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
      <header className="workbench-heading">
        <div>
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
          onClick={() => void refresh()}
        >
          <RefreshCw size={15} aria-hidden="true" />
          刷新
        </button>
      </header>

      <div className="workbench-layout">
        <main className="workbench-primary" aria-labelledby="workbench-list-title">
          <div className="workbench-section-heading">
            <div>
              <span>今日任务</span>
              <h2 id="workbench-list-title">按下一步行动排列</h2>
            </div>
          </div>
          <div className="workbench-tabs" role="tablist" aria-label="我的工作分组">
            {WORK_TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.key}
                className={activeTab === tab.key ? "is-active" : ""}
                onClick={() => setActiveTab(tab.key)}
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
          <div className="workbench-task-list" role="tabpanel" aria-live="polite">
            {taskCenterStatus === "available" && activeItems.length > 0 ? (
              activeItems.map((item) => (
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
                onRetry={() => void refresh()}
                emptyAction={activeTab === "my_tasks" ? emptyAction : undefined}
              />
            )}
          </div>
        </main>

        <aside className="workbench-aside" aria-label="工作摘要">
          <section>
            <div className="workbench-aside-heading">
              <h2>进行中的作业</h2>
              <button type="button" onClick={() => openTask("running_jobs")}>
                查看全部
              </button>
            </div>
            {groups.running_jobs.length > 0 ? (
              <div className="workbench-compact-list">
                {groups.running_jobs.slice(0, 3).map((item) => (
                  <button
                    key={item.task_ref}
                    type="button"
                    onClick={() => openTask("running_jobs", item.task_ref)}
                  >
                    <span>
                      <strong>{item.object_name}</strong>
                      <small>{item.next_action_label}</small>
                    </span>
                    <em>{progressLabel(item)}</em>
                  </button>
                ))}
              </div>
            ) : (
              <SectionState
                status={taskCenterStatus === "available" ? "empty" : taskCenterStatus}
                kind="running"
                onRetry={() => void refresh()}
              />
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
          </section>

          <section>
            <div className="workbench-aside-heading">
              <h2>最近完成</h2>
              <button type="button" onClick={() => openTask("recent_completed")}>
                查看全部
              </button>
            </div>
            {groups.recent_completed.length > 0 ? (
              <div className="workbench-compact-list is-completed">
                {groups.recent_completed.slice(0, 3).map((item) => (
                  <button
                    key={item.task_ref}
                    type="button"
                    onClick={() => openTask("recent_completed", item.task_ref)}
                  >
                    <CheckCircle2 size={16} aria-hidden="true" />
                    <span>
                      <strong>{item.object_name}</strong>
                      <small>{item.result_summary || taskStatusLabel(item.status)}</small>
                    </span>
                    <time>{formatBeijingTime(item.updated_at)}</time>
                  </button>
                ))}
              </div>
            ) : (
              <SectionState
                status={taskCenterStatus === "available" ? "empty" : taskCenterStatus}
                kind="completed"
                onRetry={() => void refresh()}
              />
            )}
          </section>
        </aside>
      </div>

      <section className="workbench-recent" aria-labelledby="workbench-recent-title">
        <div className="workbench-section-heading">
          <div>
            <span>近期变化</span>
            <h2 id="workbench-recent-title">最近更新</h2>
          </div>
        </div>
        {visibleRecentStatus === "available" && overview!.recent_activity.items.length > 0 ? (
          <div className="workbench-recent-list">
            {overview!.recent_activity.items.slice(0, 3).map((item) => (
              <Link key={item.asset_id} to={`/knowledge/${encodeURIComponent(item.asset_id)}`}>
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
            onRetry={() => void refresh()}
          />
        )}
      </section>

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
