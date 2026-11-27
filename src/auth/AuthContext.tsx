import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, clearCsrfToken } from "../api/http";
import { fetchAuthMe, type AuthMeVM } from "../api/auth";
import { deriveCapabilities, type Capabilities } from "./permissions";
import { subscribeAuthChanges } from "./authChanges";

// 单一身份来源：整个应用只在此拉取一次 /auth/me，导航过滤、页面守卫、身份菜单共享，
// 避免各组件各自请求导致登录态不一致（登录/登出后由 setAuthMe / reload 统一刷新）。
type AuthStatus = "loading" | "authenticated" | "anonymous" | "error";

interface AuthContextValue {
  authMe: AuthMeVM | null;
  status: AuthStatus;
  identityMessage: string;
  availableRoles: string[];
  capabilities: Capabilities;
  reload: () => Promise<void>;
  // 供给 IdentityMenu 在登录 / 登出后直接写入或清空。
  setAuthMe: (me: AuthMeVM | null) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function authorizationKey(me: AuthMeVM | null): string {
  if (!me) return "anonymous";
  return JSON.stringify([
    me.userId,
    me.activeCompanyRole,
    [...me.companyRoles].sort(),
    me.isBusinessUser,
    me.canDiscoverL5,
    me.projects.map((project) => [project.projectId, project.projectRole]).sort(),
  ]);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authMe, setAuthMeState] = useState<AuthMeVM | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [identityMessage, setIdentityMessage] = useState("");
  const [availableRoles, setAvailableRoles] = useState<string[]>([]);
  const generation = useRef(0);
  const pending = useRef<number | null>(null);

  const revalidate = useCallback(async (silent = false) => {
    if (silent && pending.current !== null) return;
    const request = ++generation.current;
    pending.current = request;
    if (!silent) {
      setStatus("loading");
      setIdentityMessage("");
      setAvailableRoles([]);
    }
    try {
      const me = await fetchAuthMe();
      if (request !== generation.current) return;
      setAuthMeState(me);
      setStatus("authenticated");
      setIdentityMessage("");
      setAvailableRoles([]);
    } catch (e) {
      if (request !== generation.current) return;
      if (
        e instanceof ApiError &&
        e.status === 403 &&
        e.deniedReason?.startsWith("active_company_role_")
      ) {
        setAuthMeState(null);
        if (e.deniedReason === "active_company_role_selection_required") {
          const roles = e.detail?.available_roles;
          setAvailableRoles(
            Array.isArray(roles) ? roles.filter((r): r is string => typeof r === "string") : [],
          );
          setIdentityMessage("工作身份已变更，请选择当前要使用的身份。");
          setStatus("error");
        } else if (e.deniedReason === "active_company_role_unavailable") {
          setIdentityMessage("当前没有可用工作身份，请联系管理员。");
          setStatus("error");
        } else {
          setIdentityMessage("工作身份凭证已失效，请重新登录。");
          setStatus("anonymous");
        }
        return;
      }
      if (e instanceof ApiError && e.status === 401) {
        // 确实未登录：清空状态，UI 显示登录入口
        setAuthMeState(null);
        setStatus("anonymous");
      } else {
        // Losing connectivity while returning to an unchanged session must not
        // destroy its draft. Known cross-tab changes use the blocking path;
        // an explicit auth rejection always clears protected content above.
        if (silent && (!(e instanceof ApiError) || e.status >= 500)) return;
        // 网络 / 服务端临时故障：保留上次已知身份，显示错误 banner 供用户重试
        setStatus("error");
      }
    } finally {
      if (pending.current === request) pending.current = null;
    }
  }, []);

  const reload = useCallback(() => revalidate(), [revalidate]);

  const setAuthMe = useCallback((me: AuthMeVM | null) => {
    generation.current += 1;
    pending.current = null;
    setAuthMeState(me);
    setStatus(me ? "authenticated" : "anonymous");
    setIdentityMessage("");
    setAvailableRoles([]);
  }, []);

  useEffect(() => {
    void reload();
    const unsubscribe = subscribeAuthChanges(() => {
      clearCsrfToken();
      // Another tab changed the shared cookie. Remove the old identity before
      // checking it, including when the replacement request cannot connect.
      setAuthMeState(null);
      void revalidate();
    });
    const foreground = () => {
      if (document.visibilityState === "visible") void revalidate(true);
    };
    window.addEventListener("focus", foreground);
    document.addEventListener("visibilitychange", foreground);
    return () => {
      generation.current += 1;
      pending.current = null;
      unsubscribe();
      window.removeEventListener("focus", foreground);
      document.removeEventListener("visibilitychange", foreground);
    };
  }, [reload, revalidate]);

  const value = useMemo<AuthContextValue>(
    // A failed identity refresh is intentionally fail-closed for navigation and
    // mutation affordances.  We may retain the last display identity for a
    // recovery prompt, but it must not continue to expose governance controls.
    () => ({
      authMe,
      status,
      identityMessage,
      availableRoles,
      capabilities: deriveCapabilities(status === "authenticated" ? authMe : null),
      reload,
      setAuthMe,
    }),
    [authMe, status, identityMessage, availableRoles, reload, setAuthMe],
  );

  // Same-identity refreshes retain the mounted workspace. Actual permission or
  // account changes discard its cached protected results and unsent content.
  return (
    <AuthContext.Provider key={authorizationKey(authMe)} value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 <AuthProvider> 内使用");
  return ctx;
}
