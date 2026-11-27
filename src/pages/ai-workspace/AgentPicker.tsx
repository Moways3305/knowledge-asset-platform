import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { createPortal } from "react-dom";
import { Bot, Check, ChevronDown, MessageCircle } from "lucide-react";
import type { WorkspaceAgent } from "../../api/aiWorkspace";
import { WorkspaceIconButton } from "./WorkspaceTooltip";
import "./AgentPicker.css";

interface AgentPickerProps {
  agents: WorkspaceAgent[] | undefined;
  value: string | null;
  disabled?: boolean;
  onChange: (value: string | null) => void;
}
interface MenuPosition {
  left: number;
  top: number;
  width: number;
  maxHeight: number;
}

/** A session is bound only on first send; this picker edits the unsent draft. */
export default function AgentPicker({
  agents,
  value,
  disabled = false,
  onChange,
}: AgentPickerProps) {
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const items = useRef<(HTMLButtonElement | null)[]>([]);
  const id = useId();
  const [open, setOpen] = useState(false);
  const [portal, setPortal] = useState<HTMLElement | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [position, setPosition] = useState<MenuPosition | null>(null);
  const selected = agents?.find((agent) => agent.key === value);
  const choices = [
    { key: null, label: "通用对话", description: "不指定智能体，直接与博维 AI 对话" },
    ...(agents ?? []),
  ];
  const hasPosition = position !== null;
  const selectedIndex = Math.max(
    0,
    choices.findIndex((choice) => choice.key === value),
  );
  const close = useCallback((restoreFocus = true) => {
    setOpen(false);
    setPosition(null);
    if (restoreFocus) trigger.current?.focus({ preventScroll: true });
  }, []);

  function show(index = selectedIndex) {
    if (disabled || !trigger.current) return;
    setPortal(trigger.current.closest<HTMLElement>(".ai-workspace") ?? document.body);
    setActiveIndex(index);
    setPosition(null);
    setOpen(true);
  }
  function choose(next: string | null) {
    if (disabled) return;
    onChange(next);
    close();
  }

  useEffect(() => {
    if (disabled) close(false);
  }, [disabled, close]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!(event.target instanceof Node)) return;
      if (trigger.current?.contains(event.target) || menu.current?.contains(event.target)) return;
      // Restore on background clicks. Native pointer focus may then move to the
      // outside control the user actually clicked; never steal that focus back.
      close();
    };
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      close();
    };
    const focusOutside = (event: FocusEvent) => {
      if (!(event.target instanceof Node)) return;
      if (trigger.current?.contains(event.target) || menu.current?.contains(event.target)) return;
      close(false);
    };
    document.addEventListener("pointerdown", outside, true);
    // Capture also closes the menu when an icon's hover tooltip consumes Escape.
    document.addEventListener("keydown", escape, true);
    document.addEventListener("focusin", focusOutside);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("keydown", escape, true);
      document.removeEventListener("focusin", focusOutside);
    };
  }, [open, close]);

  useLayoutEffect(() => {
    if (!open || !menu.current || !trigger.current) return;
    const place = () => {
      if (!trigger.current || !menu.current) return;
      const anchor = trigger.current.getBoundingClientRect();
      const viewport = window.visualViewport;
      const viewportWidth = viewport?.width ?? window.innerWidth;
      const viewportHeight = viewport?.height ?? window.innerHeight;
      const x = viewport?.offsetLeft ?? 0;
      const y = viewport?.offsetTop ?? 0;
      const margin = 12;
      const gap = 8;
      const width = Math.max(0, Math.min(320, viewportWidth - margin * 2));
      const topEdge = y + margin;
      const bottomEdge = y + viewportHeight - margin;
      const above = Math.max(0, Math.min(anchor.top - gap, bottomEdge) - topEdge);
      const below = Math.max(0, bottomEdge - Math.max(anchor.bottom + gap, topEdge));
      const naturalHeight = menu.current.scrollHeight + 2;
      const preferredHeight = Math.min(340, naturalHeight);
      const useAbove = above >= preferredHeight || above >= below;
      // A soft keyboard can obscure the trigger entirely. Keep the list inside
      // the remaining visual viewport instead of shrinking it to zero height.
      const available =
        Math.max(above, below) < 80 ? Math.max(0, bottomEdge - topEdge) : useAbove ? above : below;
      const maxHeight = Math.min(340, available);
      const height = Math.min(naturalHeight, maxHeight);
      const preferredTop = useAbove ? anchor.top - gap - height : anchor.bottom + gap;
      setPosition({
        width,
        maxHeight,
        left: Math.max(x + margin, Math.min(anchor.left, x + viewportWidth - margin - width)),
        top: Math.max(topEdge, Math.min(preferredTop, bottomEdge - height)),
      });
    };
    place();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    observer?.observe(menu.current);
    observer?.observe(trigger.current);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    window.visualViewport?.addEventListener("resize", place);
    window.visualViewport?.addEventListener("scroll", place);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      window.visualViewport?.removeEventListener("resize", place);
      window.visualViewport?.removeEventListener("scroll", place);
    };
  }, [open, agents, value]);

  useLayoutEffect(() => {
    if (!open || !hasPosition) return;
    const index = Math.min(activeIndex, choices.length - 1);
    if (index !== activeIndex) setActiveIndex(index);
    else {
      const item = items.current[index];
      const container = menu.current;
      item?.focus({ preventScroll: true });
      if (!item || !container || !container.clientHeight) return;
      const itemBounds = item.getBoundingClientRect();
      const top = container.getBoundingClientRect().top + container.clientTop;
      const bottom = top + container.clientHeight;
      // Keep keyboard focus visible inside the menu without scrolling the page
      // or the conversation behind this portal.
      if (itemBounds.top < top || itemBounds.height > container.clientHeight) {
        container.scrollTop += itemBounds.top - top;
      } else if (itemBounds.bottom > bottom) {
        container.scrollTop += itemBounds.bottom - bottom;
      }
    }
  }, [open, hasPosition, activeIndex, choices.length, position?.maxHeight]);

  function onTriggerKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (disabled) return;
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
      event.preventDefault();
      show(event.key === "ArrowUp" ? choices.length - 1 : selectedIndex);
    }
  }
  function onMenuKey(event: KeyboardEvent<HTMLDivElement>) {
    const count = choices.length;
    const movement: Record<string, number> = {
      ArrowDown: (activeIndex + 1) % count,
      ArrowUp: (activeIndex - 1 + count) % count,
      Home: 0,
      End: count - 1,
    };
    if (event.key in movement) {
      event.preventDefault();
      setActiveIndex(movement[event.key]);
    } else if (event.key === "Tab") {
      // A portal is outside the composer's DOM order. Explicitly move to the
      // trigger's adjacent tab stop, without trapping Tab inside the menu.
      const controls = [
        ...document.querySelectorAll<HTMLElement>(
          'button, a[href], input, select, textarea, [tabindex], [contenteditable="true"]',
        ),
      ]
        .filter((element) => {
          if (
            element.tabIndex < 0 ||
            element.matches(":disabled") ||
            menu.current?.contains(element)
          )
            return false;
          if (element.closest('[hidden], [inert], [aria-hidden="true"]')) return false;
          for (
            let ancestor: HTMLElement | null = element;
            ancestor;
            ancestor = ancestor.parentElement
          ) {
            const style = window.getComputedStyle(ancestor);
            if (style.display === "none" || style.visibility === "hidden") return false;
          }
          return true;
        })
        .sort((a, b) => (a.tabIndex || Infinity) - (b.tabIndex || Infinity));
      const current = controls.findIndex((element) => element === trigger.current);
      const adjacent = controls[current + (event.shiftKey ? -1 : 1)];
      if (current >= 0 && adjacent) {
        event.preventDefault();
        close(false);
        adjacent.focus({ preventScroll: true });
      } else {
        close();
      }
    }
  }

  const name = selected?.label ?? (agents ? "智能体不可用" : "智能体加载中");
  const tooltip = value ? `${name}，点击更换；选择通用对话可移除` : "添加智能体";
  return (
    <>
      <WorkspaceIconButton
        ref={trigger}
        className="aw-icon aw-agent-picker-trigger"
        label="添加智能体"
        tooltip={tooltip}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open && !disabled}
        aria-controls={open && !disabled ? id : undefined}
        data-selected={Boolean(value)}
        onClick={() => (open ? close() : show())}
        onKeyDown={onTriggerKey}
      >
        <Bot size={16} aria-hidden="true" />
        {value && (
          <>
            <span className="aw-agent-picker-name">{name}</span>
            <ChevronDown size={12} aria-hidden="true" />
          </>
        )}
      </WorkspaceIconButton>
      {open &&
        !disabled &&
        portal &&
        createPortal(
          <div
            ref={menu}
            id={id}
            role="menu"
            aria-label="选择智能体"
            className="aw-agent-picker-menu"
            onKeyDown={onMenuKey}
            style={{ ...position, visibility: position ? "visible" : "hidden" }}
          >
            <div className="aw-agent-picker-heading" role="presentation">
              选择智能体
            </div>
            {value && !selected && (
              <p className="aw-agent-picker-notice" role="status">
                {agents ? "此前选择的智能体不可用，可切回通用对话。" : "正在读取智能体列表…"}
              </p>
            )}
            {choices.map((choice, index) => (
              <button
                ref={(element) => {
                  items.current[index] = element;
                }}
                key={choice.key ?? "general"}
                type="button"
                role="menuitemradio"
                aria-checked={choice.key === value}
                aria-labelledby={`${id}-label-${index}`}
                aria-describedby={`${id}-description-${index}`}
                tabIndex={index === activeIndex ? 0 : -1}
                className="aw-agent-picker-option"
                onFocus={() => setActiveIndex(index)}
                onClick={() => choose(choice.key)}
              >
                {choice.key ? (
                  <Bot size={17} aria-hidden="true" />
                ) : (
                  <MessageCircle size={17} aria-hidden="true" />
                )}
                <span className="aw-agent-picker-copy">
                  <span id={`${id}-label-${index}`}>{choice.label}</span>
                  <small id={`${id}-description-${index}`}>{choice.description}</small>
                </span>
                {choice.key === value && (
                  <Check size={15} className="aw-agent-picker-check" aria-hidden="true" />
                )}
              </button>
            ))}
            {!agents && !value && (
              <p className="aw-agent-picker-notice" role="status">
                正在读取智能体列表…
              </p>
            )}
            {agents?.length === 0 && (
              <p className="aw-agent-picker-notice" role="status">
                暂无可用智能体，可以继续通用对话。
              </p>
            )}
          </div>,
          portal,
        )}
    </>
  );
}
