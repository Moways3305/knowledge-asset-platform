import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Clock3 } from "lucide-react";
import DetailDrawer from "./DetailDrawer";
import type { WorkbenchTaskItemDTO } from "../types/workbench";
import { formatBeijingTime } from "../utils/time";

export type TaskCenterGroup = "my_tasks" | "running_jobs" | "attention_items" | "recent_completed";

const GROUP_LABEL: Record<TaskCenterGroup, string> = {
  my_tasks: "我的任务",
  running_jobs: "进行中的作业",
  attention_items: "需要关注",
  recent_completed: "最近完成",
};
const STATUS_LABEL: Record<string, string> = {
  needs_action: "待处理",
  submitted: "已提交",
  processing: "处理中",
  completed: "已完成",
  partial: "部分完成",
  failed: "失败",
};
const PRIORITY_LABEL: Record<string, string> = {
  urgent: "紧急",
  high: "高优先级",
  normal: "常规",
  low: "低优先级",
};
const ROUTES: Record<string, string> = {
  reviews: "/review",
  upload: "/upload",
  original_access: "/original-access",
  admin_ingest: "/admin/ingest",
  models: "/admin/weknora-models",
  knowledge: "/knowledge",
};

function waitLabel(minutes: number | null): string | null {
  if (minutes === null) return null;
  if (minutes < 60) return `等待 ${Math.max(1, minutes)} 分钟`;
  if (minutes < 24 * 60) return `等待 ${Math.floor(minutes / 60)} 小时`;
  return `等待 ${Math.floor(minutes / (24 * 60))} 天`;
}

export default function TaskCenterDrawer({
  open,
  initialGroup = "my_tasks",
  groups,
  onClose,
}: {
  open: boolean;
  initialGroup?: TaskCenterGroup;
  groups: Record<TaskCenterGroup, WorkbenchTaskItemDTO[]>;
  onClose: () => void;
}) {
  const [group, setGroup] = useState<TaskCenterGroup>(initialGroup);
  const [selectedRef, setSelectedRef] = useState<string | null>(null);
  const items = groups[group];
  const selected = useMemo(
    () => items.find((item) => item.task_ref === selectedRef) ?? items[0] ?? null,
    [items, selectedRef],
  );
  const route = selected?.route_key ? ROUTES[selected.route_key] : undefined;

  return (
    <DetailDrawer
      open={open}
      title="任务中心"
      description="同一份权限过滤数据，集中查看待办、作业进度与业务终态。"
      onClose={onClose}
      footer={
        selected && route ? (
          <Link className="tc90-primary-action" to={route} onClick={onClose}>
            {selected.next_action_label}
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        ) : undefined
      }
    >
      <div className="tc90-drawer-tabs" role="tablist" aria-label="任务分组">
        {(Object.keys(GROUP_LABEL) as TaskCenterGroup[]).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={group === key}
            className={group === key ? "is-active" : ""}
            onClick={() => {
              setGroup(key);
              setSelectedRef(null);
            }}
          >
            {GROUP_LABEL[key]}
            <span>{groups[key].length}</span>
          </button>
        ))}
      </div>
      {items.length === 0 ? (
        <div className="tc90-empty">此分组当前没有任务。</div>
      ) : (
        <div className="tc90-drawer-layout">
          <div className="tc90-drawer-list" aria-label={`${GROUP_LABEL[group]}列表`}>
            {items.map((item) => (
              <button
                key={item.task_ref}
                type="button"
                className={selected?.task_ref === item.task_ref ? "is-selected" : ""}
                onClick={() => setSelectedRef(item.task_ref)}
              >
                <span className={`tc90-status-dot is-${item.status}`} aria-hidden="true" />
                <span>
                  <strong>{item.object_name}</strong>
                  <small>{item.project_name || item.responsibility}</small>
                </span>
                <em>{STATUS_LABEL[item.status] || item.status}</em>
              </button>
            ))}
          </div>
          {selected && (
            <article className="tc90-detail">
              <div className="tc90-detail-heading">
                <span className={`tc90-priority is-${selected.priority}`}>
                  {PRIORITY_LABEL[selected.priority] || selected.priority}
                </span>
                <span className={`tc90-status is-${selected.status}`}>
                  {STATUS_LABEL[selected.status] || selected.status}
                </span>
              </div>
              <h3>{selected.object_name}</h3>
              <dl>
                <div>
                  <dt>任务类型</dt>
                  <dd>{selected.task_type}</dd>
                </div>
                <div>
                  <dt>所属项目</dt>
                  <dd>{selected.project_name || "不适用"}</dd>
                </div>
                <div>
                  <dt>负责人</dt>
                  <dd>{selected.assignee}</dd>
                </div>
                <div>
                  <dt>责任关系</dt>
                  <dd>{selected.responsibility}</dd>
                </div>
                <div>
                  <dt>创建时间</dt>
                  <dd>{formatBeijingTime(selected.created_at)}</dd>
                </div>
                <div>
                  <dt>最近更新</dt>
                  <dd>{formatBeijingTime(selected.updated_at)}</dd>
                </div>
              </dl>
              {waitLabel(selected.waiting_minutes) && (
                <p className="tc90-wait">
                  <Clock3 size={15} />
                  {waitLabel(selected.waiting_minutes)}
                </p>
              )}
              {selected.progress_total !== null && (
                <div className="tc90-progress">
                  <span>总计 {selected.progress_total}</span>
                  <span>成功 {selected.progress_success ?? 0}</span>
                  <span>失败 {selected.progress_failed ?? 0}</span>
                </div>
              )}
              {selected.result_summary && <p className="tc90-result">{selected.result_summary}</p>}
              <div className="tc90-next">
                <span>下一步</span>
                <strong>{selected.next_action_label}</strong>
              </div>
            </article>
          )}
        </div>
      )}
    </DetailDrawer>
  );
}
