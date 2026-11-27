import { useCallback, useEffect, useRef, useState } from "react";
import {
  getWorkspaceDetail,
  getWorkspaceEvents,
  getWorkspaceOptions,
  isWorkspaceRunActive,
  listWorkspaceSessions,
  type WorkspaceDetail,
  type WorkspaceEvent,
  type WorkspaceOptions,
  type WorkspaceSession,
} from "../../api/aiWorkspace";
import { ApiError } from "../../api/http";

export const workspaceError = (error: unknown) =>
  error instanceof ApiError ? error.message : "连接暂时中断，请重试。你的输入仍保留在当前页面。";

/** Cursor-driven updates keep the mounted conversation and editor intact. */
export function useWorkspaceData(sessionId: string) {
  const [options, setOptions] = useState<WorkspaceOptions | null>(null);
  const [sessions, setSessions] = useState<WorkspaceSession[]>([]);
  const [details, setDetails] = useState<Record<string, WorkspaceDetail>>({});
  const [events, setEvents] = useState<Record<string, WorkspaceEvent[]>>({});
  const [connectionError, setConnectionError] = useState("");
  const [initialError, setInitialError] = useState("");
  const [deniedSession, setDeniedSession] = useState("");
  const [identityDenied, setIdentityDenied] = useState(false);
  const [loading, setLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [initialRevision, setInitialRevision] = useState(0);
  const detailRef = useRef(details);
  detailRef.current = details;

  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  const reloadOptions = useCallback(() => setInitialRevision((value) => value + 1), []);
  const upsertSession = useCallback((row: WorkspaceSession) => {
    setSessions((rows) => [row, ...rows.filter((item) => item.id !== row.id)]);
  }, []);
  const removeSession = useCallback((id: string) => {
    setSessions((rows) => rows.filter((item) => item.id !== id));
    setDetails((current) => {
      const next = { ...current };
      delete next[id];
      return next;
    });
    setEvents((current) => {
      const next = { ...current };
      delete next[id];
      return next;
    });
  }, []);

  useEffect(() => {
    const foreground = () => {
      if (!document.hidden) refresh();
    };
    window.addEventListener("focus", foreground);
    document.addEventListener("visibilitychange", foreground);
    return () => {
      window.removeEventListener("focus", foreground);
      document.removeEventListener("visibilitychange", foreground);
    };
  }, [refresh]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([getWorkspaceOptions(controller.signal), listWorkspaceSessions(controller.signal)])
      .then(([available, recent]) => {
        if (controller.signal.aborted) return;
        setOptions(available);
        setSessions(recent);
        setInitialError("");
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setInitialError(workspaceError(error));
      });
    return () => controller.abort();
  }, [initialRevision]);

  useEffect(() => {
    setDeniedSession("");
    setIdentityDenied(false);
    if (!sessionId) {
      setLoading(false);
      setConnectionError("");
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let cursor = 0;
    setLoading(!detailRef.current[sessionId]);
    setConnectionError("");
    setDeniedSession("");
    async function poll() {
      let running = detailRef.current[sessionId]?.runs.some(isWorkspaceRunActive);
      try {
        const batch = await getWorkspaceEvents(sessionId, cursor, controller.signal);
        if (controller.signal.aborted) return;
        // A reconnect starts from zero; deduplicate rather than clearing displayed steps.
        // Permissions and source revisions can change without a session event.
        // Revalidate the projection on every poll while preserving mounted UI.
        {
          const snapshot = await getWorkspaceDetail(sessionId, controller.signal);
          if (controller.signal.aborted) return;
          running = snapshot.runs.some(isWorkspaceRunActive);
          setDetails((current) => ({ ...current, [sessionId]: snapshot }));
          setEvents((current) => {
            const merged = new Map((current[sessionId] ?? []).map((event) => [event.id, event]));
            batch.events.forEach((event) => merged.set(event.id, event));
            return {
              ...current,
              [sessionId]: [...merged.values()].sort((a, b) => a.id - b.id).slice(-500),
            };
          });
          setSessions((rows) => {
            const next = rows.filter((row) => row.id !== sessionId);
            next.push(snapshot.session);
            return next.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
          });
          cursor = batch.cursor;
        }
        setLoading(false);
        setConnectionError("");
      } catch (error: unknown) {
        if (controller.signal.aborted) return;
        setLoading(false);
        setConnectionError(workspaceError(error));
        if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
          removeSession(sessionId);
          setDeniedSession(sessionId);
          setIdentityDenied(error.status === 401 || error.status === 403);
          return;
        }
      }
      if (controller.signal.aborted) return;
      timer = setTimeout(poll, document.hidden ? 15000 : running ? 1800 : 8000);
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [sessionId, revision, removeSession]);

  return {
    options,
    sessions,
    detail: details[sessionId],
    events: events[sessionId] ?? [],
    connectionError,
    initialError,
    deniedSession,
    identityDenied,
    loading,
    refresh,
    reloadOptions,
    upsertSession,
    removeSession,
  };
}
