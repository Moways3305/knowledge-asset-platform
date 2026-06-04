import { useState, useCallback, useEffect } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { ApiError, fetchAuthMe, login, logout, startWecomOAuth, type AuthMeVM } from "../api/client";
import "./AppLayout.css";

const roleLabel: Record<string, string> = {
  boss: "Boss",
  consulting_director: "咨询总监",
  consultant: "顾问",
  admin: "管理员",
};

const projectRoleLabel: Record<string, string> = {
  project_manager: "项目经理（project_manager）",
  consultant: "顾问（consultant）",
  coach: "辅导老师（coach）",
};

const navGroups = [
  {
    label: "业务功能",
    items: [
      { to: "/knowledge", label: "知识首页" },
      { to: "/my/knowledge", label: "个人知识" },
      { to: "/upload", label: "资产化确认" },
      { to: "/review", label: "升级审核" },
      { to: "/original-access", label: "原文访问" },
      { to: "/project/current/knowledge", label: "项目看板" },
      { to: "/project/current/settings", label: "项目设置" },
    ],
  },
  {
    label: "管理后台",
    items: [
      { to: "/admin/ingest", label: "入库管理" },
      { to: "/admin/wecom-scan", label: "微盘扫描" },
      { to: "/admin/audit", label: "审计日志" },
      { to: "/admin/alert-settings", label: "告警设置" },
      { to: "/admin/permissions", label: "权限规则" },
      { to: "/admin/people", label: "人员权限" },
    ],
  },
  {
    label: "帮助",
    items: [
      { to: "/help", label: "使用说明" },
    ],
  },
];

export default function AppLayout() {
  const [authMe, setAuthMe] = useState<AuthMeVM | null>(null);
  const [projectIndex, setProjectIndex] = useState(0);
  const [loginEmail, setLoginEmail] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  const loadMe = useCallback(async () => {
    try {
      const me = await fetchAuthMe();
      setAuthMe(me);
      setProjectIndex(0);
    } catch (e) {
      setAuthMe(null);
      setAuthError(e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "身份加载失败");
    }
  }, []);

  useEffect(() => {
    void loadMe();
  }, [loadMe]);

  const handleProjectChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    setProjectIndex(Number(e.target.value));
  }, []);

  const handleLogin = useCallback(async () => {
    if (!loginEmail.trim()) return;
    setAuthBusy(true); setAuthError(null);
    try {
      const me = await login(loginEmail.trim());
      setAuthMe(me);
      setProjectIndex(0);
      setLoginEmail("");
    } catch (e) {
      setAuthError(e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "登录失败");
    } finally {
      setAuthBusy(false);
    }
  }, [loginEmail]);

  const handleWecomLogin = useCallback(async () => {
    setAuthBusy(true); setAuthError(null);
    try {
      // 后端生成 state 写短时 httpOnly cookie 并返回授权 URL；前端只做跳转，
      // 绝不接触/存储 OAuth code / state / 任何登录凭证（会话由后端 httpOnly cookie 控制）。
      const { authorize_url } = await startWecomOAuth();
      window.location.href = authorize_url;
    } catch (e) {
      setAuthError(e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "企微登录暂不可用（需后端配置 WECOM_*）");
      setAuthBusy(false);
    }
    // 成功路径会发生整页跳转，无需复位 authBusy。
  }, []);

  const handleLogout = useCallback(async () => {
    setAuthBusy(true); setAuthError(null);
    try {
      await logout();
      await loadMe(); // 登出后回到开发态回退身份（如默认顾问）
    } catch (e) {
      setAuthError(e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "登出失败");
    } finally {
      setAuthBusy(false);
    }
  }, [loadMe]);

  const projects = authMe?.projects ?? [];
  const currentProject = projects[projectIndex];
  const rolesText = (authMe?.companyRoles ?? []).map((r) => roleLabel[r] ?? r).join(" / ") || "—";

  return (
    <div className="app-layout">
      <header className="app-topbar">
        <h1>知识资产平台</h1>
        <div className="topbar-context">
          <span className="topbar-user">{authMe?.name ?? "未登录"}</span>
          <span className="topbar-separator">·</span>
          <span className="topbar-platform-roles">平台身份：{rolesText}</span>
          {projects.length > 0 ? (
            <>
              <span className="topbar-separator">·</span>
              <select className="topbar-role-select" value={projectIndex} onChange={handleProjectChange}>
                {projects.map((ctx, i) => (
                  <option key={ctx.projectId} value={i}>{ctx.projectName}</option>
                ))}
              </select>
              <span className="topbar-project-role">
                {currentProject ? (projectRoleLabel[currentProject.projectRole] ?? currentProject.projectRole) : ""}
              </span>
            </>
          ) : (
            <>
              <span className="topbar-separator">·</span>
              <span className="topbar-role-desc">无项目身份</span>
            </>
          )}
        </div>
        <div className="topbar-auth">
          <input
            className="topbar-login-input"
            type="email"
            placeholder="登录邮箱（如 boss.c@dev.local）"
            value={loginEmail}
            onChange={(e) => setLoginEmail(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void handleLogin(); }}
          />
          <button className="btn-small btn-small-primary" onClick={() => void handleLogin()} disabled={authBusy}>登录</button>
          <button className="btn-small" onClick={() => void handleWecomLogin()} disabled={authBusy}>企微登录</button>
          <button className="btn-small" onClick={() => void handleLogout()} disabled={authBusy}>登出</button>
          <span className="topbar-badge">会话身份 · 本地登录 / 企微 OAuth（需配置 WECOM_*）</span>
        </div>
        {authError && <div className="topbar-auth-error">{authError}</div>}
      </header>
      <div className="app-body">
        <nav className="app-sidebar">
          <div className="sidebar-brand">KAP</div>
          {navGroups.map((group) => (
            <div key={group.label} className="sidebar-nav-group">
              <div className="sidebar-group-label">{group.label}</div>
              <ul>
                {group.items.map((item) => (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      className={({ isActive }) => (isActive ? "active" : "")}
                    >
                      {item.label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <main className="app-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
