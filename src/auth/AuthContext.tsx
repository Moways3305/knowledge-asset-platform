import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiError } from "../api/http";
import { fetchAuthMe, type AuthMeVM } from "../api/auth";
import { deriveCapabilities, type Capabilities } from "./permissions";

// 单一身份来源：整个应用只在此拉取一次 /auth/me，导航过滤、页面守卫、身份菜单共享，
// 避免各组件各自请求导致登录态不一致（登录/登出后由 setAuthMe / reload 统一刷新）。
type AuthStatus = "loading" | "authenticated" | "anonymous" | "error";

interface AuthContextValue {
  authMe: AuthMeVM | null;
  status: AuthStatus;
  capabilities: Capabilities;
  reload: () => Promise<void>;
  // 登录 / 登出后由 IdentityMenu 直接写入最新身份（或置空），无需再次往返。
  setAuthMe: (me: AuthMeVM | null) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [authMe, setAuthMeState] = useState<AuthMeVM | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  const reload = useCallback(async () => {
    setStatus("loading");
    try {
      const me = await fetchAuthMe();
      setAuthMeState(me);
      setStatus("authenticated");
    } catch (e) {
      setAuthMeState(null);
      // 401 / 鉴权类失败 → 视为未登录（匿名）；其余（网络 / 服务端）→ 错误态。
      setStatus(e instanceof ApiError && e.status === 401 ? "anonymous" : "error");
    }
  }, []);

  const setAuthMe = useCallback((me: AuthMeVM | null) => {
    setAuthMeState(me);
    setStatus(me ? "authenticated" : "anonymous");
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const value = useMemo<AuthContextValue>(
    () => ({ authMe, status, capabilities: deriveCapabilities(authMe), reload, setAuthMe }),
    [authMe, status, reload, setAuthMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 <AuthProvider> 内使用");
  return ctx;
}
