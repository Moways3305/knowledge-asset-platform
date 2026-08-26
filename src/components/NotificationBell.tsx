import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Bell, BellOff, CheckCheck, LoaderCircle, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  fetchNotifications,
  markNotificationRead,
  markNotificationsRead,
} from "../api/notifications";
import type { BusinessNotificationDTO } from "../types/notification";
import { TASK_STATUS_INVALIDATED_EVENT } from "../workbench/taskStatusEvents";
import { formatBeijingTime } from "../utils/time";
import DetailDrawer from "./DetailDrawer";
import "./NotificationBell.css";

const POLL_MS = 60_000;
const PAGE_SIZE = 20;
const ROUTES: Record<string, string> = {
  reviews: "/review",
  original_access: "/original-access",
  upload: "/upload",
  admin_ingest: "/admin/ingest",
  models: "/admin/weknora-models",
  knowledge_detail: "/knowledge/:id",
};
const STATUS_LABEL: Record<string, string> = {
  needs_action: "待处理",
  submitted: "已提交",
  processing: "处理中",
  completed: "已完成",
  partial: "部分完成",
  failed: "失败",
};
const CATEGORY_LABEL: Record<string, string> = {
  review: "审核",
  ingest: "入库",
  parsing: "解析",
  indexing: "索引",
  knowledge_base: "知识库作业",
  original_access: "原文访问",
  ops: "系统风险",
};

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<BusinessNotificationDTO[]>([]);
  const [unread, setUnread] = useState(0);
  const [total, setTotal] = useState(0);
  const [tab, setTab] = useState<"pending" | "updates">("pending");
  const [pendingCount, setPendingCount] = useState(0);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const sequence = useRef(0);
  const mutationIds = useRef(new Set<string>());
  const navigate = useNavigate();

  const load = useCallback(async (nextPage = 1, append = false, quiet = false) => {
    const request = ++sequence.current;
    if (!quiet) setBusy(true);
    setError(null);
    try {
      const data = await fetchNotifications({
        page: nextPage,
        pageSize: PAGE_SIZE,
        unreadOnly: false,
      });
      if (request !== sequence.current) return;
      setItems((current) =>
        append
          ? [...current, ...data.items.filter((item) => !current.some((old) => old.id === item.id))]
          : data.items,
      );
      setUnread(data.unread_count ?? data.total);
      setPendingCount(
        data.pending_count ?? data.items.filter((item) => item.action_required).length,
      );
      setTotal(data.total);
      setPage(nextPage);
    } catch {
      if (request === sequence.current && !quiet) setError("通知暂时无法加载，请稍后重试。");
    } finally {
      if (request === sequence.current && !quiet) setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load(1, false, true);
  }, [load]);
  useEffect(() => {
    const refresh = () => void load(1, false, true);
    const timer = window.setInterval(refresh, POLL_MS);
    window.addEventListener("focus", refresh);
    window.addEventListener(TASK_STATUS_INVALIDATED_EVENT, refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      window.removeEventListener(TASK_STATUS_INVALIDATED_EVENT, refresh);
    };
  }, [load]);

  const markOne = async (item: BusinessNotificationDTO) => {
    if (item.is_read || mutationIds.current.has(item.id)) return true;
    mutationIds.current.add(item.id);
    setMutationError(null);
    try {
      const updated = await markNotificationRead(item.id);
      sequence.current += 1;
      setBusy(false);
      setItems((current) => current.map((row) => (row.id === item.id ? updated : row)));
      setUnread((value) => Math.max(0, value - 1));
      return true;
    } catch {
      setMutationError("未能标记为已读，你可以重试；任务状态未发生改变。");
      return false;
    } finally {
      mutationIds.current.delete(item.id);
    }
  };

  const openItem = async (item: BusinessNotificationDTO) => {
    const routeTemplate = ROUTES[item.target.route_key];
    if (!routeTemplate) {
      setMutationError("目标页暂不可用，通知仍保持未读。");
      return;
    }
    const route = routeTemplate.replace(":id", encodeURIComponent(item.target.resource_id));
    navigate(`${route}?target_id=${encodeURIComponent(item.target.resource_id)}`);
    if (await markOne(item)) setOpen(false);
  };

  const markAll = async () => {
    const ids = items.filter((item) => !item.is_read).map((item) => item.id);
    if (!ids.length) return;
    setBusy(true);
    setMutationError(null);
    try {
      await markNotificationsRead(ids);
      sequence.current += 1;
      setItems((current) =>
        current.map((item) =>
          ids.includes(item.id)
            ? { ...item, is_read: true, read_at: new Date().toISOString() }
            : item,
        ),
      );
      setUnread((value) => Math.max(0, value - ids.length));
    } catch {
      setMutationError("全部已读未能保存，列表保持原状，请重试。");
    } finally {
      setBusy(false);
    }
  };

  const visibleItems = items.filter((item) =>
    tab === "pending" ? item.action_required : !item.action_required,
  );

  return (
    <div className="notification-bell">
      <button
        type="button"
        className={`notification-bell-trigger ${open ? "is-open" : ""}`}
        aria-label={`通知中心，${pendingCount} 项待处理`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <Bell size={17} strokeWidth={1.8} aria-hidden="true" />
        {pendingCount > 0 && (
          <span className="notification-bell-badge" aria-hidden="true">
            {pendingCount > 99 ? "99+" : pendingCount}
          </span>
        )}
      </button>
      <DetailDrawer
        open={open}
        title="通知中心"
        description={`${unread} 条未读 · 已读仅代表你已查看，不代表任务完成`}
        onClose={() => setOpen(false)}
        busy={busy}
        footer={
          <div className="notification-center-footer">
            <span>仅展示你当前有权查看的事项</span>
            <button
              type="button"
              disabled={busy || !items.some((item) => !item.is_read)}
              onClick={() => void markAll()}
            >
              <CheckCheck size={15} />
              全部已读
            </button>
          </div>
        }
      >
        <div className="notification-center-filters">
          <div role="tablist" aria-label="通知范围">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "pending"}
              className={tab === "pending" ? "is-active" : ""}
              onClick={() => setTab("pending")}
            >
              待处理 <span>{pendingCount}</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "updates"}
              className={tab === "updates" ? "is-active" : ""}
              onClick={() => setTab("updates")}
            >
              动态 <span>{unread}</span>
            </button>
          </div>
        </div>
        {mutationError && (
          <div className="notification-center-alert" role="alert">
            {mutationError}
          </div>
        )}
        {busy && items.length === 0 ? (
          <div className="notification-center-state">
            <LoaderCircle className="is-spinning" />
            正在加载通知…
          </div>
        ) : error ? (
          <div className="notification-center-state">
            <BellOff />
            <strong>加载失败</strong>
            <span>{error}</span>
            <button type="button" onClick={() => void load()}>
              重试
            </button>
          </div>
        ) : visibleItems.length === 0 ? (
          <div className="notification-center-state">
            <BellOff />
            <strong>{tab === "pending" ? "暂时没有待处理事项" : "暂时没有动态"}</strong>
            <span>新的业务进展会在这里出现。</span>
          </div>
        ) : (
          <div className="notification-center-list" aria-live="polite">
            {visibleItems.map((item) => (
              <article key={item.id} className={item.is_read ? "is-read" : "is-unread"}>
                <div className="notification-center-meta">
                  <span>{CATEGORY_LABEL[item.category] ?? "其他通知"}</span>
                  <span className={`task-status is-${item.task_status}`}>
                    {STATUS_LABEL[item.task_status] ?? "状态更新"}
                  </span>
                  <time>{formatBeijingTime(item.created_at)}</time>
                </div>
                <h3>{item.title}</h3>
                <p>{item.summary}</p>
                {item.failure_reason && <p>失败原因：{item.failure_reason}</p>}
                {item.recovery_suggestion && <p>恢复建议：{item.recovery_suggestion}</p>}
                <div className="notification-center-context">
                  <span>{item.project_name ?? item.object_name}</span>
                  <span>{item.is_read ? "已读" : "未读"}</span>
                </div>
                <button
                  type="button"
                  className="notification-center-action"
                  onClick={() => void openItem(item)}
                >
                  {item.next_action_label}
                  <ArrowRight size={15} />
                </button>
              </article>
            ))}
            {items.length < total && (
              <button
                type="button"
                className="notification-center-more"
                disabled={busy}
                onClick={() => void load(page + 1, true)}
              >
                {busy ? <LoaderCircle className="is-spinning" /> : <RefreshCw />}加载更多
              </button>
            )}
          </div>
        )}
      </DetailDrawer>
    </div>
  );
}
