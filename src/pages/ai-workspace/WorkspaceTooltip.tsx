import {
  cloneElement,
  forwardRef,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
  bottom: number;
}

export function positionWorkspaceTooltip(
  anchor: Rect,
  bubble: { width: number; height: number },
  viewport: { width: number; height: number },
) {
  const margin = 8;
  const gap = 8;
  const above = anchor.top - bubble.height - gap;
  const desiredTop = above >= margin ? above : anchor.bottom + gap;
  return {
    left: Math.max(
      margin,
      Math.min(
        anchor.left + (anchor.width - bubble.width) / 2,
        viewport.width - bubble.width - margin,
      ),
    ),
    top: Math.max(margin, Math.min(desiredTop, viewport.height - bubble.height - margin)),
  };
}

export function WorkspaceTooltip({
  label,
  children,
}: {
  label: string;
  children: ReactElement<{ "aria-describedby"?: string }>;
}) {
  const id = useId();
  const anchor = useRef<HTMLSpanElement>(null);
  const bubble = useRef<HTMLDivElement>(null);
  const hover = useRef(false);
  const focus = useRef(false);
  const touch = useRef(false);
  const leaveTimer = useRef<ReturnType<typeof setTimeout>>();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);

  function closeAfterLeave() {
    clearTimeout(leaveTimer.current);
    leaveTimer.current = setTimeout(() => {
      if (!hover.current && !focus.current) setOpen(false);
    }, 100);
  }
  useEffect(() => () => clearTimeout(leaveTimer.current), []);
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
    };
    // Hover can leave focus in the composer, outside the trigger's subtree.
    document.addEventListener("keydown", dismiss, true);
    return () => document.removeEventListener("keydown", dismiss, true);
  }, [open]);
  useLayoutEffect(() => {
    if (!open) {
      setPosition(null);
      return;
    }
    const place = () => {
      if (!anchor.current || !bubble.current) return;
      setPosition(
        positionWorkspaceTooltip(
          anchor.current.getBoundingClientRect(),
          bubble.current.getBoundingClientRect(),
          {
            width: window.innerWidth,
            height: window.innerHeight,
          },
        ),
      );
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, label]);

  return (
    <span
      ref={anchor}
      className="aw-tooltip-anchor"
      onClickCapture={() => setOpen(false)}
      onPointerDown={(event) => {
        touch.current = event.pointerType === "touch";
        if (touch.current) setOpen(false);
      }}
      onPointerUp={() => {
        touch.current = false;
      }}
      onPointerCancel={() => {
        touch.current = false;
      }}
      onPointerEnter={(event) => {
        if (event.pointerType === "touch") return;
        touch.current = false;
        hover.current = true;
        clearTimeout(leaveTimer.current);
        setOpen(true);
      }}
      onPointerLeave={() => {
        hover.current = false;
        closeAfterLeave();
      }}
      onFocus={(event) => {
        focus.current =
          !touch.current &&
          event.target instanceof HTMLElement &&
          event.target.matches(":focus-visible");
        if (focus.current) setOpen(true);
      }}
      onBlur={(event) => {
        if (event.currentTarget.contains(event.relatedTarget)) return;
        focus.current = false;
        closeAfterLeave();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
        }
      }}
    >
      {cloneElement(children, {
        "aria-describedby":
          [children.props["aria-describedby"], open ? id : undefined].filter(Boolean).join(" ") ||
          undefined,
      })}
      {open &&
        createPortal(
          <div
            ref={bubble}
            id={id}
            role="tooltip"
            className="aw-workspace-tooltip"
            style={{
              left: position?.left ?? 0,
              top: position?.top ?? 0,
              visibility: position ? "visible" : "hidden",
            }}
            onPointerEnter={() => {
              hover.current = true;
              clearTimeout(leaveTimer.current);
            }}
            onPointerLeave={() => {
              hover.current = false;
              closeAfterLeave();
            }}
          >
            {label}
          </div>,
          document.body,
        )}
    </span>
  );
}

interface IconButtonProps extends Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "children" | "title"
> {
  label: string;
  tooltip?: string;
  children: ReactNode;
}

export const WorkspaceIconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  function WorkspaceIconButton(
    { label, tooltip, className = "aw-icon", type = "button", children, ...props },
    ref,
  ) {
    return (
      <WorkspaceTooltip label={tooltip || label}>
        <button ref={ref} type={type} className={className} aria-label={label} {...props}>
          {children}
        </button>
      </WorkspaceTooltip>
    );
  },
);
