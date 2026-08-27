const TASK_STATUS_LABEL: Record<string, string> = {
  needs_action: "待处理",
  submitted: "已提交",
  processing: "处理中",
  completed: "已完成",
  partial: "部分完成",
  failed: "失败",
  duplicate_skipped: "重复跳过",
};

const TASK_PRIORITY_LABEL: Record<string, string> = {
  urgent: "紧急",
  high: "高优先级",
  normal: "常规",
  low: "低优先级",
};

// 与 backend/app/services/workbench.py 的安全 task_type 投影保持一致。
// 保留 migration 作为旧响应兼容键，未知值必须回退为面向用户的中性文案。
const TASK_TYPE_LABEL: Record<string, string> = {
  review: "知识审核",
  ingest: "上传资料",
  original_access: "原文审批",
  indexing: "索引作业",
  parsing: "解析作业",
  migration: "迁移作业",
  kb_migration: "迁移作业",
  markdown_backfill: "内容补齐作业",
  operation: "后台作业",
  index_failed: "索引异常",
  parse_failed: "解析异常",
  kb_init_failed: "知识库异常",
  pending_original_requests: "原文申请",
  overdue_original_requests: "超时原文申请",
  archive_candidates: "资产归档",
  reuse_upgrade_candidates: "复用升格",
};

export const taskStatusLabel = (status: string): string =>
  TASK_STATUS_LABEL[status] ?? "状态待确认";

export const taskPriorityLabel = (priority: string): string =>
  TASK_PRIORITY_LABEL[priority] ?? "常规";

export const taskTypeLabel = (taskType: string): string => TASK_TYPE_LABEL[taskType] ?? "业务任务";
