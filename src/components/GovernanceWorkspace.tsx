import type { ReactNode } from "react";
import { RefreshCw, Inbox, CircleCheck, KeyRound, History } from "lucide-react";
import { NavLink } from "react-router-dom";
import { PageHeader, ProductPage } from "./ProductLayout";
import "./GovernanceWorkspace.css";

interface GovernanceWorkspaceProps {
  active: "review" | "review-completed" | "original-access" | "original-grants";
  loading: boolean;
  onRefresh: () => void;
  children: ReactNode;
}

export default function GovernanceWorkspace({
  active,
  loading,
  onRefresh,
  children,
}: GovernanceWorkspaceProps) {
  return (
    <ProductPage className="gw-page">
      <PageHeader
        title="审核与原文访问"
        actions={
          <button
            className="product-button is-secondary is-small gw-refresh"
            type="button"
            disabled={loading}
            onClick={onRefresh}
          >
            <RefreshCw size={14} aria-hidden="true" />
            {loading ? "正在刷新" : "刷新"}
          </button>
        }
      />

      <nav className="gw-route-tabs" aria-label="治理工作区">
        <NavLink end className={active === "review" ? "is-active" : ""} to="/review">
          <Inbox size={17} aria-hidden="true" />
          审核待办
        </NavLink>
        <NavLink
          className={active === "review-completed" ? "is-active" : ""}
          to="/review/completed"
        >
          <CircleCheck size={17} aria-hidden="true" />
          已完成任务
        </NavLink>
        <NavLink className={active === "original-access" ? "is-active" : ""} to="/original-access">
          <KeyRound size={17} aria-hidden="true" />
          原文访问
        </NavLink>
        <NavLink
          className={active === "original-grants" ? "is-active" : ""}
          to="/original-access/grants"
        >
          <History size={17} aria-hidden="true" />
          授权记录
        </NavLink>
      </nav>

      <div className="gw-workspace">{children}</div>
    </ProductPage>
  );
}
