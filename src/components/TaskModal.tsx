import { useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useDialogSurface } from "./useDialogSurface";

export interface TaskModalProps {
  open: boolean;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  busy?: boolean;
  size?: "small" | "medium" | "large";
  closeLabel?: string;
  eyebrow?: ReactNode;
  leadingIcon?: ReactNode;
  panelClassName?: string;
}

export default function TaskModal({
  open,
  title,
  description,
  children,
  footer,
  onClose,
  busy = false,
  size = "medium",
  closeLabel = "关闭弹窗",
  eyebrow,
  leadingIcon,
  panelClassName = "",
}: TaskModalProps) {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLElement>(null);
  const { onKeyDown } = useDialogSurface(open, panelRef, onClose, busy);

  if (!open) return null;
  const modal = (
    <div className="experience-overlay" onMouseDown={() => !busy && onClose()}>
      <section
        ref={panelRef}
        className={`task-modal is-${size} ${panelClassName}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        aria-busy={busy}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="task-modal-header">
          {leadingIcon}
          <div className="task-modal-heading">
            {eyebrow && <span className="task-modal-eyebrow">{eyebrow}</span>}
            <h2 id={titleId}>{title}</h2>
            {description && <p id={descriptionId}>{description}</p>}
          </div>
          <button
            type="button"
            className="task-modal-close"
            aria-label={closeLabel}
            disabled={busy}
            onClick={onClose}
          >
            <X size={19} aria-hidden="true" />
          </button>
        </header>
        {children && <div className="task-modal-body">{children}</div>}
        {footer && <footer className="task-modal-footer">{footer}</footer>}
      </section>
    </div>
  );
  return typeof document === "undefined" ? modal : createPortal(modal, document.body);
}
