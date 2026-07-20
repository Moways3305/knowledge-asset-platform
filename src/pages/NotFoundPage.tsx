import { Compass, CornerUpLeft, House } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

// 未知路由兜底（Routes 末尾 path="*"）。渲染在 AppLayout 的 Outlet 内，故左侧导航与
// 顶栏仍在，用户可直接换页或返回工作台。
export default function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <main className="global-state-page not-found-page" role="alert">
      <div className="global-state-graphic is-route" aria-hidden="true">
        <Compass size={30} />
        <span className="global-state-route-line" />
      </div>
      <div className="global-state-kicker">404 · 路径不可用</div>
      <h2>页面不存在或已不可用</h2>
      <p>这个入口可能已移动、被移除，或当前链接已经失效。你可以返回上一页继续操作。</p>
      <div className="global-state-actions">
        <button className="btn-small" type="button" onClick={() => navigate(-1)}>
          <CornerUpLeft size={14} aria-hidden="true" />
          返回上一页
        </button>
        <Link className="btn-small btn-small-primary" to="/">
          <House size={14} aria-hidden="true" />
          返回今日工作台
        </Link>
      </div>
    </main>
  );
}
