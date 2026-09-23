import { Cable } from "lucide-react";
import WorkbuddyAccessCard from "../components/WorkbuddyAccessCard";
import { ProductPage } from "../components/ProductLayout";

export default function WorkbuddyAccessPage() {
  return (
    <ProductPage className="workbuddy-access-page">
      <header className="product-page-header">
        <span className="product-page-eyebrow">
          <Cable size={14} aria-hidden="true" />
          个人设置
        </span>
        <h1>MCP 接入</h1>
        <p>管理智能体平台的 MCP 配置和操作权限；连接状态以最近一次真实调用为准。</p>
      </header>
      <WorkbuddyAccessCard />
    </ProductPage>
  );
}
