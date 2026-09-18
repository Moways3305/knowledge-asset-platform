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
import { TASK_STATUS_INVALIDATED_EVENT } from "./taskStatusEvents";

type WorkbenchState = "loading" | "ready" | "error";

interface WorkbenchContextValue {
  overview: WorkbenchOverviewDTO | null;
  state: WorkbenchState;
  refresh: () => Promise<void>;
}

const WorkbenchContext = createContext<WorkbenchContextValue | null>(null);

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const { status: authStatus } = useAuth();
  const [overview, setOverview] = useState<WorkbenchOverviewDTO | null>(null);
  const [state, setState] = useState<WorkbenchState>("loading");
  const requestRef = useRef(0);
  const hasDataRef = useRef(false);
  const inFlight = useRef<AbortController | null>(null);
  const needsRefresh = useRef(false);

  const refresh = useCallback(async () => {
    if (inFlight.current) {
      needsRefresh.current = true;
      return;
    }
    const controller = new AbortController();
    needsRefresh.current = false;
    inFlight.current = controller;
    const deadline = window.setTimeout(() => {
      if (inFlight.current !== controller) return;
      controller.abort();
      inFlight.current = null;
      // Drain invalidations here: an aborted transport may never settle.
      if (needsRefresh.current) void refresh();
    }, 30_000);
    const requestId = ++requestRef.current;
    setState((current) => (hasDataRef.current || current === "ready" ? current : "loading"));
    try {
      const next = await fetchWorkbenchOverview(controller.signal);
      if (requestId !== requestRef.current || controller.signal.aborted || needsRefresh.current)
        return;
      hasDataRef.current = true;
      setOverview(next);
      setState("ready");
    } catch {
      if (requestId !== requestRef.current || controller.signal.aborted) return;
      setState("error");
    } finally {
      window.clearTimeout(deadline);
      if (inFlight.current === controller) {
        inFlight.current = null;
        if (needsRefresh.current && !controller.signal.aborted) {
          needsRefresh.current = false;
          void refresh();
        }
      }
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
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible" && !inFlight.current) void refresh();
    }, 30_000);
    const onVisible = () => {
      if (document.visibilityState === "visible" && !inFlight.current) void refresh();
    };
    const onTaskInvalidated = () => void refresh();
    window.addEventListener("focus", onVisible);
    window.addEventListener(TASK_STATUS_INVALIDATED_EVENT, onTaskInvalidated);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      requestRef.current += 1;
      inFlight.current?.abort();
      inFlight.current = null;
      needsRefresh.current = false;
      window.clearInterval(interval);
      window.removeEventListener("focus", onVisible);
      window.removeEventListener(TASK_STATUS_INVALIDATED_EVENT, onTaskInvalidated);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [authStatus, refresh]);

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
