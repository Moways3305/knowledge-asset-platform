import { useState, useCallback, useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { ChevronDown, LogOut, UserRound, Building2, Check } from "lucide-react";
import { ApiError } from "../api/http";
import { login, logout } from "../api/auth";
import { useAuth } from "../auth/AuthContext";
import { startWecomOAuth } from "../api/admin";

const roleLabel: Record<string, string> = {
  boss: "总经理",
  consulting_director: "咨询总监",
  consultant: "顾问",
  admin: "管理员",
};

const projectRoleLabel: Record<string, string> = {
  project_manager: "项目经理",
  consultant: "顾问",
  coach: "辅导老师",
};

export function wecomOAuthModeForUserAgent(userAgent: string): "client" | "web_qr" {
  return /wxwork/i.test(userAgent) ? "client" : "web_qr";
}

/**
 * 身份与会话入口。所有登录/登出/企微/切换账号控件与错误反馈都收纳在一个
 * 固定宽度的浮层里，因此长邮箱、长项目名、失败文案都只在浮层内换行，
 * 绝不撑坏顶部命令栏（解决旧顶栏登录失败变形问题）。
 */
export default function IdentityMenu() {
  // 身份来自全局 AuthProvider（与导航过滤、页面守卫共享同一份 /auth/me）。
  const { authMe, status, setAuthMe, reload } = useAuth();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [projectIndex, setProjectIndex] = useState(0);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // 从 URL 解析当前项目 ID，用于在项目列表中高亮当前项目。
  const urlProjectId = (() => {
    const m = location.pathname.match(/^\/project\/([0-9a-f-]{36})/i);
    return m ? m[1] : null;
  })();

  // 身份加载失败（非未登录）时在浮层内提示，不影响顶栏布局。
  useEffect(() => {
    setAuthError(status === "error" ? "身份加载失败" : null);
    if (status === "authenticated") {
      setProjectIndex(0);
    }
  }, [status]);

  // 点击浮层外 / Esc 关闭。
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const handleLogin = useCallback(async () => {
    if (!loginEmail.trim()) {
      setAuthError("请输入登录邮箱");
      return;
    }
    setAuthBusy(true);
    setAuthError(null);
    try {
      const me = await login(loginEmail.trim(), loginPassword || undefined);
      setAuthMe(me);
      setProjectIndex(0);
      setLoginEmail("");
      setLoginPassword(""); // 登录后立即清空密码，绝不回显
    } catch (e) {
      setAuthError(
        e instanceof ApiError && e.status === 403 && e.deniedReason === "auth_password_required"
          ? "请输入密码登录"
          : e instanceof ApiError && e.status === 401
            ? "邮箱或密码错误"
            : "登录失败，请稍后重试",
      );
    } finally {
      setAuthBusy(false);
    }
  }, [loginEmail, loginPassword, setAuthMe]);

  const handleWecomLogin = useCallback(async () => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      // 后端生成 state 写短时 httpOnly cookie 并返回授权 URL；前端只做跳转，
      // 绝不接触/存储 OAuth code / state（会话由后端 httpOnly cookie 控制）。
      const { authorize_url } = await startWecomOAuth(
        wecomOAuthModeForUserAgent(window.navigator.userAgent),
      );
      window.location.href = authorize_url;
    } catch (e) {
      setAuthError(e instanceof ApiError ? "企业微信登录暂不可用" : "企业微信登录暂不可用");
      setAuthBusy(false);
    }
  }, []);

  const handleLogout = useCallback(async () => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      await logout();
      await reload();
    } catch {
      setAuthError("登出失败，请稍后重试");
    } finally {
      setAuthBusy(false);
    }
  }, [reload]);

  const projects = authMe?.projects ?? [];
  const currentProject = projects[projectIndex];
  const roles = authMe?.companyRoles ?? [];
  const name = authMe?.name ?? "未登录";
  const email = authMe?.email ?? "";
  const initial = (authMe?.name ?? "·").trim().charAt(0) || "·";
  const showLoginForm = !authMe;

  // 区分当前项目和其他项目，便于用户理解"当前在哪个项目"。
  const activeProject = urlProjectId
    ? (projects.find((p) => p.projectId === urlProjectId) ?? currentProject)
    : currentProject;
  const rolesText = roles.map((r) => roleLabel[r] ?? r).join(" / ") || "—";

  return (
    <div className="idm" ref={wrapRef}>
      <button
        type="button"
        className={`idm-trigger ${open ? "is-open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className={`idm-avatar ${authMe ? "" : "idm-avatar-anon"}`}>{initial}</span>
        <span className="idm-trigger-text">
          <span className="idm-trigger-name">{name}</span>
          <span className="idm-trigger-role">{authMe ? rolesText : "点击登录"}</span>
        </span>
        <ChevronDown size={15} className="idm-chevron" />
      </button>

      {open && (
        <div className="idm-panel" role="dialog">
          <div className="idm-panel-head">
            <span className={`idm-avatar idm-avatar-lg ${authMe ? "" : "idm-avatar-anon"}`}>
              {initial}
            </span>
            <div className="idm-panel-id">
              <div className="idm-panel-name">{name}</div>
              {email && <div className="idm-panel-email">{email}</div>}
              <div className="idm-panel-roles">
                <UserRound size={12} /> 平台身份：
                <span className="idm-role-badges">
                  {roles.length > 0 ? (
                    roles.map((r) => (
                      <span key={r} className={`idm-role-badge idm-role-${r}`}>
                        {roleLabel[r] ?? r}
                      </span>
                    ))
                  ) : (
                    <span className="idm-role-badge idm-role-none">无</span>
                  )}
                </span>
              </div>
            </div>
          </div>

          {projects.length > 0 ? (
            <div className="idm-project">
              <label className="idm-field-label">
                <Building2 size={12} /> 项目身份
              </label>
              {activeProject && (
                <div className="idm-project-current">
                  <span className="idm-project-name">{activeProject.projectName}</span>
                  <span className="idm-project-role">
                    {projectRoleLabel[activeProject.projectRole] ?? activeProject.projectRole}
                  </span>
                  {urlProjectId && activeProject.projectId === urlProjectId && (
                    <span className="idm-project-mark" title="当前正在查看的项目">
                      <Check size={11} aria-hidden="true" /> 当前
                    </span>
                  )}
                </div>
              )}
              {projects.length > 1 && (
                <div className="idm-project-row">
                  <select
                    className="idm-select"
                    value={projectIndex}
                    onChange={(e) => setProjectIndex(Number(e.target.value))}
                  >
                    {projects.map((ctx, i) => (
                      <option key={ctx.projectId} value={i}>
                        {ctx.projectName}
                        {ctx.projectId === urlProjectId ? "（当前）" : ""}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          ) : authMe ? (
            <div className="idm-project idm-project-empty">无项目身份</div>
          ) : null}

          <div className="idm-divider" />

          <div className="idm-auth">
            {authMe ? (
              <>
                {authError && (
                  <div className="idm-error" role="alert">
                    {authError}
                  </div>
                )}
                <div className="idm-actions">
                  <button
                    type="button"
                    className="idm-logout"
                    onClick={() => void handleLogout()}
                    disabled={authBusy}
                  >
                    <LogOut size={13} /> 登出当前会话
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="idm-field-label">登录</div>
                {/* 隐藏假字段，干扰浏览器基于历史会话的账密自动填充 */}
                <input
                  type="text"
                  name="kap-switch-field"
                  tabIndex={-1}
                  autoComplete="off"
                  aria-hidden="true"
                  style={{ display: "none" }}
                />
                <input
                  type="password"
                  name="kap-switch-code"
                  tabIndex={-1}
                  autoComplete="off"
                  aria-hidden="true"
                  style={{ display: "none" }}
                />
                <input
                  className="idm-input"
                  type="email"
                  name="kap-switch-field"
                  placeholder="登录邮箱"
                  value={loginEmail}
                  onChange={(e) => setLoginEmail(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleLogin();
                  }}
                  autoComplete="off"
                />
                <input
                  className="idm-input"
                  type="password"
                  name="kap-switch-code"
                  placeholder="密码"
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleLogin();
                  }}
                  autoComplete="new-password"
                />
                <div className="idm-actions">
                  <button
                    type="button"
                    className="btn-primary idm-btn"
                    onClick={() => void handleLogin()}
                    disabled={authBusy}
                  >
                    {authBusy ? "登录中…" : "登录"}
                  </button>
                  <button
                    type="button"
                    className="btn-secondary idm-btn"
                    onClick={() => void handleWecomLogin()}
                    disabled={authBusy}
                  >
                    企业微信
                  </button>
                </div>
                {authError && (
                  <div className="idm-error" role="alert">
                    {authError}
                  </div>
                )}
                {showLoginForm && (
                  <p className="idm-hint">使用企业微信登录 Kivo，或使用已分配的账号密码。</p>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
