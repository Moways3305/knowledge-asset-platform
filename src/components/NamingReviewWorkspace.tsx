import type { ReactNode } from "react";
import { ClipboardCheck } from "lucide-react";
import Button from "./Button";
import TaskModal from "./TaskModal";

export interface NamingReviewWorkspaceProps {
  open: boolean;
  title: ReactNode;
  description?: ReactNode;
  confirmText?: string;
  cancelText?: string;
  busy?: boolean;
  confirmDisabled?: boolean;
  busyText?: string;
  error?: string | null;
  errorDescription?: ReactNode;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
  panelClassName?: string;
  closeButtonLabel?: string;
  portal?: boolean;
}

export default function NamingReviewWorkspace({
  open,
  title,
  description,
  confirmText = "确认入库",
  cancelText = "取消",
  busy = false,
  confirmDisabled = false,
  busyText = "处理中…",
  error,
  errorDescription,
  onConfirm,
  onCancel,
  children,
  panelClassName = "",
  closeButtonLabel = "关闭批量命名核对",
  portal = false,
}: NamingReviewWorkspaceProps) {
  return (
    <TaskModal
      open={open}
      title={title}
      description={description}
      onClose={onCancel}
      busy={busy}
      size="large"
      panelClassName={`naming-review-workspace ${panelClassName}`.trim()}
      closeLabel={closeButtonLabel}
      portal={portal}
      leadingIcon={<ClipboardCheck size={20} aria-hidden="true" />}
      footer={
        <>
          <Button data-autofocus disabled={busy} onClick={onCancel}>
            {cancelText}
          </Button>
          <span className="task-modal-footer-spacer" />
          <Button variant="primary" onClick={onConfirm} disabled={busy || confirmDisabled}>
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
