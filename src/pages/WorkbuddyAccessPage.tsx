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
        <h1>WorkBuddy 接入</h1>
        <p>下载连接器并管理接入配置；成功连接状态只以平台最近一次真实连接记录为准。</p>
      </header>
      <WorkbuddyAccessCard />
    </ProductPage>
  );
}
