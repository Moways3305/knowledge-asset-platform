import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, BellOff, CheckCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  fetchNotificationUnreadCount,
  fetchNotifications,
  markNotificationRead,
  markNotificationsRead,
} from "../api/notifications";
import type { BusinessNotificationDTO } from "../types/notification";
import { formatBeijingTime } from "../utils/time";
import "./NotificationBell.css";

const POLL_MS = 60_000;
const PANEL_PAGE_SIZE = 20;
const TARGET_ROUTES: Record<string, string> = {
  reviews: "/review",
  original_access: "/original-access",
  upload: "/upload",
  admin_ingest: "/admin/ingest",
};

function targetPath(notification: BusinessNotificationDTO): string {
  return TARGET_ROUTES[notification.target.route_key] ?? "/";
}

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<BusinessNotificationDTO[]>([]);
  const [busy, setBusy] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  const loadUnread = useCallback(async () => {
    try {
      const data = await fetchNotificationUnreadCount();
      setUnread(data.unread_count);
    } catch {
      // 通知是辅助功能：失败静默，不影响页面主流程。
    }
  }, []);

  const loadPanel = useCallback(async () => {
    setBusy(true);
    try {
      const data = await fetchNotifications({
        page: 1,
        pageSize: PANEL_PAGE_SIZE,
        unreadOnly: true,
      });
      setItems(data.items);
      setUnread(data.total);
    } catch {
      // 静默。
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void loadUnread();
    const timer = window.setInterval(() => void loadUnread(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [loadUnread]);

  useEffect(() => {
    if (!open) return;
    void loadPanel();
    const onDown = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open, loadPanel]);

  const openNotification = async (notification: BusinessNotificationDTO) => {
    setOpen(false);
    if (!notification.is_read) {
      try {
        await markNotificationRead(notification.id);
      } catch {
        // 已读失败不阻断跳转。
      }
    }
    navigate(targetPath(notification));
  };

  const markAllRead = async () => {
    if (items.length === 0) return;
    setBusy(true);
    try {
      await markNotificationsRead(items.map((item) => item.id));
      setItems([]);
      setUnread(0);
    } catch {
      // 静默。
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="notification-bell" ref={wrapRef}>
      <button
        type="button"
        className={`notification-bell-trigger ${open ? "is-open" : ""}`}
        aria-label="通知"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <Bell size={17} strokeWidth={1.8} aria-hidden="true" />
        {unread > 0 && (
          <span className="notification-bell-badge" aria-hidden="true">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="notification-bell-panel" role="dialog" aria-label="通知列表">
          <div className="notification-bell-head">
            <strong>通知</strong>
            <button
              type="button"
              disabled={busy || items.length === 0}
              onClick={() => void markAllRead()}
            >
              <CheckCheck size={13} aria-hidden="true" />
              全部已读
            </button>
          </div>
          {busy && items.length === 0 ? (
            <div className="notification-bell-empty">正在加载通知…</div>
          ) : items.length === 0 ? (
            <div className="notification-bell-empty">
              <BellOff size={22} aria-hidden="true" />
              暂无未读通知
            </div>
          ) : (
            <ul className="notification-bell-list">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className="notification-bell-item"
                    onClick={() => void openNotification(item)}
                  >
                    <strong>{item.title}</strong>
                    <p>{item.summary}</p>
                    <time>{formatBeijingTime(item.created_at)}</time>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="notification-bell-foot">
            <span>点击通知跳转处理；通知仅展示当前账户可见事项。</span>
          </div>
        </div>
      )}
    </div>
  );
}
