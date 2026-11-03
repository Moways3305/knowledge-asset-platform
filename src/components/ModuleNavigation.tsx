import { Link, NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import {
  knowledgeEntries,
  managementEntries,
  permittedEntries,
  workspaceForPath,
} from "../navigation/workspaces";
import { ActionMenu } from "./ActionLayout";

/** Module navigation belongs to the content workspace, not the global rail. */
export default function ModuleNavigation({
  embedded = false,
  compact = false,
  rail = false,
}: {
  embedded?: boolean;
  compact?: boolean;
  rail?: boolean;
}) {
  const { capabilities } = useAuth();
  const { pathname } = useLocation();
  const workspace = workspaceForPath(pathname);
  if (!rail && workspace === "knowledge") {
    if (
      !embedded &&
      (pathname === "/knowledge" || pathname.startsWith("/knowledge/") || pathname === "/upload")
    )
      return null;
    return (
      <nav className="module-navigation knowledge-module-navigation" aria-label="知识库导航">
        {permittedEntries(knowledgeEntries, capabilities)
          .filter((entry) => entry.to !== "/upload")
          .map((entry) => (
            <NavLink key={entry.to} to={entry.to} end>
              {entry.label}
            </NavLink>
          ))}
      </nav>
    );
  }
  if (!rail && workspace !== "admin") return null;
  const entries = permittedEntries(managementEntries, capabilities);
  if (!entries.length) return null;
  const selected = entries.find((entry) => entry.to === pathname);
  return (
    <nav
      className={`module-navigation management-module-navigation ${compact ? "is-compact" : ""} ${rail ? "is-rail-menu" : ""}`}
      aria-label="管理模块"
    >
      <ActionMenu
        label={rail ? "" : (selected?.label ?? "选择管理模块")}
        ariaLabel="切换管理模块"
        placement={rail ? "right" : "bottom"}
      >
        {Array.from(new Set(entries.map((entry) => entry.section))).map((section) => (
          <div className="module-menu-section" key={section}>
            <strong>{section}</strong>
            {entries
              .filter((entry) => entry.section === section)
              .map((entry) => (
                <Link
                  key={entry.to}
                  to={entry.to}
                  aria-current={entry.to === pathname ? "page" : undefined}
                >
                  {entry.label}
                </Link>
              ))}
          </div>
        ))}
      </ActionMenu>
    </nav>
  );
}
