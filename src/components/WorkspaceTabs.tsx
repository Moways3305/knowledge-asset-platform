import { useId, useRef, type ReactNode } from "react";
import "./WorkspaceTabs.css";

/** Keeps each panel mounted so switching views does not discard edits or requests. */
export default function WorkspaceTabs({
  label,
  items,
  value,
  onChange,
}: {
  label: string;
  items: Array<{ key: string; label: string; icon?: ReactNode; content: ReactNode }>;
  value: string;
  onChange: (key: string) => void;
}) {
  const id = useId();
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  return (
    <div className="workspace-tabs">
      <div role="tablist" aria-label={label} className="workspace-tabs-nav">
        {items.map((item, index) => (
          <button
            key={item.key}
            ref={(node) => {
              buttons.current[index] = node;
            }}
            type="button"
            role="tab"
            id={`${id}-${item.key}-tab`}
            aria-controls={`${id}-${item.key}-panel`}
            aria-selected={value === item.key}
            tabIndex={value === item.key ? 0 : -1}
            onClick={() => onChange(item.key)}
            onKeyDown={(event) => {
              let next: number;
              if (event.key === "ArrowRight") next = (index + 1) % items.length;
              else if (event.key === "ArrowLeft") next = (index - 1 + items.length) % items.length;
              else if (event.key === "Home") next = 0;
              else if (event.key === "End") next = items.length - 1;
              else return;
              event.preventDefault();
              onChange(items[next].key);
              buttons.current[next]?.focus();
            }}
          >
            {item.icon}
            {item.label}
          </button>
        ))}
      </div>
      {items.map((item) => (
        <div
          key={item.key}
          role="tabpanel"
          id={`${id}-${item.key}-panel`}
          aria-labelledby={`${id}-${item.key}-tab`}
          hidden={value !== item.key}
          tabIndex={0}
          className="workspace-tab-panel"
        >
          {item.content}
        </div>
      ))}
    </div>
  );
}
