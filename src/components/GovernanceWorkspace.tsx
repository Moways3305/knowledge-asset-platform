import ModuleFrame from "./ModuleFrame";
import ListWorkspace from "./ListWorkspace";
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
  const view = {
    review: {
      title: "审核待办",
      description: "先核对资料、来源和适用证据，再处理当前身份可审批的事项。",
      icon: <Inbox size={21} />,
    },
    "review-completed": {
      title: "已完成审核任务",
      description: "按结果和时间查找已处理事项，查看审核记录。",
      icon: <CircleCheck size={21} />,
    },
    "original-access": {
      title: "原文访问申请",
      description: "查看申请进度，处理当前身份负责的原文审批。",
      icon: <KeyRound size={21} />,
    },
    "original-grants": {
      title: "原文授权记录",
      description: "核对授权对象、有效期与当前状态。",
      icon: <History size={21} />,
    },
  }[active];
  return (
    <ModuleFrame
      label="审批工作区"
      className="approval-module-frame"
      navigation={
        <nav className="module-navigation approval-module-navigation" aria-label="治理工作区">
          <NavLink end className={active === "review" ? "is-active" : ""} to="/review">
            <Inbox size={17} aria-hidden="true" />
            审核待办
          </NavLink>
          <NavLink
            end
            className={active === "review-completed" ? "is-active" : ""}
            to="/review/completed"
          >
            <CircleCheck size={17} aria-hidden="true" />
            已完成任务
          </NavLink>
          <NavLink
            end
            className={active === "original-access" ? "is-active" : ""}
            to="/original-access"
          >
            <KeyRound size={17} aria-hidden="true" />
            原文访问
          </NavLink>
          <NavLink
            end
            className={active === "original-grants" ? "is-active" : ""}
            to="/original-access/grants"
          >
            <History size={17} aria-hidden="true" />
            授权记录
          </NavLink>
        </nav>
      }
    >
      <ProductPage className="gw-page">
        <PageHeader
          title={view.title}
          description={view.description}
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

        <ListWorkspace>
          <div className="gw-workspace">{children}</div>
        </ListWorkspace>
      </ProductPage>
    </ModuleFrame>
  );
}
