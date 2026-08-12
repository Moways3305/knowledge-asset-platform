import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { fetchWorkbenchOverview } from "../api/workbench";
import type { WorkbenchOverviewDTO } from "../types/workbench";
import { useAuth } from "../auth/AuthContext";
import { useLocation } from "react-router-dom";

type WorkbenchState = "loading" | "ready" | "error";

interface WorkbenchContextValue {
  overview: WorkbenchOverviewDTO | null;
  state: WorkbenchState;
  refresh: () => Promise<void>;
}

const WorkbenchContext = createContext<WorkbenchContextValue | null>(null);

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const { status: authStatus } = useAuth();
  const location = useLocation();
  const [overview, setOverview] = useState<WorkbenchOverviewDTO | null>(null);
  const [state, setState] = useState<WorkbenchState>("loading");
  const requestRef = useRef(0);
  const hasDataRef = useRef(false);

  const refresh = useCallback(async () => {
    const requestId = ++requestRef.current;
    setState((current) => (hasDataRef.current || current === "ready" ? current : "loading"));
    try {
      const next = await fetchWorkbenchOverview();
      if (requestId !== requestRef.current) return;
      hasDataRef.current = true;
      setOverview(next);
      setState("ready");
    } catch {
      if (requestId !== requestRef.current) return;
      setState("error");
    }
  }, []);

  useEffect(() => {
    if (authStatus !== "authenticated") {
      requestRef.current += 1;
      hasDataRef.current = false;
      setOverview(null);
      setState(authStatus === "loading" ? "loading" : "error");
      return;
    }
    void refresh();
    const interval = window.setInterval(() => void refresh(), 30_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      requestRef.current += 1;
      window.clearInterval(interval);
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [authStatus, location.pathname, refresh]);

  return (
    <WorkbenchContext.Provider value={{ overview, state, refresh }}>
      {children}
    </WorkbenchContext.Provider>
  );
}

export function useWorkbench() {
  const context = useContext(WorkbenchContext);
  if (!context) throw new Error("useWorkbench must be used inside WorkbenchProvider");
  return context;
}
