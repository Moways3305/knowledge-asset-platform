import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { ShieldCheck, Trash2, X } from "lucide-react";

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
  confirmDisabled?: boolean;
  busyText?: string;
  danger?: boolean;
  error?: string | null;
  // 仅传入调用方已经收口的业务提示；原始 error 只作为状态标志，不直接渲染。
  errorDescription?: ReactNode;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
  icon?: ReactNode;
  panelClassName?: string;
  closeButtonLabel?: string;
}

export default function ConfirmDialog({
  open,
  title,
  description,
  confirmText = "确认",
  cancelText = "取消",
  busy = false,
  confirmDisabled = false,
  busyText = "处理中…",
  danger = false,
  error,
  errorDescription,
  onConfirm,
  onCancel,
  children,
  icon,
  panelClassName,
  closeButtonLabel,
}: ConfirmDialogProps) {
  const titleId = useId();
  const modalRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    cancelRef.current?.focus();
    return () => previousFocus?.focus();
  }, [open]);

  if (!open) return null;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && !busy) {
      event.preventDefault();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [
      ...(modalRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? []),
    ];
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="kl-modal-overlay" onClick={() => !busy && onCancel()}>
      <div
        ref={modalRef}
        className={`kl-modal ${panelClassName ?? ""}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        <div className="kl-modal-header">
          <div
            className={`confirm-dialog-icon ${danger ? "is-danger" : "is-governance"}`}
            aria-hidden="true"
          >
            {icon ?? (danger ? <Trash2 size={20} /> : <ShieldCheck size={20} />)}
          </div>
          <h3 className="kl-modal-title" id={titleId}>
            {title}
          </h3>
          {description && <p className="kl-modal-desc">{description}</p>}
          {closeButtonLabel && (
            <button
              aria-label={closeButtonLabel}
              className="kl-modal-close"
              disabled={busy}
              onClick={onCancel}
              type="button"
            >
              <X aria-hidden="true" size={20} />
            </button>
          )}
        </div>
        {children && <div className="kl-modal-body">{children}</div>}
        {error && (
          <div className="kl-modal-error">{errorDescription ?? "操作未完成，请检查后重试。"}</div>
        )}
        <div className="kl-modal-actions">
          <button
            type="button"
            className={`btn-small ${danger ? "btn-small-danger" : "btn-small-primary"}`}
            onClick={onConfirm}
            disabled={busy || confirmDisabled}
          >
            {busy ? busyText : confirmText}
          </button>
          <button
            type="button"
            ref={cancelRef}
            className="btn-small"
            onClick={onCancel}
            disabled={busy}
          >
            {cancelText}
          </button>
        </div>
      </div>
    </div>
  );
}
