import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ChevronRight, ListTree } from "lucide-react";

export interface WorkspaceOutlineItem {
  id: string;
  label: string;
}

/** Local section navigation. Sections remain mounted, retaining in-progress forms. */
export default function WorkspaceOutline({
  items,
  children,
  label = "本页内容",
}: {
  items: WorkspaceOutlineItem[];
  children: ReactNode;
  label?: string;
}) {
  const body = useRef<HTMLDivElement>(null);
  const [available, setAvailable] = useState<string[]>([]);
  const [active, setActive] = useState("");
  useLayoutEffect(() => {
    const ids = items
      .filter((item) => body.current?.querySelector(`[id="${item.id}"]`))
      .map((item) => item.id);
    setAvailable((previous) => (previous.join("|") === ids.join("|") ? previous : ids));
  }, [items, children]);
  const visible = items.filter((item) => available.includes(item.id));
  return (
    <div className={`workspace-outline${visible.length < 2 ? " is-single-section" : ""}`}>
      {visible.length > 1 && (
        <nav className="workspace-outline-nav" aria-label={label}>
          <span className="workspace-outline-label">
            <ListTree size={15} aria-hidden="true" />
            {label}
          </span>
          {visible.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              aria-current={active === item.id ? "location" : undefined}
              onClick={(event) => {
                event.preventDefault();
                setActive(item.id);
                const target = body.current?.querySelector<HTMLElement>(`[id="${item.id}"]`);
                target?.scrollIntoView({ block: "start", behavior: "auto" });
                target?.focus({ preventScroll: true });
              }}
            >
              {item.label}
              <ChevronRight size={14} aria-hidden="true" />
            </a>
          ))}
        </nav>
      )}
      <div className="workspace-outline-content" ref={body}>
        {children}
      </div>
    </div>
  );
}
