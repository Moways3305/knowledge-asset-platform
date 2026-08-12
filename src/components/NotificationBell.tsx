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
  const [categories, setCategories] = useState<string[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const sequence = useRef(0);
  const mutationIds = useRef(new Set<string>());
  const navigate = useNavigate();

  const load = useCallback(
    async (nextPage = 1, append = false, quiet = false) => {
      const request = ++sequence.current;
      if (!quiet) setBusy(true);
      setError(null);
      try {
        const data = await fetchNotifications({
          page: nextPage,
          pageSize: PAGE_SIZE,
          unreadOnly,
          category,
        });
        if (request !== sequence.current) return;
        setItems((current) =>
          append
            ? [
                ...current,
                ...data.items.filter((item) => !current.some((old) => old.id === item.id)),
              ]
            : data.items,
        );
        setUnread(data.unread_count ?? data.total);
        setTotal(data.total);
        setCategories(data.categories ?? []);
        setPage(nextPage);
      } catch {
        if (request === sequence.current && !quiet) setError("通知暂时无法加载，请稍后重试。");
      } finally {
        if (request === sequence.current && !quiet) setBusy(false);
      }
    },
    [category, unreadOnly],
  );

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
      setItems((current) =>
        unreadOnly
          ? current.filter((row) => row.id !== item.id)
          : current.map((row) => (row.id === item.id ? updated : row)),
      );
      setUnread((value) => Math.max(0, value - 1));
      if (unreadOnly) setTotal((value) => Math.max(0, value - 1));
      return true;
    } catch {
      setMutationError("未能标记为已读，你可以重试；任务状态未发生改变。");
      return false;
    } finally {
      mutationIds.current.delete(item.id);
    }
  };

  const openItem = async (item: BusinessNotificationDTO) => {
    const marked = await markOne(item);
    if (!marked) return;
    setOpen(false);
    const route = item.action_required ? ROUTES[item.target.route_key] : undefined;
    navigate(route ?? `/?task_group=${encodeURIComponent(item.task_group)}`);
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
        unreadOnly
          ? current.filter((item) => !ids.includes(item.id))
          : current.map((item) =>
              ids.includes(item.id)
                ? { ...item, is_read: true, read_at: new Date().toISOString() }
                : item,
            ),
      );
      setUnread((value) => Math.max(0, value - ids.length));
      if (unreadOnly) setTotal((value) => Math.max(0, value - ids.length));
    } catch {
      setMutationError("全部已读未能保存，列表保持原状，请重试。");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="notification-bell">
      <button
        type="button"
        className={`notification-bell-trigger ${open ? "is-open" : ""}`}
        aria-label={`通知中心，${unread} 条未读`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <Bell size={17} strokeWidth={1.8} aria-hidden="true" />
        {unread > 0 && (
          <span className="notification-bell-badge" aria-hidden="true">
            {unread > 99 ? "99+" : unread}
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
              aria-selected={!unreadOnly}
              className={!unreadOnly ? "is-active" : ""}
              onClick={() => setUnreadOnly(false)}
            >
              最近通知
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={unreadOnly}
              className={unreadOnly ? "is-active" : ""}
              onClick={() => setUnreadOnly(true)}
            >
              未读 <span>{unread}</span>
            </button>
          </div>
          <label>
            <span>类别</span>
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="">全部类别</option>
              {categories.map((key) => (
                <option key={key} value={key}>
                  {CATEGORY_LABEL[key] ?? "其他通知"}
                </option>
              ))}
            </select>
          </label>
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
        ) : items.length === 0 ? (
          <div className="notification-center-state">
            <BellOff />
            <strong>{unreadOnly ? "没有未读通知" : "暂时没有通知"}</strong>
            <span>新的业务进展会在这里出现。</span>
          </div>
        ) : (
          <div className="notification-center-list" aria-live="polite">
            {items.map((item) => (
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
                {item.delivery_status === "failed" && (
                  <p className="notification-delivery-warning">
                    外部提醒未送达，站内通知仍可正常使用。
                  </p>
                )}
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
