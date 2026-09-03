import type { ReactNode } from "react";
import { ShieldCheck, Trash2 } from "lucide-react";
import Button from "./Button";
import TaskModal from "./TaskModal";

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
  errorDescription?: ReactNode;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
  icon?: ReactNode;
  panelClassName?: string;
  closeButtonLabel?: string;
  portal?: boolean;
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
  portal = false,
}: ConfirmDialogProps) {
  return (
    <TaskModal
      open={open}
      title={title}
      description={description}
      onClose={onCancel}
      busy={busy}
      size="small"
      panelClassName={panelClassName}
      closeLabel={closeButtonLabel ?? "关闭确认弹窗"}
      portal={portal}
      leadingIcon={
        <span
          className={`confirm-dialog-icon ${danger ? "is-danger" : "is-governance"}`}
          aria-hidden="true"
        >
          {icon ?? (danger ? <Trash2 size={20} /> : <ShieldCheck size={20} />)}
        </span>
      }
      footer={
        <>
          <Button data-autofocus disabled={busy} onClick={onCancel}>
            {cancelText}
          </Button>
          <span className="task-modal-footer-spacer" />
          <Button
            variant={danger ? "danger" : "primary"}
            onClick={onConfirm}
            disabled={busy || confirmDisabled}
          >
            {busy ? busyText : confirmText}
          </Button>
        </>
      }
    >
      {children}
      {error && (
        <div className="kl-modal-error" role="alert">
          {errorDescription ?? "操作未完成，请检查后重试。"}
        </div>
      )}
    </TaskModal>
  );
}
