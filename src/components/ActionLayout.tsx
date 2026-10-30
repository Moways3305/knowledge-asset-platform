import {
  useCallback,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { ChevronDown } from "lucide-react";
import Button from "./Button";
import "./ActionLayout.css";

export function ActionGroup({
  primary,
  secondary,
  children,
  label,
  className = "",
}: {
  primary?: ReactNode;
  secondary?: ReactNode;
  children?: ReactNode;
  label?: string;
  className?: string;
}) {
  return (
    <div
      className={`action-group ${className}`.trim()}
      role={label ? "group" : undefined}
      aria-label={label}
    >
      {secondary && <div className="action-group-secondary">{secondary}</div>}
      {children}
      {primary && <div className="action-group-primary">{primary}</div>}
    </div>
  );
}

export function FormActions({
  children,
  description,
  sticky = false,
  className = "",
}: {
  children: ReactNode;
  description?: ReactNode;
  sticky?: boolean;
  className?: string;
}) {
  return (
    <div className={`form-actions ${sticky ? "is-sticky" : ""} ${className}`.trim()}>
      {description && <div className="form-actions-description">{description}</div>}
      <div className="form-actions-controls">{children}</div>
    </div>
  );
}

const ACTIONS = 'button:not(:disabled), a[href]:not([aria-disabled="true"])';

/** A disclosure containing normal buttons/links, with their normal Tab behavior. */
export function ActionMenu({
  label = "更多操作",
  ariaLabel,
  children,
  disabled = false,
}: {
  label?: string;
  ariaLabel?: string;
  children: ReactNode;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<CSSProperties>({ visibility: "hidden" });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    if (disabled) {
      setOpen(false);
      return;
    }
    const trigger = triggerRef.current;
    const panel = panelRef.current;
    if (!trigger || !panel) return;

    const place = () => {
      const anchor = trigger.getBoundingClientRect();
      const viewport = window.visualViewport;
      const leftEdge = viewport?.offsetLeft ?? 0;
      const topEdge = viewport?.offsetTop ?? 0;
      const width = viewport?.width ?? window.innerWidth;
      const height = viewport?.height ?? window.innerHeight;
      const gap = 6;
      const inset = 12;
      const panelWidth = Math.min(Math.max(anchor.width, 200), Math.max(0, width - inset * 2));
      const below = Math.max(0, topEdge + height - inset - anchor.bottom - gap);
      const above = Math.max(0, anchor.top - topEdge - inset - gap);
      const naturalHeight = panel.scrollHeight + 2;
      const useAbove = below < Math.min(naturalHeight, 180) && above > below;
      const maxHeight = Math.max(0, useAbove ? above : below);
      const renderedHeight = Math.min(naturalHeight, maxHeight);
      setPosition({
        width: panelWidth,
        left: Math.max(
          leftEdge + inset,
          Math.min(anchor.right - panelWidth, leftEdge + width - panelWidth - inset),
        ),
        top: useAbove
          ? Math.max(topEdge + inset, anchor.top - gap - renderedHeight)
          : anchor.bottom + gap,
        maxHeight,
      });
    };
    const outside = (event: Event) => {
      if (
        event.target instanceof Node &&
        !panel.contains(event.target) &&
        !trigger.contains(event.target)
      ) {
        close(false);
      }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      close(true);
    };
    place();
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("focusin", outside);
    document.addEventListener("keydown", escape, true);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    window.visualViewport?.addEventListener("resize", place);
    window.visualViewport?.addEventListener("scroll", place);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    observer?.observe(trigger);
    observer?.observe(panel);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("focusin", outside);
      document.removeEventListener("keydown", escape, true);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      window.visualViewport?.removeEventListener("resize", place);
      window.visualViewport?.removeEventListener("scroll", place);
      observer?.disconnect();
    };
  }, [open, disabled, close]);

  useLayoutEffect(() => {
    if (open && !disabled && position.visibility !== "hidden") {
      panelRef.current?.querySelector<HTMLElement>(ACTIONS)?.focus();
    }
  }, [open, disabled, position.visibility]);

  // Keep portaled actions inside a surrounding dialog's focus boundary.
  const portalTarget = triggerRef.current?.closest('[role="dialog"]') ?? document.body;
  return (
    <>
      <Button
        ref={triggerRef}
        disabled={disabled}
        aria-label={ariaLabel ?? label}
        aria-expanded={open && !disabled}
        aria-controls={open && !disabled ? panelId : undefined}
        className="action-menu-trigger"
        onClick={() => {
          setPosition({ visibility: "hidden" });
          setOpen((value) => !value);
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && !open) {
            event.preventDefault();
            setPosition({ visibility: "hidden" });
            setOpen(true);
          }
        }}
      >
        {label}
        <ChevronDown size={15} aria-hidden="true" />
      </Button>
      {open &&
        !disabled &&
        createPortal(
          <div
            ref={panelRef}
            id={panelId}
            className="action-menu-panel"
            style={position}
            role="group"
            aria-label={ariaLabel ?? label}
            onKeyDown={(event) => {
              if (event.key !== "Tab") return;
              const actions = [...event.currentTarget.querySelectorAll<HTMLElement>(ACTIONS)];
              if (event.shiftKey && document.activeElement === actions[0]) {
                event.preventDefault();
                close(true);
              } else if (
                !event.shiftKey &&
                document.activeElement === actions[actions.length - 1]
              ) {
                // Resume the page's normal Tab order after the trigger, rather than
                // jumping to the end of the document where this portal is mounted.
                event.preventDefault();
                const controls = [
                  ...document.querySelectorAll<HTMLElement>(
                    'button, a[href], input:not([type="hidden"]), select, textarea, [tabindex]',
                  ),
                ].filter((element) => {
                  if (
                    event.currentTarget.contains(element) ||
                    element.tabIndex < 0 ||
                    element.matches(':disabled, [aria-disabled="true"]') ||
                    element.closest("[hidden], [inert]")
                  )
                    return false;
                  for (
                    let parent: HTMLElement | null = element;
                    parent;
                    parent = parent.parentElement
                  ) {
                    const style = getComputedStyle(parent);
                    if (style.display === "none" || style.visibility === "hidden") return false;
                  }
                  return true;
                });
                const next = controls[controls.indexOf(triggerRef.current!) + 1];
                close(true);
                next?.focus();
              }
            }}
            onClick={(event) => {
              const action = event.target instanceof Element ? event.target.closest(ACTIONS) : null;
              if (action && event.currentTarget.contains(action)) close(true);
            }}
          >
            <div className="action-menu-content">{children}</div>
          </div>,
          portalTarget,
        )}
    </>
  );
}
