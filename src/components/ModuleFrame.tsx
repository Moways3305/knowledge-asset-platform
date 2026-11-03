import type { ReactNode } from "react";
import "./KnowledgeModuleFrame.css";

/** Persistent module navigation; changing the task only replaces the work surface. */
export default function ModuleFrame({
  navigation,
  children,
  label,
  className = "",
}: {
  navigation: ReactNode;
  children: ReactNode;
  label: string;
  className?: string;
}) {
  return (
    <div className={`knowledge-module-frame module-frame ${className}`}>
      <aside className="kbl-navigation" aria-label={label}>
        {navigation}
      </aside>
      <div className="knowledge-module-content">{children}</div>
    </div>
  );
}
