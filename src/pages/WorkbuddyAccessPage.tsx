import WorkspaceOutline from "../components/WorkspaceOutline";
import { Cable } from "lucide-react";
import WorkbuddyAccessCard from "../components/WorkbuddyAccessCard";
import McpOAuthGrants from "../components/McpOAuthGrants";
import { PageHeader, ProductPage } from "../components/ProductLayout";

export default function WorkbuddyAccessPage() {
  return (
    <ProductPage className="workbuddy-access-page">
      <PageHeader
        title="MCP 接入"
        eyebrow={
          <>
            <Cable size={14} aria-hidden="true" /> 个人设置
          </>
        }
        description="管理智能体平台的 MCP 配置和操作权限；连接状态以最近一次真实调用为准。"
      />
      <WorkspaceOutline
        items={[
          { id: "mcp-connection", label: "连接配置" },
          { id: "mcp-authorizations", label: "授权管理" },
        ]}
      >
        <section id="mcp-connection" tabIndex={-1} className="settings-content-section">
          <WorkbuddyAccessCard />
        </section>
        <section id="mcp-authorizations" tabIndex={-1} className="settings-content-section">
          <McpOAuthGrants />
        </section>
      </WorkspaceOutline>
    </ProductPage>
  );
}
