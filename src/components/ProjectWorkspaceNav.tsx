import { Link } from "react-router-dom";
import "./ProjectWorkspaceNav.css";

export default function ProjectWorkspaceNav({
  projectId,
  current,
  canManage = false,
  canViewKnowledge = true,
}: {
  projectId: string;
  current: "overview" | "knowledge" | "qa" | "settings";
  canManage?: boolean;
  canViewKnowledge?: boolean;
}) {
  const base = `/project/${encodeURIComponent(projectId)}`;
  return (
    <nav className="project-workspace-nav" aria-label="项目空间导航">
      <Link to={base} aria-current={current === "overview" ? "page" : undefined}>
        项目概览
      </Link>
      {canViewKnowledge && (
        <Link to={`${base}/knowledge`} aria-current={current === "knowledge" ? "page" : undefined}>
          项目知识库
        </Link>
      )}
      <Link to={`${base}?view=qa`} aria-current={current === "qa" ? "page" : undefined}>
        项目问答
      </Link>
      {canManage && (
        <Link to={`${base}/settings`} aria-current={current === "settings" ? "page" : undefined}>
          项目设置
        </Link>
      )}
    </nav>
  );
}
