import type { IndexingHealthDTO, OpsIndexingFailedItemDTO } from "../../../types/ops";
import { formatBeijingTime } from "../../../utils/time";
export type LoadState = "loading" | "ready" | "error";

export type DiagnosticCategory = OpsIndexingFailedItemDTO["diagnostic_category"];

export type FailureFilter = "all" | DiagnosticCategory;

export const JOB_POLL_INTERVAL_MS = 1_500;

export const JOB_POLL_MAX_ATTEMPTS = 20;

export const OPS_AUTO_REFRESH_MS = 60_000;

export const DEFAULT_VISIBLE_RECOVERY_ITEMS = 4;

export const jobOpLabel: Record<string, string> = {
  retry_index: "恢复索引",
  reparse: "重新解析",
  markdown_backfill: "历史正文回填",
  kb_migrate: "知识库迁移",
};

export const jobStatusLabel: Record<string, string> = {
  queued: "等待执行",
  running: "执行中",
  submitted_pending_index: "已提交，待索引确认",
  completed: "已完成",
  completed_with_errors: "完成，部分未成功",
  failed: "执行失败",
  no_action: "未找到可处理项",
};

export const ingestStatusLabel: Record<string, string> = {
  pending: "待处理",
  processing: "处理中",
  pending_confirmation: "待业务确认",
  waiting_review: "待审核",
  rejected: "已驳回",
  completed: "已完成",
  duplicate_skipped: "重复跳过",
  cancelled: "已取消",
  failed: "处理失败",
};

export function ingestFailureLabel(errorType: string | null): string {
  if (errorType === "processing_timeout") return "处理超时";
  if (errorType?.includes("extract")) return "内容提取失败";
  if (errorType === "queue_unavailable") return "任务排队失败";
  if (errorType?.includes("storage")) return "临时文件处理失败";
  return "文件处理失败";
}

export function timeoutRecoveryStopLabel(reason: string | null): string {
  const labels: Record<string, string> = {
    batch_in_progress: "已有恢复批次正在执行",
    batch_interval_not_elapsed: "距上一批次不足 15 秒",
    redis_unavailable: "Redis 当前不可用",
    ocr_worker_unavailable: "OCR 工作进程当前不可用",
    queue_budget_exceeded: "当前队列已达到安全预算",
    oom_kill_count_changed: "检测到新的内存终止事件",
    oom_baseline_confirmation_required: "需要重新确认内存终止计数",
    queue_unavailable: "恢复任务暂时无法排队",
  };
  return reason ? (labels[reason] ?? "运行预检未通过") : "运行预检未通过";
}

export const urgentSeverities = new Set(["critical", "error"]);

export const diagnosticLabels: Record<DiagnosticCategory, string> = {
  configuration: "配置问题",
  external_service: "外部服务",
  source_content: "文件或内容",
  permission: "权限或访问",
  platform: "平台处理",
  unknown: "待确认",
};

export const recoveryStatePriority: Record<string, number> = {
  submission_interrupted: 0,
  parse_interrupted: 0,
  interrupted: 0,
  failed: 1,
  waiting: 2,
  skipped: 3,
};

export function recoveryWaitLabel(waitSeconds?: number | null): string {
  const seconds = Math.max(0, waitSeconds ?? 0);
  if (seconds < 60) return "不足 1 分钟";
  if (seconds < 3_600) return `${Math.floor(seconds / 60)} 分钟`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3_600)} 小时`;
  return `${Math.floor(seconds / 86_400)} 天`;
}

export const healthLabels = {
  healthy: "正常",
  degraded: "需关注",
  stale: "心跳过期",
  unknown: "待确认",
};

export function trendPointLabel(point: IndexingHealthDTO["trend_points"][number]): string {
  return `${formatBeijingTime(point.observed_at)}，已完成作业 ${point.completed_jobs}，失败或部分失败作业 ${point.failed_jobs}，排队作业 ${point.queued_jobs}，索引失败存量 ${point.index_failed}，解析失败存量 ${point.parse_failed}`;
}

export function trendTickLabel(points: IndexingHealthDTO["trend_points"], index: number): string {
  const current = formatBeijingTime(points[index]?.observed_at);
  const previous = index > 0 ? formatBeijingTime(points[index - 1]?.observed_at) : null;
  const time = current.slice(11, 16);
  return previous && previous.slice(0, 10) !== current.slice(0, 10)
    ? `${current.slice(5, 10).replace("-", "/")} ${time}`
    : time;
}

export function trendTickIndexes(points: IndexingHealthDTO["trend_points"]): Set<number> {
  if (points.length < 8) return new Set(points.map((_, index) => index));
  const indexes = new Set<number>();
  if (points.length === 24) {
    for (let index = 0; index < points.length; index += 3) indexes.add(index);
  } else {
    const last = points.length - 1;
    for (let tick = 0; tick < 8; tick += 1) indexes.add(Math.round((last * tick) / 7));
  }
  const dateBoundaries: number[] = [];
  for (let index = 1; index < points.length; index += 1) {
    const previousDate = formatBeijingTime(points[index - 1].observed_at).slice(0, 10);
    const currentDate = formatBeijingTime(points[index].observed_at).slice(0, 10);
    if (currentDate !== previousDate) dateBoundaries.push(index);
  }
  for (const boundary of dateBoundaries) {
    for (const index of [...indexes]) {
      if (Math.abs(index - boundary) < 3) indexes.delete(index);
    }
    indexes.add(boundary);
  }
  indexes.add(points.length - 1);
  while (indexes.size < 8) {
    let candidate = -1;
    let candidateDistance = -1;
    for (let index = 0; index < points.length; index += 1) {
      if (indexes.has(index)) continue;
      const distance = Math.min(...[...indexes].map((existing) => Math.abs(existing - index)));
      if (distance > candidateDistance) {
        candidate = index;
        candidateDistance = distance;
      }
    }
    if (candidate < 0) break;
    indexes.add(candidate);
  }
  return indexes;
}

export function jobTone(status: string) {
  if (status === "completed") return "success";
  if (status === "failed" || status === "completed_with_errors") return "danger";
  if (status === "no_action") return "warning";
  return "pending";
}

export function safeJobStatus(status: string) {
  return jobStatusLabel[status] ?? "状态待确认";
}

export function safeJobOperation(operation: string) {
  return jobOpLabel[operation] ?? "索引维护作业";
}

export function failureTone(item: OpsIndexingFailedItemDTO) {
  return urgentSeverities.has(item.severity ?? "") ? "danger" : "warning";
}

export function safeFailureMessage(item: OpsIndexingFailedItemDTO) {
  return item.operator_error_message || item.index_error_message || "索引处理异常";
}

export function recoveryStateLabel(item: OpsIndexingFailedItemDTO) {
  if (item.recovery_state === "submission_interrupted") return "索引提交中断";
  if (item.recovery_state === "parse_interrupted" || item.recovery_state === "interrupted")
    return "解析中断";
  if (item.recovery_state === "waiting") return "等待索引";
  if (item.recovery_state === "skipped") return "此前未进入";
  return "索引失败";
}
