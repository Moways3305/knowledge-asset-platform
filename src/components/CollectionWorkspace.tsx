import type { ReactNode } from "react";

/** Keep filters and results in one workspace without remounting either region. */
export default function CollectionWorkspace({
  filters,
  children,
  label = "筛选与范围",
  variant = "toolbar",
}: {
  filters: ReactNode;
  children: ReactNode;
  label?: string;
  variant?: "toolbar" | "sidebar";
}) {
  return (
    <div className={`collection-workspace is-${variant}`}>
      <aside className="collection-workspace-filters" aria-label={label}>
        <h3 className="collection-workspace-label">{label}</h3>
        {filters}
      </aside>
      <div className="collection-workspace-results">{children}</div>
    </div>
  );
}
