import type { ReactNode } from "react";

// 统一确认弹窗：复用现有 `.kl-modal-*` 模态样式。用于需要明确二次确认的写动作
// （如删除 / 撤销 / 强制下线）。busy 期间禁用按钮并屏蔽遮罩点击关闭，避免重复提交。
// danger=true 时确认按钮用危险色（btn-small-danger）。
interface ConfirmDialogProps {
  open: boolean;
  title: ReactNode;
  description?: ReactNode;
  confirmText?: string;
  cancelText?: string;
  busy?: boolean;
  busyText?: string;
  danger?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}

export default function ConfirmDialog({
  open,
  title,
  description,
  confirmText = "确认",
  cancelText = "取消",
  busy = false,
  busyText = "处理中…",
  danger = false,
  error,
  onConfirm,
  onCancel,
  children,
}: ConfirmDialogProps) {
  if (!open) return null;
  return (
    <div className="kl-modal-overlay" onClick={() => !busy && onCancel()}>
      <div className="kl-modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3 className="kl-modal-title">{title}</h3>
        {description && <p className="kl-modal-desc">{description}</p>}
        {children}
        {error && <div className="kl-modal-error">{error}</div>}
        <div className="kl-modal-actions">
          <button
            className={`btn-small ${danger ? "btn-small-danger" : "btn-small-primary"}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? busyText : confirmText}
          </button>
          <button className="btn-small" onClick={onCancel} disabled={busy}>
            {cancelText}
          </button>
        </div>
      </div>
    </div>
  );
}
