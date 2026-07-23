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
  // 供给 IdentityMenu 在登录 / 登出后直接写入或清空。
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
      if (e instanceof ApiError && e.status === 401) {
        // 确实未登录：清空状态，UI 显示登录入口
        setAuthMeState(null);
        setStatus("anonymous");
      } else {
        // 网络 / 服务端临时故障：保留上次已知身份，显示错误 banner 供用户重试
        setStatus("error");
      }
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
