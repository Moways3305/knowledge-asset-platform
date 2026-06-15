import type { ReactNode } from "react";

// 统一状态标签渲染：复用全局 `.status-pill` 基类 + 各页面已有的状态修饰类
// （如 ig-status-failed / rv-status-approved），不改变任何现有视觉。
interface StatusBadgeProps {
  label: ReactNode;
  // 状态修饰类（决定底色/前景色），与现有 CSS 中 `.status-pill.<variant>` 对应。
  variant?: string;
  className?: string;
  title?: string;
}

export default function StatusBadge({ label, variant, className, title }: StatusBadgeProps) {
  const cls = ["status-pill", variant, className].filter(Boolean).join(" ");
  return (
    <span className={cls} title={title}>
      {label}
    </span>
  );
}
