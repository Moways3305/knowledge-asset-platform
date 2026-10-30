import { Link } from "react-router-dom";
import "./ProjectWorkspaceNav.css";

export default function ProjectWorkspaceNav({
  projectId,
  current,
  canManage = false,
  canViewKnowledge = true,
  onAsk,
  askOpen = false,
}: {
  projectId: string;
  current: "overview" | "knowledge" | "settings";
  canManage?: boolean;
  canViewKnowledge?: boolean;
  onAsk?: () => void;
  askOpen?: boolean;
}) {
  const base = `/project/${encodeURIComponent(projectId)}`;
  return (
    <nav className="project-workspace-nav" aria-label="项目空间导航">
      {canViewKnowledge && (
        <Link to={`${base}/knowledge`} aria-current={current === "knowledge" ? "page" : undefined}>
          项目知识库
        </Link>
      )}
      {onAsk ? (
        <button type="button" aria-haspopup="dialog" aria-expanded={askOpen} onClick={onAsk}>
          项目问答
        </button>
      ) : (
        <Link to={base} aria-current={current === "overview" ? "page" : undefined}>
          项目问答
        </Link>
      )}
      {canManage && (
        <Link to={`${base}/settings`} aria-current={current === "settings" ? "page" : undefined}>
          项目设置
        </Link>
      )}
    </nav>
  );
}
