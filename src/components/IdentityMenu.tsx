import { useState, useCallback, useEffect, useRef } from "react";
import { ChevronDown, LogOut, UserRound, Building2 } from "lucide-react";
import { ApiError } from "../api/http";
import { fetchAuthMe, login, logout, type AuthMeVM } from "../api/auth";
import { startWecomOAuth } from "../api/admin";

const roleLabel: Record<string, string> = {
  boss: "Boss",
  consulting_director: "咨询总监",
  consultant: "顾问",
  admin: "管理员",
};

const projectRoleLabel: Record<string, string> = {
  project_manager: "项目经理",
  consultant: "顾问",
  coach: "辅导老师",
};

/**
 * 身份与会话入口。所有登录/登出/企微/切换账号控件与错误反馈都收纳在一个
 * 固定宽度的浮层里，因此长邮箱、长项目名、失败文案都只在浮层内换行，
 * 绝不撑坏顶部命令栏（解决旧顶栏登录失败变形问题）。
 */
export default function IdentityMenu() {
  const [authMe, setAuthMe] = useState<AuthMeVM | null>(null);
  const [open, setOpen] = useState(false);
  const [projectIndex, setProjectIndex] = useState(0);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const loadMe = useCallback(async () => {
    try {
      const me = await fetchAuthMe();
      setAuthMe(me);
      setProjectIndex(0);
      setAuthError(null);
    } catch (e) {
      setAuthMe(null);
      setAuthError(e instanceof ApiError ? "身份未登录或会话已过期" : "身份加载失败");
    }
  }, []);

  useEffect(() => {
    void loadMe();
  }, [loadMe]);

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
  }, [loginEmail, loginPassword]);

  const handleWecomLogin = useCallback(async () => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      // 后端生成 state 写短时 httpOnly cookie 并返回授权 URL；前端只做跳转，
      // 绝不接触/存储 OAuth code / state（会话由后端 httpOnly cookie 控制）。
      const { authorize_url } = await startWecomOAuth();
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
      await loadMe();
    } catch {
      setAuthError("登出失败，请稍后重试");
    } finally {
      setAuthBusy(false);
    }
  }, [loadMe]);

  const projects = authMe?.projects ?? [];
  const currentProject = projects[projectIndex];
  const rolesText = (authMe?.companyRoles ?? []).map((r) => roleLabel[r] ?? r).join(" / ") || "—";
  const name = authMe?.name ?? "未登录";
  const initial = (authMe?.name ?? "·").trim().charAt(0) || "·";

  return (
    <div className="idm" ref={wrapRef}>
      <button
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
              <div className="idm-panel-roles">
                <UserRound size={12} /> 平台身份：{rolesText}
              </div>
            </div>
          </div>

          {projects.length > 0 ? (
            <div className="idm-project">
              <label className="idm-field-label">
                <Building2 size={12} /> 当前项目
              </label>
              <div className="idm-project-row">
                <select
                  className="idm-select"
                  value={projectIndex}
                  onChange={(e) => setProjectIndex(Number(e.target.value))}
                >
                  {projects.map((ctx, i) => (
                    <option key={ctx.projectId} value={i}>
                      {ctx.projectName}
                    </option>
                  ))}
                </select>
                {currentProject && (
                  <span className="idm-project-role">
                    {projectRoleLabel[currentProject.projectRole] ?? currentProject.projectRole}
                  </span>
                )}
              </div>
            </div>
          ) : authMe ? (
            <div className="idm-project idm-project-empty">无项目身份</div>
          ) : null}

          <div className="idm-divider" />

          <div className="idm-auth">
            <div className="idm-field-label">{authMe ? "切换账号" : "登录"}</div>
            <input
              className="idm-input"
              type="email"
              placeholder="登录邮箱"
              value={loginEmail}
              onChange={(e) => setLoginEmail(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleLogin();
              }}
            />
            <input
              className="idm-input"
              type="password"
              placeholder="密码"
              value={loginPassword}
              onChange={(e) => setLoginPassword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleLogin();
              }}
            />
            <div className="idm-actions">
              <button
                className="btn-primary idm-btn"
                onClick={() => void handleLogin()}
                disabled={authBusy}
              >
                登录
              </button>
              <button
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
            <p className="idm-hint">开发环境可不填密码用邮箱登录；生产需密码或企业微信。</p>
            {authMe && (
              <button
                className="idm-logout"
                onClick={() => void handleLogout()}
                disabled={authBusy}
              >
                <LogOut size={13} /> 登出当前会话
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
