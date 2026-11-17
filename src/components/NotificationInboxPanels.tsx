import { useCallback, useEffect, useState } from "react";
import {
  fetchNotificationEvents,
  fetchNotificationPreferences,
  saveNotificationPreferences,
  type InboxFilter,
  type NotificationGroup,
  type NotificationPreferences,
} from "../api/notificationInbox";
import type { BusinessNotificationDTO } from "../types/notification";
import { formatBeijingTime } from "../utils/time";
import { taskStatusLabel } from "./taskCenterLabels";

export const CATEGORY_LABEL: Record<string, string> = {
  knowledge: "知识维护",
  review: "审核",
  ingest: "入库",
  parsing: "解析",
  indexing: "索引",
  knowledge_base: "知识库作业",
  original_access: "原文访问",
  ops: "系统风险",
};

export function NotificationEvents({
  group,
  filters,
  snapshot,
  onOpen,
}: {
  group: NotificationGroup;
  filters: InboxFilter;
  snapshot: string;
  onOpen: (item: BusinessNotificationDTO) => void;
}) {
  const [items, setItems] = useState<BusinessNotificationDTO[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    void fetchNotificationEvents(group.id, filters, snapshot, page, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setItems(data.items);
          setTotal(data.total);
          setError("");
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setItems([]);
          setError("详情暂不可用，消息可能已清理或权限已变更。");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [group.id, filters, snapshot, page, retry]);
  return (
    <section className="inbox-events" aria-label="消息详情">
      {group.id.startsWith("upload:") && (
        <p>
          本组已完成 {group.completed_count} 项，异常 {group.failed_count}{" "}
          项。逐条消息可打开对应任务。
        </p>
      )}
      {error && (
        <p role="alert">
          {error}
          <button onClick={() => setRetry((value) => value + 1)}>重试详情</button>
        </p>
      )}
      {busy && <p role="status">正在加载详情…</p>}
      {items.map((item) => (
        <div key={item.id} className="inbox-event">
          <time>{formatBeijingTime(item.created_at)}</time>
          <strong>{item.title}</strong>
          <p>{item.summary}</p>
          <span>{taskStatusLabel(item.task_status)}</span>
          {item.project_name && <span>{item.project_name}</span>}
          {item.failure_reason && <p>失败原因：{item.failure_reason}</p>}
          {item.recovery_suggestion && <p>恢复建议：{item.recovery_suggestion}</p>}
          <button disabled={busy} onClick={() => onOpen(item)}>
            {item.next_action_label}
          </button>
        </div>
      ))}
      {total > 20 && (
        <div className="inbox-tools">
          <button disabled={busy || page <= 1} onClick={() => setPage((value) => value - 1)}>
            上一页消息
          </button>
          <span>
            第 {page} 页 / {Math.ceil(total / 20)} 页
          </span>
          <button
            disabled={busy || page * 20 >= total}
            onClick={() => setPage((value) => value + 1)}
          >
            下一页消息
          </button>
        </div>
      )}
    </section>
  );
}

export function NotificationSettings({ onClose }: { onClose: () => void }) {
  const [value, setValue] = useState<NotificationPreferences>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    setBusy(true);
    void fetchNotificationPreferences()
      .then(setValue)
      .catch(() => setError("设置加载失败，请重试。"))
      .finally(() => setBusy(false));
  }, []);
  useEffect(load, [load]);
  const save = async () => {
    if (!value) return;
    setBusy(true);
    setError("");
    try {
      await saveNotificationPreferences(value);
      onClose();
    } catch {
      setError("设置未保存，请重试。你的修改已保留。");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="inbox-settings" aria-label="通知设置">
      <strong>通知设置</strong>
      <p>按类型选择新消息的接收方式。关闭提醒不影响业务待办；企业微信需要平台已接通。</p>
      {error && (
        <p role="alert">
          {error}
          {!value && <button onClick={load}>重试设置</button>}
        </p>
      )}
      {value && (
        <>
          <div className="inbox-preference-head">
            <span>消息类型</span>
            <span>站内</span>
            <span>企业微信</span>
          </div>
          {Object.entries(CATEGORY_LABEL).map(([key, label]) => {
            const category = value.categories[key] ?? { in_app: true, wecom: "immediate" as const };
            const update = (change: Partial<typeof category>) =>
              setValue({
                ...value,
                categories: { ...value.categories, [key]: { ...category, ...change } },
              });
            return (
              <div className="inbox-preference" key={key}>
                <span>{label}</span>
                <input
                  type="checkbox"
                  aria-label={`${label}站内通知`}
                  checked={category.in_app}
                  disabled={busy}
                  onChange={(e) => update({ in_app: e.target.checked })}
                />
                <select
                  aria-label={`${label}企业微信`}
                  value={category.wecom}
                  disabled={busy}
                  onChange={(e) => update({ wecom: e.target.value as typeof category.wecom })}
                >
                  <option value="immediate">即时提醒</option>
                  <option value="hourly">每小时摘要</option>
                  <option value="off">关闭</option>
                </select>
              </div>
            );
          })}
          <label className="inbox-retention">
            自动归档已读历史
            <select
              value={value.auto_archive_days}
              disabled={busy}
              onChange={(e) =>
                setValue({
                  ...value,
                  auto_archive_days: Number(
                    e.target.value,
                  ) as NotificationPreferences["auto_archive_days"],
                })
              }
            >
              <option value={0}>不自动归档</option>
              {[30, 90, 180].map((days) => (
                <option key={days} value={days}>
                  {days} 天后
                </option>
              ))}
            </select>
          </label>
          <p>仅归档已读且已结束的普通动态；待处理、运行中及异常消息保留。</p>
        </>
      )}
      <div className="inbox-tools">
        <button disabled={busy || !value} onClick={() => void save()}>
          保存通知设置
        </button>
        <button disabled={busy} onClick={onClose}>
          关闭设置
        </button>
      </div>
    </section>
  );
}
