import type { ReactNode } from "react";
import "./ListWorkspace.css";

/** One list surface: tabs, filters, results and pagination share a single rhythm. */
export default function ListWorkspace({
  children,
  tabs,
  className = "",
  label,
}: {
  children: ReactNode;
  tabs?: ReactNode;
  className?: string;
  label?: string;
}) {
  return (
    <section className={`list-workspace ${className}`} aria-label={label}>
      {tabs && <div className="list-workspace-tabs">{tabs}</div>}
      {children}
    </section>
  );
}
