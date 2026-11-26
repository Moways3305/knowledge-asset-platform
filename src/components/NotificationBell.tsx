import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, BellOff, CheckCheck, RefreshCw, Settings2, Trash2 } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { readKnowledgeDetailSource } from "../routing/knowledgeDetailSource";
import {
  actOnInbox,
  fetchInbox,
  type InboxAction,
  type InboxActionName,
  type InboxFilter,
  type InboxResponse,
  type InboxView,
  type NotificationGroup,
} from "../api/notificationInbox";
import type { BusinessNotificationDTO } from "../types/notification";
import { TASK_STATUS_INVALIDATED_EVENT } from "../workbench/taskStatusEvents";
import { formatBeijingTime } from "../utils/time";
import DetailDrawer from "./DetailDrawer";
import {
  NotificationEvents,
  NotificationSettings,
  CATEGORY_LABEL,
} from "./NotificationInboxPanels";
import "./NotificationBell.css";

const ROUTES: Record<string, string> = {
  maintenance_agent: "/agents/knowledge-maintenance",
  reviews: "/review",
  original_access: "/original-access",
  upload: "/upload",
  admin_ingest: "/admin/ingest",
  models: "/admin/weknora-models",
  knowledge_detail: "/knowledge/:id",
};
const VIEWS: [InboxView, string][] = [
  ["inbox", "收件箱"],
  ["unread", "未读"],
  ["archived", "已归档"],
  ["trash", "回收站"],
];
const ACTIONS: Partial<Record<InboxActionName, string>> = {
  read: "标为已读",
  unread: "标为未读",
  archive: "归档",
  delete: "删除",
  restore: "恢复到收件箱",
};

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [filters, setFilters] = useState<InboxFilter>({ view: "inbox" });
  const [data, setData] = useState<InboxResponse>();
  const [items, setItems] = useState<NotificationGroup[]>([]);
  const [unseen, setUnseen] = useState(0);
  const [unread, setUnread] = useState(0);
  const [busy, setBusy] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [all, setAll] = useState(false);
  const [expanded, setExpanded] = useState<string>();
  const [settings, setSettings] = useState(false);
  const [cleanup, setCleanup] = useState(false);
  const [cleanupDate, setCleanupDate] = useState("");
  const [cleanupSnapshot, setCleanupSnapshot] = useState<string>();
  const [confirmation, setConfirmation] = useState<InboxAction>();
  const snapshot = useRef<string>();
  const pages = useRef(1);
  const opened = useRef(false);
  const request = useRef(0);
  const controller = useRef<AbortController>();
  const mutationLock = useRef(false);
  const queuedRefresh = useRef(false);
  const navigate = useNavigate();
  const location = useLocation();
  opened.current = open;

  const load = useCallback(
    async (quiet = false, see = false, append = false) => {
      if (quiet && controller.current) {
        queuedRefresh.current = true;
        return;
      }
      controller.current?.abort();
      const abort = new AbortController();
      controller.current = abort;
      const seq = ++request.current;
      const timeout = window.setTimeout(() => abort.abort(), 30_000);
      if (!quiet) setBusy(true);
      try {
        const fresh = await fetchInbox(filters, 1, undefined, abort.signal);
        const pinned = (quiet && opened.current) || append;
        const at = pinned ? (snapshot.current ?? fresh.snapshot_at) : fresh.snapshot_at;
        let result =
          at === fresh.snapshot_at ? fresh : await fetchInbox(filters, 1, at, abort.signal);
        const loaded = [...result.items];
        for (let page = 2; page <= pages.current && loaded.length < result.total; page++) {
          result = await fetchInbox(filters, page, at, abort.signal);
          loaded.push(...result.items);
        }
        if (seq !== request.current || abort.signal.aborted) return;
        snapshot.current = at;
        setData({
          ...result,
          snapshot_at: at,
          projects: fresh.projects,
          categories: fresh.categories,
        });
        setItems((current) =>
          pinned
            ? [
                ...current.flatMap((old) => {
                  const next = loaded.find((row) => row.id === old.id);
                  return next ? [next] : [];
                }),
                ...loaded.filter((row) => !current.some((old) => old.id === row.id)),
              ]
            : loaded,
        );
        setExpanded((current) => (loaded.some((row) => row.id === current) ? current : undefined));
        setSelected((current) => current.filter((id) => loaded.some((row) => row.id === id)));
        setUnseen(fresh.unseen_count);
        setUnread(fresh.unread_count);
        setError("");
        if (see) {
          await actOnInbox({
            action: "seen",
            all_matching: true,
            filters: { view: "inbox" },
            snapshot_at: fresh.snapshot_at,
          });
          if (seq === request.current) setUnseen(0);
        }
      } catch {
        if (seq === request.current) setError("通知状态暂未同步，请重试。当前内容与选择已保留。");
      } finally {
        window.clearTimeout(timeout);
        if (seq === request.current) setBusy(false);
        if (controller.current === abort) {
          controller.current = undefined;
          if (queuedRefresh.current) {
            queuedRefresh.current = false;
            void load(true);
          }
        }
      }
    },
    [filters],
  );

  useEffect(() => {
    pages.current = 1;
    snapshot.current = undefined;
    setSelected([]);
    setAll(false);
    setExpanded(undefined);
    setItems([]);
    void load();
    const refresh = () => {
      if (document.visibilityState === "visible" && !mutationLock.current) void load(true);
    };
    const timer = window.setInterval(refresh, 60_000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener(TASK_STATUS_INVALIDATED_EVENT, refresh);
    return () => {
      // This numeric generation deliberately invalidates all outstanding requests.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      request.current++;
      queuedRefresh.current = false;
      controller.current?.abort();
      controller.current = undefined;
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener(TASK_STATUS_INVALIDATED_EVENT, refresh);
    };
  }, [load]);

  const mutate = async (body: InboxAction) => {
    if (mutationLock.current) return false;
    mutationLock.current = true;
    setMutating(true);
    setError("");
    request.current++;
    controller.current?.abort();
    controller.current = undefined;
    try {
      const result = await actOnInbox(body);
      setNotice(`已${ACTIONS[body.action] ?? "更新"} ${result.affected_count} 条消息。`);
      setConfirmation(undefined);
      setCleanup(false);
      setSelected([]);
      setAll(false);
      await load(true);
      return true;
    } catch {
      setError("操作未能确认，请重试。重试不会重复删除，也不会改变业务任务。");
      return false;
    } finally {
      mutationLock.current = false;
      setMutating(false);
    }
  };
  const action = (name: InboxActionName, groups?: string[]) => {
    if (!snapshot.current) return;
    const body: InboxAction = {
      action: name,
      snapshot_at: snapshot.current,
      filters,
      ...(groups ? { group_ids: groups } : all ? { all_matching: true } : { group_ids: selected }),
    };
    if (name === "delete") setConfirmation(body);
    else void mutate(body);
  };
  const openItem = async (item: BusinessNotificationDTO, group: NotificationGroup) => {
    if (!ROUTES[item.target.route_key]) {
      setError("目标页暂不可用，消息仍保留。");
      return;
    }
    if (
      !snapshot.current ||
      !(await mutate({
        action: "read",
        filters,
        snapshot_at: snapshot.current,
        group_ids: [group.id],
      }))
    )
      return;
    const routeTemplate = ROUTES[item.target.route_key];
    if (!routeTemplate) {
      setError("目标页暂不可用，通知仍保持未读。");
      return;
    }
    const route = routeTemplate.replace(":id", encodeURIComponent(item.target.resource_id));
    const query = new URLSearchParams({ target_id: item.target.resource_id });
    if (item.target.route_key === "maintenance_agent") {
      query.set("mine", "true");
      if (item.task_status === "completed") query.set("status", "all");
    }
    if (item.target.route_key === "original_access") {
      query.set("box", item.event_type === "original_access.pending" ? "inbox" : "mine");
    }
    if (
      item.target.route_key === "reviews" &&
      ["completed", "cancelled", "rejected"].includes(item.task_status)
    )
      query.set("queue", "completed");
    if (item.target.route_key === "upload") query.set("task_id", item.target.resource_id);
    const target = `${route}?${query.toString()}`;
    if (item.target.route_key === "knowledge_detail") {
      const origin = location.pathname.startsWith("/knowledge/")
        ? readKnowledgeDetailSource(location.state).backTo
        : `${location.pathname}${location.search}${location.hash}`;
      navigate(target, {
        state: { backTo: origin, backLabel: "返回上一页", source: "notification" },
      });
    } else {
      navigate(target);
    }

    setOpen(false);
  };
  const selectedCount = all ? (data?.total ?? 0) : selected.length;
  const bulkActions: InboxActionName[] =
    filters.view === "trash"
      ? ["restore"]
      : filters.view === "archived"
        ? ["restore", "delete"]
        : ["read", "unread", "archive", "delete"];

  return (
    <div className="notification-bell">
      <button
        type="button"
        className={`notification-bell-trigger ${open ? "is-open" : ""}`}
        aria-label={`通知中心，${unseen} 条新提醒，${unread} 组未读`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => {
          setOpen(true);
          setNotice("");
          void load(false, true);
        }}
      >
        <Bell size={17} aria-hidden="true" />
        {unseen > 0 && (
          <span className="notification-bell-badge" aria-hidden="true">
            {unseen > 99 ? "99+" : unseen}
          </span>
        )}
      </button>
      <DetailDrawer
        open={open}
        title="通知中心"
        className="notification-inbox-drawer"
        onClose={() => setOpen(false)}
        busy={mutating}
        description={`${unread} 组未读 · 打开仅清除新提醒角标`}
        footer={
          <span className="inbox-footnote">
            已读、归档和删除仅整理个人消息，待办仍在任务中心追踪。
          </span>
        }
      >
        <div className="inbox-tools">
          <button
            disabled={mutating || !data}
            onClick={() =>
              snapshot.current &&
              void mutate({
                action: "read",
                all_matching: true,
                filters: { view: "inbox" },
                snapshot_at: snapshot.current,
              })
            }
          >
            <CheckCheck size={15} />
            全部已读
          </button>
          <button
            disabled={mutating || !data}
            onClick={() => {
              setCleanup(true);
              setCleanupSnapshot(snapshot.current);
              setConfirmation(undefined);
            }}
          >
            <Trash2 size={15} />
            清理历史
          </button>
          <button aria-label="通知设置" onClick={() => setSettings(!settings)}>
            <Settings2 size={16} />
          </button>
          <button
            aria-label="刷新通知"
            disabled={busy || mutating}
            onClick={() => {
              setSelected([]);
              setAll(false);
              void load(false, true);
            }}
          >
            <RefreshCw size={16} />
          </button>
        </div>
        {settings && <NotificationSettings onClose={() => setSettings(false)} />}
        {error && (
          <div className="inbox-feedback is-error" role="alert">
            {error}
            <button onClick={() => void load()}>重试加载</button>
          </div>
        )}
        {notice && (
          <div className="inbox-feedback" role="status">
            {notice}
          </div>
        )}
        {cleanup && (
          <section className="inbox-confirm" aria-label="清理历史消息">
            <strong>清理历史消息</strong>
            <p>包含收件箱、归档及所有分页；移入回收站后可恢复。操作期间新到的消息会保留。</p>
            <label>
              只清理此日期之前的消息（北京时间，可留空）
              <input
                type="date"
                value={cleanupDate}
                onChange={(event) => setCleanupDate(event.target.value)}
              />
            </label>
            <div className="inbox-tools">
              <button
                disabled={mutating || !cleanupSnapshot}
                onClick={() => {
                  if (cleanupSnapshot)
                    void mutate({
                      action: "delete",
                      all_matching: true,
                      snapshot_at: cleanupSnapshot,
                      filters: {
                        view: "inbox",
                        include_archived: true,
                        ...(cleanupDate ? { before: `${cleanupDate}T00:00:00+08:00` } : {}),
                      },
                    });
                }}
              >
                确认清理{cleanupDate ? "日期之前" : "全部历史"}消息
              </button>
              <button disabled={mutating} onClick={() => setCleanup(false)}>
                取消
              </button>
            </div>
          </section>
        )}
        {confirmation && (
          <section className="inbox-confirm" aria-label="确认删除消息">
            <strong>删除所选消息？</strong>
            <p>仅移入你的回收站，可以恢复。关联业务不受影响。</p>
            <div className="inbox-tools">
              <button disabled={mutating} onClick={() => void mutate(confirmation)}>
                确认删除
              </button>
              <button disabled={mutating} onClick={() => setConfirmation(undefined)}>
                取消
              </button>
            </div>
          </section>
        )}
        <div className="inbox-tabs" role="tablist" aria-label="通知范围">
          {VIEWS.map(([view, label]) => (
            <button
              key={view}
              role="tab"
              aria-selected={filters.view === view}
              disabled={mutating}
              onClick={() => setFilters({ ...filters, view })}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="inbox-filters">
          <label>
            消息类型
            <select
              value={filters.category ?? ""}
              onChange={(e) => setFilters({ ...filters, category: e.target.value || undefined })}
            >
              <option value="">全部类型</option>
              {Object.entries(CATEGORY_LABEL).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            项目
            <select
              value={filters.project_id ?? ""}
              onChange={(e) => setFilters({ ...filters, project_id: e.target.value || undefined })}
            >
              <option value="">全部项目</option>
              {data?.projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {unseen > 0 && (
          <button
            className="inbox-new"
            onClick={() => {
              setSelected([]);
              setAll(false);
              void load(false, true);
            }}
          >
            有 {unseen} 组新提醒，点击查看
          </button>
        )}
        <div className="inbox-selection">
          <label>
            <input
              type="checkbox"
              aria-label="选择当前已加载消息"
              checked={items.length > 0 && (all || selected.length === items.length)}
              disabled={!items.length || mutating}
              onChange={(e) => {
                setAll(false);
                setSelected(e.target.checked ? items.map((row) => row.id) : []);
              }}
            />
            已选 {selectedCount} 组
          </label>
          {!all && items.length > 0 && (
            <button
              disabled={mutating}
              onClick={() => {
                setAll(true);
                setSelected([]);
              }}
            >
              选择全部 {data?.total ?? 0} 组（跨页）
            </button>
          )}
          {selectedCount > 0 && (
            <>
              <button
                disabled={mutating}
                onClick={() => {
                  setSelected([]);
                  setAll(false);
                }}
              >
                取消选择
              </button>
              {bulkActions.map((name) => (
                <button key={name} disabled={mutating} onClick={() => action(name)}>
                  {ACTIONS[name]}
                </button>
              ))}
            </>
          )}
          {filters.view !== "trash" && filters.view !== "archived" && (
            <button
              disabled={mutating || !snapshot.current}
              onClick={() =>
                snapshot.current &&
                void mutate({
                  action: "archive",
                  all_matching: true,
                  filters: { ...filters, read_only: true },
                  snapshot_at: snapshot.current,
                })
              }
            >
              归档已读（跨页）
            </button>
          )}
        </div>
        {busy && !items.length ? (
          <p role="status">正在加载通知…</p>
        ) : !items.length ? (
          <div className="inbox-empty">
            <BellOff size={28} />
            <strong>{filters.view === "trash" ? "回收站为空" : "当前范围没有消息"}</strong>
            <span>可以切换范围或调整筛选。</span>
          </div>
        ) : (
          <div className="inbox-list">
            {items.map((group) => (
              <article key={group.id} className={group.unread_count ? "is-unread" : ""}>
                <input
                  type="checkbox"
                  aria-label={`选择${group.latest.title}`}
                  checked={all || selected.includes(group.id)}
                  disabled={mutating}
                  onChange={(e) => {
                    setAll(false);
                    setSelected((current) =>
                      e.target.checked
                        ? [...current, group.id]
                        : current.filter((id) => id !== group.id),
                    );
                  }}
                />
                <div className="inbox-message">
                  <div className="inbox-meta">
                    <span>{CATEGORY_LABEL[group.latest.category] ?? "业务消息"}</span>
                    {group.action_required && <b>待处理</b>}
                    {group.failed_count > 0 && (
                      <b className="is-danger">{group.failed_count} 项异常</b>
                    )}
                    <time>{formatBeijingTime(group.latest.created_at)}</time>
                  </div>
                  <button
                    className="inbox-title"
                    aria-expanded={
                      group.latest.target.route_key === "maintenance_agent"
                        ? undefined
                        : expanded === group.id
                    }
                    onClick={() =>
                      group.latest.target.route_key === "maintenance_agent"
                        ? void openItem(group.latest, group)
                        : setExpanded(expanded === group.id ? undefined : group.id)
                    }
                  >
                    {group.id.startsWith("upload:") ? "批量入库进展" : group.latest.title}
                  </button>
                  <p className="inbox-summary">{group.latest.summary}</p>
                  <div className="inbox-row-actions">
                    <span>
                      {group.event_count > 1 ? `${group.event_count} 条更新 · ` : ""}
                      {group.unread_count ? `${group.unread_count} 条未读` : "已读"}
                    </span>
                    <button
                      onClick={() => setExpanded(expanded === group.id ? undefined : group.id)}
                    >
                      {expanded === group.id ? "收起详情" : "查看详情"}
                    </button>
                    {filters.view === "trash" || filters.view === "archived" ? (
                      <button disabled={mutating} onClick={() => action("restore", [group.id])}>
                        恢复
                      </button>
                    ) : (
                      <>
                        <button
                          disabled={mutating}
                          onClick={() => action(group.unread_count ? "read" : "unread", [group.id])}
                        >
                          {group.unread_count ? "标为已读" : "标为未读"}
                        </button>
                        <button disabled={mutating} onClick={() => action("archive", [group.id])}>
                          归档
                        </button>
                      </>
                    )}
                    {filters.view !== "trash" && (
                      <button disabled={mutating} onClick={() => action("delete", [group.id])}>
                        删除
                      </button>
                    )}
                  </div>
                  {expanded === group.id && snapshot.current && (
                    <NotificationEvents
                      group={group}
                      filters={filters}
                      snapshot={snapshot.current}
                      onOpen={(item) => void openItem(item, group)}
                    />
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
        {items.length < (data?.total ?? 0) && (
          <button
            className="inbox-more"
            disabled={busy || mutating}
            onClick={() => {
              pages.current++;
              void load(false, false, true);
            }}
          >
            加载更多
          </button>
        )}
      </DetailDrawer>
    </div>
  );
}
