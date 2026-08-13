import type { ReactNode } from "react";
import { OPERATION_STATUS, type OperationStatus } from "./operationStatus";

// 统一状态标签渲染：复用全局 `.status-pill` 基类 + 各页面已有的状态修饰类
// （如 ig-status-failed / rv-status-approved），不改变任何现有视觉。
interface StatusBadgeProps {
  label?: ReactNode;
  status?: OperationStatus;
  // 状态修饰类（决定底色/前景色），与现有 CSS 中 `.status-pill.<variant>` 对应。
  variant?: string;
  className?: string;
  title?: string;
  tone?: "neutral" | "info" | "success" | "warning" | "danger";
  showIcon?: boolean;
}

export default function StatusBadge({
  label,
  status,
  variant,
  className,
  title,
  tone,
  showIcon = Boolean(status),
}: StatusBadgeProps) {
  const definition = status ? OPERATION_STATUS[status] : null;
  const Icon = definition?.Icon;
  const resolvedLabel = label ?? definition?.label;
  const resolvedTone = tone ?? definition?.tone ?? "neutral";
  const cls = ["status-pill", `is-${resolvedTone}`, variant, className].filter(Boolean).join(" ");
  return (
    <span className={cls} title={title ?? definition?.guidance} data-operation-status={status}>
      {showIcon && Icon && <Icon className="status-pill-icon" size={13} aria-hidden="true" />}
      {resolvedLabel}
    </span>
  );
}
