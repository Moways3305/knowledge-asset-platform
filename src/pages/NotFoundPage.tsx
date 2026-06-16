import { Link } from "react-router-dom";

// 未知路由兜底（Routes 末尾 path="*"）。渲染在 AppLayout 的 Outlet 内，故左侧导航与
// 顶栏仍在，用户可直接换页或返回工作台。
export default function NotFoundPage() {
  return (
    <div className="state-box" role="alert">
      <div className="state-title">页面不存在</div>
      <p className="state-desc">你访问的页面可能已被移动或删除，请检查链接是否正确。</p>
      <Link className="btn-small" to="/">
        返回今日工作台
      </Link>
    </div>
  );
}
