import { useRef, useState, type FormEvent } from "react";
import { useLocation } from "react-router-dom";
import { Eye, EyeOff, MessageCircle } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { login } from "../api/auth";
import { ApiError } from "../api/http";
import { startWecomOAuth } from "../api/admin";
import { rememberLoginReturn } from "../auth/loginReturn";
import "./LoginPage.css";

export default function LoginPage() {
  const { status, reload, setAuthMe } = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState<"password" | "wecom" | null>(null);
  const inFlight = useRef(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    if (!email.trim() || !password) {
      setError("请输入邮箱和密码");
      return;
    }
    inFlight.current = true;
    setBusy("password");
    setError("");
    try {
      const me = await login(email.trim(), password);
      setPassword("");
      setAuthMe(me);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401
          ? "邮箱或密码错误"
          : e instanceof ApiError && e.status === 429
            ? "尝试次数过多，请稍后重试"
            : "登录失败，请稍后重试或联系管理员",
      );
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  async function wecom() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy("wecom");
    setError("");
    try {
      const { authorize_url } = await startWecomOAuth(
        /wxwork/i.test(navigator.userAgent) ? "client" : "web_qr",
      );
      const url = new URL(authorize_url);
      if (url.protocol !== "https:") throw new Error("Invalid OAuth URL");
      rememberLoginReturn(location.pathname + location.search + location.hash);
      window.location.assign(url.href);
    } catch {
      setError("企业微信登录暂不可用，请使用账号登录或联系管理员");
      inFlight.current = false;
      setBusy(null);
    }
  }

  return (
    <main className="login-page">
      <header className="login-brand">
        <img src="/moways-logo.png" alt="MOWAYS 博维咨询" width="984" height="327" />
        <span className="login-brand-rule" aria-hidden="true" />
        <h1>博维知识资产平台</h1>
        <p>沉淀专业经验，支持项目交付</p>
      </header>
      <section className="login-panel" aria-labelledby="login-heading">
        <h2 id="login-heading">欢迎登录</h2>
        <p className="login-subtitle">使用公司账号进入平台</p>
        {status === "loading" ? (
          <p role="status" className="login-notice">
            正在验证登录状态…
          </p>
        ) : status === "error" ? (
          <div className="login-notice" role="alert">
            <p>暂时无法连接登录服务，请重试。</p>
            <button className="login-primary" type="button" onClick={() => void reload()}>
              重新连接
            </button>
          </div>
        ) : (
          <>
            <form onSubmit={submit} aria-busy={busy !== null}>
              <label htmlFor="login-email">邮箱</label>
              <input
                id="login-email"
                name="email"
                type="email"
                autoComplete="username"
                placeholder="请输入登录邮箱"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={busy !== null}
              />
              <label htmlFor="login-password">密码</label>
              <div className="login-password">
                <input
                  id="login-password"
                  name="password"
                  type={visible ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="请输入密码"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={busy !== null}
                />
                <button
                  type="button"
                  className="login-reveal"
                  aria-label={visible ? "隐藏密码" : "显示密码"}
                  aria-pressed={visible}
                  onClick={() => setVisible((v) => !v)}
                >
                  {visible ? <EyeOff size={20} /> : <Eye size={20} />}
                </button>
              </div>
              {error && (
                <p className="login-error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" className="login-primary" disabled={busy !== null}>
                {busy === "password" ? "正在登录…" : "登录"}
              </button>
            </form>
            <div className="login-divider">
              <span>或</span>
            </div>
            <button
              type="button"
              className="login-wecom"
              disabled={busy !== null}
              onClick={() => void wecom()}
            >
              <MessageCircle size={23} aria-hidden="true" />
              {busy === "wecom" ? "正在跳转…" : "企业微信登录"}
            </button>
          </>
        )}
      </section>
    </main>
  );
}
