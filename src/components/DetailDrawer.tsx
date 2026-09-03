import { useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useDialogSurface } from "./useDialogSurface";

interface DetailDrawerProps {
  open: boolean;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  busy?: boolean;
  portal?: boolean;
}

export default function DetailDrawer({
  open,
  title,
  description,
  children,
  footer,
  onClose,
  busy = false,
  portal = false,
}: DetailDrawerProps) {
  const titleId = useId();
  const drawerRef = useRef<HTMLElement>(null);
  const { onKeyDown } = useDialogSurface(open, drawerRef, onClose, busy);
  if (!open) return null;
  const drawer = (
    <div className="experience-overlay is-drawer" onMouseDown={() => !busy && onClose()}>
      <aside
        ref={drawerRef}
        className="detail-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="detail-drawer-header">
          <div>
            <span className="task-modal-eyebrow">上下文详情</span>
            <h2 id={titleId}>{title}</h2>
            {description && <p>{description}</p>}
          </div>
          <button type="button" aria-label="关闭详情" disabled={busy} onClick={onClose}>
            <X size={19} aria-hidden="true" />
          </button>
        </header>
        <div className="detail-drawer-body">{children}</div>
        {footer && <footer className="detail-drawer-footer">{footer}</footer>}
      </aside>
    </div>
  );
  return portal && typeof document !== "undefined" ? createPortal(drawer, document.body) : drawer;
}
