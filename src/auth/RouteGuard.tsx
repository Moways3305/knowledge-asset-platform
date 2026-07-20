import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import LoadingError from "../components/LoadingError";
import { useAuth } from "./AuthContext";
import { type Capability } from "./permissions";

// 页面级轻量守卫：在渲染页面正文（及其数据请求）之前先判定当前身份是否有该入口权限。
// 无权时直接渲染温和的「无此入口」态并提供返回工作台的出口，绝不让无权页面先发一堆
// 请求再显示「加载失败 / 404」，也不暴露接口路径 / HTTP code / denied_reason 等技术细节。
// 后端仍是权威鉴权方：即便有人绕过前端直达接口，后端照常 403/404。
export default function RouteGuard({ cap, children }: { cap: Capability; children: ReactNode }) {
  const { status, capabilities } = useAuth();

  // 身份尚在加载：先占位，避免用未就绪的身份误判为「无权」。
  if (status === "loading") {
    return <LoadingError loading loadingTitle="加载中…" />;
  }

  if (cap(capabilities)) {
    return <>{children}</>;
  }

  // 未登录：引导登录（顶栏身份菜单），而非笼统「无权 / 加载失败」。
  if (status === "anonymous") {
    return (
      <LoadingError
        forbidden
        forbiddenTitle="请先登录"
        forbiddenDesc="登录后才能访问该功能。可在右上角身份菜单登录。"
        forbiddenAction={
          <Link className="btn-primary" to="/">
            返回今日工作台
          </Link>
        }
      />
    );
  }

  // 身份加载失败（非未登录）：温和提示，不暴露技术细节。
  if (status === "error") {
    return (
      <LoadingError
        error="identity-unavailable"
        errorTitle="身份加载失败"
        errorDescription="暂时无法确认你的身份，请稍后刷新重试。"
      />
    );
  }

  // 已登录但无该入口权限。
  return (
    <LoadingError
      forbidden
      forbiddenTitle="当前账号无此入口"
      forbiddenDesc="你当前的身份没有访问该功能的权限。如需开通，请联系平台管理员。"
      forbiddenAction={
        <Link className="btn-primary" to="/">
          返回今日工作台
        </Link>
      }
    />
  );
}
