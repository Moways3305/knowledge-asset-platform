import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  BookOpen,
  Bot,
  Check,
  Circle,
  ChevronRight,
  Cpu,
  FileDiff,
  FileText,
  HelpCircle,
  History,
  Layers2,
  Menu,
  PanelLeftClose,
  PanelRight,
  Pencil,
  Plus,
  RotateCcw,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  Table2,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import {
  createWorkspaceSession,
  deleteWorkspaceSession,
  decideWorkspaceAction,
  isWorkspaceRunActive,
  renameWorkspaceSession,
  resumeWorkspaceRun,
  sendWorkspaceMessage,
  stopWorkspaceRun,
  type WorkspaceArtifact,
  type WorkspaceRun,
  type WorkspaceSession,
} from "../api/aiWorkspace";
import { createClientUuid } from "../api/http";
import { useDialogSurface } from "../components/useDialogSurface";
import { MarkdownView } from "./knowledge/OnlyOfficePreview";
import ArtifactPanel, { type ArtifactDraft, type PreviewTab } from "./ai-workspace/ArtifactPanel";
import { useWorkspaceData, workspaceError } from "./ai-workspace/useWorkspaceData";
import { WorkspaceIconButton, WorkspaceTooltip } from "./ai-workspace/WorkspaceTooltip";
import { ActionConfirmation, ToolReceipts } from "./ai-workspace/RunActions";
import AgentPicker from "./ai-workspace/AgentPicker";
import {
  AI_WORKSPACE_PATH,
  MAINTENANCE_AGENT_KEY,
  MAINTENANCE_AGENT_PATH,
  agentConversationHref,
  maintenanceAgentHref,
} from "../navigation/agentRoutes";
import "../styles/ai-workspace.css";

const MaintenanceAgentPage = lazy(() => import("./MaintenanceAgentPage"));
type View = "chat" | "agents" | "maintenance" | "tools" | "preferences" | "help";
interface SessionView {
  input: string;
  model: string;
  context: string;
  artifact: string;
  previewOpen: boolean;
  previewFull: boolean;
  previewTab: PreviewTab;
}
const EMPTY_VIEW: SessionView = {
  input: "",
  model: "",
  context: "",
  artifact: "",
  previewOpen: false,
  previewFull: false,
  previewTab: "document",
};
const runLabels: Record<WorkspaceRun["status"], string> = {
  queued: "等待开始",
  running: "正在处理",
  waiting: "等待继续",
  awaiting_confirmation: "等待你的确认",
  completed: "已完成",
  failed: "未能完成",
  stopped: "已停止",
};
const failureLabels: Record<string, string> = {
  model_unavailable: "所选模型当前不可用，请检查模型配置后重试。",
  access_changed: "知识访问权限已变更，请重新选择可访问的上下文。",
  timeout: "处理超时，可以重试。",
  interrupted: "执行中断，可以重试。",
  run_expired: "执行中断，可以重试。",
};

function WorkspaceDialog({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const dialog = useDialogSurface(true, ref, onClose);
  return (
    <div className="aw-dialog-backdrop">
      <div
        ref={ref}
        className="aw-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        {...dialog}
      >
        <header>
          <h2>{title}</h2>
          <WorkspaceIconButton label="关闭弹窗" onClick={onClose}>
            <X />
          </WorkspaceIconButton>
        </header>
        {children}
      </div>
    </div>
  );
}

export default function AIWorkspacePage() {
  const { authMe } = useAuth();
  return <Workspace key={`${authMe?.userId}:${authMe?.activeCompanyRole}`} />;
}

function Workspace() {
  const { authMe, reload } = useAuth();
  const location = useLocation();
  const routeNavigate = useNavigate();
  const [params] = useSearchParams();
  const isMaintenance = location.pathname.replace(/\/$/, "") === MAINTENANCE_AGENT_PATH;
  const sessionId = params.get("session") ?? "";
  const requestedView = params.get("view");
  const managementView =
    isMaintenance &&
    (params.has("target_id") ||
      params.has("digest_id") ||
      params.has("asset_id") ||
      requestedView === "mine" ||
      ["issues", "runs", "settings"].includes(params.get("tab") ?? ""));
  const view: View = managementView
    ? "maintenance"
    : ["agents", "tools", "preferences", "help"].includes(requestedView ?? "")
      ? (requestedView as View)
      : "chat";
  const state = useWorkspaceData(sessionId);
  const requestedAgent = isMaintenance ? MAINTENANCE_AGENT_KEY : params.get("agent");
  const requestedLibrary = params.get("library");
  const agentKey = sessionId
    ? (state.detail?.session.agent_key ??
      state.sessions.find((item) => item.id === sessionId)?.agent_key ??
      null)
    : requestedAgent;
  const agent = state.options?.agents?.find((item) => item.key === agentKey);
  const currentAgent = useRef(agentKey);
  currentAgent.current = agentKey;
  const unknownAgent = Boolean(!sessionId && agentKey && state.options && !agent);
  const [sessionViews, setSessionViews] = useState<Record<string, SessionView>>({});
  const [artifactDrafts, setArtifactDrafts] = useState<Record<string, ArtifactDraft>>({});
  const [lastAgentLocation, setLastAgentLocation] = useState<{
    search: string;
    hash: string;
  } | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const navigationWasOpen = useRef(false);
  navigationWasOpen.current = sidebarOpen;
  const [width, setWidth] = useState(() => window.innerWidth);
  const [motion, setMotion] = useState(() => {
    try {
      return localStorage.getItem("kap-ai-motion") !== "off";
    } catch {
      return true;
    }
  });
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState<Set<string>>(new Set());
  const pendingSubmissions = useRef(new Set<string>());
  const [operationBusy, setOperationBusy] = useState(false);
  const [dialog, setDialog] = useState<"context" | "rename" | "delete" | null>(null);
  const [rename, setRename] = useState("");
  const [dialogError, setDialogError] = useState("");
  const [followLatest, setFollowLatest] = useState(true);
  const frame = useRef<HTMLDivElement>(null);
  const sidebar = useRef<HTMLElement>(null);
  const main = useRef<HTMLElement>(null);
  const navigationOpener = useRef<HTMLButtonElement>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const editor = useRef<HTMLTextAreaElement>(null);
  const currentId = useRef(sessionId);
  currentId.current = sessionId;
  const routeKey = `${location.pathname}${location.search}${location.hash}`;
  const currentRoute = useRef(routeKey);
  currentRoute.current = routeKey;
  const mounted = useRef(true);
  const positions = useRef<Record<string, { top: number; follow: boolean }>>({});
  const requests = useRef<
    Record<
      string,
      { signature: string; id: string; sessionRequest: string; session?: WorkspaceSession }
    >
  >({});
  const resumeRequests = useRef<Record<string, string>>({});
  const actionRequests = useRef<Record<string, string>>({});
  const artifactOwners = useRef<Record<string, string>>({});
  const previewPositions = useRef<Record<string, number>>({});
  // Selecting an Agent changes who receives the same draft, not the draft itself.
  const key = sessionId || "new";
  const stored = sessionViews[key];
  const lastRun = state.detail?.runs[state.detail.runs.length - 1];
  const defaultView: SessionView = {
    ...EMPTY_VIEW,
    model:
      lastRun?.model_ref ??
      state.options?.models.find((item) => item.is_default)?.model_ref ??
      state.options?.models[0]?.model_ref ??
      "",
    context: lastRun
      ? (lastRun.context_key ?? "")
      : agentKey === MAINTENANCE_AGENT_KEY
        ? (params.get("library") ?? "company")
        : "",
  };
  const selected: SessionView = stored
    ? { ...stored, model: stored.model || defaultView.model }
    : defaultView;
  const activeRun = state.detail?.runs.find(isWorkspaceRunActive);
  const busy = submitting.has(key) || activeRun?.status === "awaiting_confirmation";
  const tools = [
    ...new Map(
      [...(state.options?.tools ?? []), ...(agent?.tools ?? [])].map((tool) => [tool.key, tool]),
    ).values(),
  ];
  const availableModel = state.options?.models.some((model) => model.model_ref === selected.model);
  const artifact = state.detail?.artifacts.find((item) => item.id === selected.artifact);
  const compact = width < 1040;
  const showPreview = Boolean(artifact && selected.previewOpen && view === "chat");
  const fullPreview = selected.previewFull || width < 900;
  const closeSidebar = useCallback(() => {
    const restoreFocus = navigationWasOpen.current;
    if (main.current) main.current.inert = false;
    setSidebarOpen(false);
    if (restoreFocus) requestAnimationFrame(() => navigationOpener.current?.focus());
  }, []);
  const sidebarDialog = useDialogSurface(compact && sidebarOpen, sidebar, closeSidebar);
  const updateView = (patch: Partial<SessionView>, target = key) => {
    setSessionViews((previous) => ({
      ...previous,
      [target]: { ...(target === key ? selected : EMPTY_VIEW), ...previous[target], ...patch },
    }));
  };
  const updateArtifactDraft = (
    id: string,
    update: (current: ArtifactDraft | undefined) => ArtifactDraft,
  ) => setArtifactDrafts((previous) => ({ ...previous, [id]: update(previous[id]) }));

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (managementView) setLastAgentLocation({ search: location.search, hash: location.hash });
  }, [managementView, location.search, location.hash]);
  useEffect(() => {
    if (!sessionId && view === "chat" && agentKey === MAINTENANCE_AGENT_KEY) {
      const library =
        requestedLibrary || state.options?.contexts.find((item) => item.key === "company")?.key;
      if (!library) return;
      setSessionViews((previous) =>
        previous[key] && (requestedLibrary || !previous[key].context)
          ? { ...previous, [key]: { ...previous[key], context: library } }
          : previous,
      );
    }
  }, [sessionId, view, agentKey, requestedLibrary, key, state.options?.contexts]);
  useEffect(() => {
    const element = frame.current;
    if (!element) return;
    const resize = () => setWidth(element.clientWidth || window.innerWidth);
    resize();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", resize);
      return () => window.removeEventListener("resize", resize);
    }
    let pending = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(pending);
      pending = requestAnimationFrame(resize);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(pending);
    };
  }, []);
  useEffect(() => {
    if (main.current) main.current.inert = compact && sidebarOpen;
  }, [compact, sidebarOpen]);
  useEffect(() => {
    if (!state.deniedSession) return;
    setSessionViews((previous) => {
      const next = { ...previous };
      delete next[state.deniedSession];
      return next;
    });
    setArtifactDrafts({});
  }, [state.deniedSession]);
  useEffect(() => {
    if (state.identityDenied) void reload();
  }, [state.identityDenied, reload]);
  useEffect(() => {
    if (!state.detail) return;
    const allowed = new Set(state.detail.artifacts.map((item) => item.id));
    setArtifactDrafts((previous) => {
      const removed = Object.keys(previous).filter(
        (id) => artifactOwners.current[id] === sessionId && !allowed.has(id),
      );
      if (!removed.length) return previous;
      const next = { ...previous };
      removed.forEach((id) => {
        delete next[id];
      });
      return next;
    });
  }, [state.detail, sessionId]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      const hasInput = Object.values(sessionViews).some((item) => item.input.trim());
      const hasDraft = Object.values(artifactDrafts).some(
        (item) => item.content !== item.baseContent || item.title !== item.baseTitle,
      );
      if (hasInput || hasDraft) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [sessionViews, artifactDrafts]);
  useLayoutEffect(() => {
    const element = scroll.current;
    if (!element) return;
    const position = positions.current[key];
    element.scrollTop = position?.top ?? element.scrollHeight;
    setFollowLatest(position?.follow ?? true);
  }, [key, view]);
  useLayoutEffect(() => {
    const element = scroll.current;
    if (element && (positions.current[key]?.follow ?? true))
      element.scrollTop = element.scrollHeight;
  }, [state.detail?.messages.length, state.events.length, key]);

  function navigate(
    nextView: View,
    id = sessionId,
    selectedAgent = agentKey,
    library: string | null = null,
  ) {
    const next = new URLSearchParams();
    if (id) next.set("session", id);
    if (selectedAgent) next.set("agent", selectedAgent);
    if (!id && library) next.set("library", library);
    if (nextView !== "chat") next.set("view", nextView);
    routeNavigate(`${AI_WORKSPACE_PATH}${next.size ? `?${next}` : ""}`);
    closeSidebar();
    setError("");
    setDialog(null);
  }
  function onScroll() {
    const element = scroll.current;
    if (!element) return;
    const follow = element.scrollHeight - element.clientHeight - element.scrollTop < 72;
    positions.current[key] = { top: element.scrollTop, follow };
    setFollowLatest(follow);
  }
  function selectAgent(next: string | null) {
    if (sessionId || submitting.has(key) || pendingSubmissions.current.has(key)) return;
    if (next === agentKey) return;
    if (next && !state.options?.agents?.some((item) => item.key === next)) return;
    updateView({
      context:
        selected.context ||
        (next === MAINTENANCE_AGENT_KEY
          ? state.options?.contexts.find((item) => item.key === "company")?.key || ""
          : ""),
    });
    navigate("chat", "", next);
  }
  function jumpLatest() {
    if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
    positions.current[key] = { top: scroll.current?.scrollTop ?? 0, follow: true };
    setFollowLatest(true);
  }
  async function send() {
    const content = selected.input.trim();
    if (
      busy ||
      pendingSubmissions.current.has(key) ||
      !content ||
      !selected.model ||
      !availableModel ||
      unknownAgent
    )
      return;
    const submittedKey = key;
    const submittedId = sessionId;
    const submittedRoute = currentRoute.current;
    const signature = JSON.stringify([
      content,
      selected.model,
      selected.context,
      agentKey,
      activeRun?.id,
    ]);
    let request = requests.current[submittedKey];
    if (!request || request.signature !== signature) {
      request = { signature, id: createClientUuid(), sessionRequest: createClientUuid() };
      requests.current[submittedKey] = request;
    }
    pendingSubmissions.current.add(submittedKey);
    setSubmitting(new Set(pendingSubmissions.current));
    setError("");
    try {
      let id = submittedId;
      if (!id) {
        request.session ??= await createWorkspaceSession(request.sessionRequest, agentKey);
        id = request.session.id;
        if (!mounted.current) return;
        state.upsertSession(request.session);
      }
      if (activeRun) await resumeWorkspaceRun(id, activeRun.id, request.id, content);
      else
        await sendWorkspaceMessage(id, {
          request_id: request.id,
          content,
          model_ref: selected.model,
          context_key: selected.context || null,
        });
      if (!mounted.current) return;
      setSessionViews((previous) => {
        const current = previous[submittedKey] ?? selected;
        const changedRecipient = !submittedId && currentAgent.current !== agentKey;
        const submittedView = changedRecipient ? selected : current;
        const updated = {
          ...submittedView,
          input: submittedView.input.trim() === content ? "" : submittedView.input,
        };
        return { ...previous, [submittedKey]: changedRecipient ? current : updated, [id]: updated };
      });
      delete requests.current[submittedKey];
      positions.current[id] = { top: scroll.current?.scrollHeight ?? 0, follow: true };
      if (currentRoute.current === submittedRoute) {
        navigate("chat", id);
        state.refresh();
        setFollowLatest(true);
      }
    } catch (cause) {
      if (mounted.current && currentRoute.current === submittedRoute)
        setError(workspaceError(cause));
    } finally {
      pendingSubmissions.current.delete(submittedKey);
      if (mounted.current) setSubmitting(new Set(pendingSubmissions.current));
    }
  }
  async function runAction(run: WorkspaceRun, action: "stop" | "resume") {
    if (operationBusy) return;
    const id = sessionId;
    setOperationBusy(true);
    setError("");
    try {
      if (action === "stop") await stopWorkspaceRun(id, run.id);
      else {
        resumeRequests.current[run.id] ??= createClientUuid();
        await resumeWorkspaceRun(id, run.id, resumeRequests.current[run.id]);
        delete resumeRequests.current[run.id];
      }
      if (mounted.current && currentId.current === id) state.refresh();
    } catch (cause) {
      if (mounted.current && currentId.current === id) setError(workspaceError(cause));
    } finally {
      if (mounted.current) setOperationBusy(false);
    }
  }
  async function decideAction(run: WorkspaceRun, decision: "approve" | "reject") {
    if (operationBusy || !run.pending_action) return;
    const id = sessionId;
    const actionKey = `${run.id}:${run.pending_action.id}:${decision}`;
    actionRequests.current[actionKey] ??= createClientUuid();
    setOperationBusy(true);
    setError("");
    try {
      await decideWorkspaceAction(
        id,
        run.id,
        run.pending_action.id,
        actionRequests.current[actionKey],
        decision,
      );
      delete actionRequests.current[actionKey];
      if (mounted.current && currentId.current === id) state.refresh();
    } catch (cause) {
      if (mounted.current && currentId.current === id) setError(workspaceError(cause));
    } finally {
      if (mounted.current) setOperationBusy(false);
    }
  }
  function openArtifact(item: WorkspaceArtifact) {
    artifactOwners.current[item.id] = sessionId;
    updateView({ artifact: item.id, previewOpen: true });
  }
  async function saveSessionChange() {
    if (operationBusy) return;
    const submittedRoute = currentRoute.current;
    const submittedId = sessionId;
    setOperationBusy(true);
    setDialogError("");
    try {
      if (dialog === "delete") {
        await deleteWorkspaceSession(submittedId);
        if (!mounted.current) return;
        state.removeSession(submittedId);
        setSessionViews((previous) => {
          const next = { ...previous };
          delete next[submittedId];
          return next;
        });
        state.detail?.artifacts.forEach((item) =>
          setArtifactDrafts((previous) => {
            const next = { ...previous };
            delete next[item.id];
            return next;
          }),
        );
        if (currentRoute.current === submittedRoute) navigate("chat", "");
      } else {
        const updated = await renameWorkspaceSession(submittedId, rename.trim());
        if (!mounted.current) return;
        state.upsertSession(updated);
        if (currentRoute.current === submittedRoute) {
          state.refresh();
          setDialog(null);
        }
      }
    } catch (cause) {
      if (mounted.current && currentRoute.current === submittedRoute)
        setDialogError(workspaceError(cause));
    } finally {
      if (mounted.current) setOperationBusy(false);
    }
  }
  function setMotionPreference(enabled: boolean) {
    setMotion(enabled);
    try {
      localStorage.setItem("kap-ai-motion", enabled ? "on" : "off");
    } catch {
      /* Optional visual preference only. */
    }
  }
  const title =
    view === "chat"
      ? state.detail?.session.title || (agent?.label ?? (sessionId ? "会话" : "新建会话"))
      : (
          {
            agents: "Agent",
            maintenance: "知识维护 Agent",
            tools: "工具",
            preferences: "偏好设置",
            help: "使用说明",
          } as const
        )[view];

  return (
    <div
      ref={frame}
      className="ai-workspace"
      data-motion={motion ? "on" : "off"}
      data-preview={showPreview ? (fullPreview ? "full" : "open") : "closed"}
      data-compact={compact}
      data-nav-open={sidebarOpen}
    >
      {compact && sidebarOpen && (
        <button className="aw-nav-scrim" aria-label="收起导航" onClick={closeSidebar} />
      )}
      <aside
        ref={sidebar}
        className="aw-sidebar"
        aria-label="工作空间导航"
        role={compact && sidebarOpen ? "dialog" : undefined}
        aria-modal={compact && sidebarOpen ? true : undefined}
        {...(compact && sidebarOpen ? sidebarDialog : {})}
      >
        <div className="aw-brand">
          <span className="aw-monogram" aria-hidden="true">
            M
          </span>
          <span>
            <strong>博维 AI</strong>
            <small>工作空间</small>
          </span>
          <WorkspaceIconButton
            className="aw-icon aw-close-nav"
            label="关闭导航"
            onClick={closeSidebar}
          >
            <PanelLeftClose />
          </WorkspaceIconButton>
        </div>
        <nav className="aw-navigation">
          <button
            className="aw-nav-item"
            data-active={view === "chat" && !sessionId && !agentKey}
            onClick={() => navigate("chat", "", null)}
          >
            <Plus />
            新建会话
          </button>
          <button
            className="aw-nav-item"
            data-active={
              view === "agents" || view === "maintenance" || Boolean(agentKey && view === "chat")
            }
            onClick={() => navigate("agents")}
          >
            <Bot />
            Agent
          </button>
          <button
            className="aw-nav-item"
            data-active={view === "tools"}
            onClick={() => navigate("tools")}
          >
            <Wrench />
            工具
          </button>
        </nav>
        <section className="aw-history" aria-label="最近会话">
          <span className="aw-section-label">
            最近会话
            <History size={14} />
          </span>
          <div className="aw-history-list">
            {state.sessions.map((item) => (
              <button
                key={item.id}
                className="aw-session"
                aria-current={sessionId === item.id && view === "chat" ? "page" : undefined}
                onClick={() => navigate("chat", item.id, item.agent_key ?? null)}
                title={item.title}
              >
                {item.agent_key && <Bot size={13} aria-label="Agent 会话" />}
                <span>{item.title}</span>
              </button>
            ))}
            {!state.sessions.length && <p className="aw-empty-history">会话会自动保存在这里</p>}
          </div>
        </section>
        <div className="aw-sidebar-bottom">
          <button
            className="aw-nav-item"
            data-active={view === "preferences"}
            onClick={() => navigate("preferences")}
          >
            <Settings2 />
            偏好设置
          </button>
          <Link className="aw-nav-item" to="/">
            <ArrowLeft />
            返回 KAP
          </Link>
          <div className="aw-profile">
            <span>{authMe?.name?.slice(0, 1) || "我"}</span>
            <span>{authMe?.name || "我的工作空间"}</span>
          </div>
        </div>
      </aside>
      <main ref={main} className="aw-main">
        <header className="aw-header">
          <div className="aw-heading">
            <WorkspaceIconButton
              className="aw-icon aw-open-nav"
              ref={navigationOpener}
              label="打开导航"
              onClick={() => setSidebarOpen(true)}
            >
              <Menu />
            </WorkspaceIconButton>
            {view === "maintenance" && (
              <WorkspaceIconButton
                label="返回 Agent 会话"
                onClick={() =>
                  navigate(
                    "chat",
                    state.detail?.session.agent_key === MAINTENANCE_AGENT_KEY ? sessionId : "",
                    MAINTENANCE_AGENT_KEY,
                    requestedLibrary,
                  )
                }
              >
                <ArrowLeft />
              </WorkspaceIconButton>
            )}
            <span>{title}</span>
          </div>
          <div className="aw-inline-actions">
            {agentKey && view === "chat" && (
              <WorkspaceIconButton
                label="新建 Agent 任务"
                onClick={() => navigate("chat", "", agentKey)}
              >
                <Plus />
              </WorkspaceIconButton>
            )}
            {sessionId && view === "chat" && state.detail && (
              <>
                <WorkspaceIconButton
                  label="重命名会话"
                  onClick={() => {
                    setRename(state.detail!.session.title);
                    setDialogError("");
                    setDialog("rename");
                  }}
                >
                  <Pencil />
                </WorkspaceIconButton>
                <WorkspaceIconButton
                  label="删除会话"
                  onClick={() => {
                    setDialogError("");
                    setDialog("delete");
                  }}
                >
                  <Trash2 />
                </WorkspaceIconButton>
              </>
            )}
            <WorkspaceIconButton label="使用说明" onClick={() => navigate("help")}>
              <HelpCircle />
            </WorkspaceIconButton>
            {view === "chat" && (state.detail?.artifacts.length ?? 0) > 0 && (
              <WorkspaceIconButton
                label={showPreview ? "收起文档预览" : "打开文档预览"}
                onClick={() =>
                  updateView({
                    artifact:
                      artifact?.id ||
                      state.detail!.artifacts[state.detail!.artifacts.length - 1].id,
                    previewOpen: !showPreview,
                  })
                }
              >
                <PanelRight />
              </WorkspaceIconButton>
            )}
          </div>
        </header>
        {state.initialError && (
          <div className="aw-banner" role="alert">
            {state.initialError}
            <WorkspaceIconButton label="重试" onClick={state.reloadOptions}>
              <RotateCcw />
            </WorkspaceIconButton>
          </div>
        )}
        {view === "chat" ? (
          <div className="aw-body">
            <section className="aw-chat" aria-label="会话">
              {agentKey === MAINTENANCE_AGENT_KEY && (
                <nav className="aw-agent-context" aria-label="知识维护辅助视图">
                  <span>
                    <Bot size={15} />
                    知识维护 Agent
                  </span>
                  <div>
                    {(
                      [
                        ["issues", "维护待办"],
                        ["runs", "巡检记录"],
                        ["settings", "巡检设置"],
                      ] as const
                    ).map(([tab, label]) => (
                      <Link
                        key={tab}
                        to={maintenanceAgentHref(lastAgentLocation?.search ?? "", {
                          tab,
                          session: sessionId || null,
                          library: selected.context || "company",
                          target_id: null,
                          digest_id: null,
                          view: null,
                          page: null,
                        })}
                      >
                        {label}
                      </Link>
                    ))}
                  </div>
                </nav>
              )}
              <div ref={scroll} className="aw-chat-scroll" onScroll={onScroll}>
                {!sessionId ? (
                  <div className="aw-home">
                    <div className="aw-orbit" aria-hidden="true">
                      <i />
                      <i />
                      <i />
                      <b />
                      <b />
                    </div>
                    <div className="aw-greeting">
                      {agentKey ? <Bot /> : <Sparkles />}
                      <h1>{agentKey ? "交给我一个知识维护目标" : "今天，想推进什么？"}</h1>
                      <p>
                        {agent?.description ??
                          (agentKey
                            ? "选择知识库，说明目标；在这里持续查看进展、核对依据和跟进结果。"
                            : "带上资料和目标，一起把想法变成可以使用的内容。")}
                      </p>
                    </div>
                  </div>
                ) : state.loading && !state.detail ? (
                  <p className="aw-loading" role="status">
                    正在读取会话…
                  </p>
                ) : state.detail ? (
                  <div className="aw-transcript">
                    {state.detail.runs.map((run) => (
                      <section
                        className="aw-turn"
                        key={run.id}
                        aria-label={`任务：${runLabels[run.status]}`}
                      >
                        {state
                          .detail!.messages.filter(
                            (message) => message.run_id === run.id && message.role === "user",
                          )
                          .map((message) => (
                            <div className="aw-question" key={message.id}>
                              {message.content}
                            </div>
                          ))}
                        <div className="aw-answer">
                          <div className="aw-answer-brand">
                            <Sparkles size={16} />
                            {agent?.label ?? "博维 AI"}{" "}
                            <span className={`aw-run-status is-${run.status}`}>
                              {runLabels[run.status]}
                            </span>
                          </div>
                          <details className="aw-activity">
                            <summary>
                              <ChevronRight size={14} />
                              执行过程
                              {state.events.filter((event) => event.run_id === run.id).length
                                ? ` · ${state.events.filter((event) => event.run_id === run.id).length} 条进展`
                                : ""}
                            </summary>
                            <ol>
                              {state.events
                                .filter((event) => event.run_id === run.id)
                                .map((event) => (
                                  <li key={event.id}>
                                    <Circle size={10} aria-hidden="true" />
                                    <span>{event.label}</span>
                                  </li>
                                ))}
                              {!state.events.some((event) => event.run_id === run.id) && (
                                <li>正在读取执行记录。</li>
                              )}
                            </ol>
                            <ToolReceipts
                              actions={(state.detail?.actions ?? []).filter(
                                (action) => action.run_id === run.id,
                              )}
                            />
                          </details>
                          {state
                            .detail!.messages.filter(
                              (message) =>
                                message.run_id === run.id && message.role === "assistant",
                            )
                            .map((message) => (
                              <div className="aw-answer-content" key={message.id}>
                                <MarkdownView text={message.content} />
                              </div>
                            ))}
                          {state
                            .detail!.artifacts.filter((item) => item.run_id === run.id)
                            .map((item) => (
                              <button
                                className="aw-artifact-link"
                                key={item.id}
                                onClick={() => openArtifact(item)}
                              >
                                <FileText />
                                <span>
                                  <strong>{item.title}</strong>
                                  <small>文档 · 第 {item.revision} 版 · 点击预览和编辑</small>
                                </span>
                                <ChevronRight />
                              </button>
                            ))}
                          {run.status === "failed" && (
                            <p className="aw-run-error">
                              {failureLabels[run.error_code ?? ""] ||
                                "本次处理未完成，可以查看执行过程后继续任务。"}
                            </p>
                          )}
                          {(run.status === "failed" ||
                            run.status === "stopped" ||
                            (run.status === "waiting" &&
                              run.waiting_reason !== "external_task")) && (
                            <WorkspaceIconButton
                              label="继续任务"
                              disabled={
                                Boolean(activeRun && activeRun.id !== run.id) || operationBusy
                              }
                              onClick={() => void runAction(run, "resume")}
                            >
                              <RotateCcw />
                            </WorkspaceIconButton>
                          )}
                          {run.status === "awaiting_confirmation" && run.pending_action && (
                            <ActionConfirmation
                              action={run.pending_action}
                              busy={operationBusy}
                              onDecision={(decision) => void decideAction(run, decision)}
                            />
                          )}
                          {isWorkspaceRunActive(run) && (
                            <p className="aw-running" role="status">
                              {run.status === "queued"
                                ? "任务已提交，等待执行…"
                                : run.status === "awaiting_confirmation"
                                  ? "任务已暂停，等待你核对并确认上面的操作。"
                                  : run.status === "waiting"
                                    ? run.waiting_reason === "external_task"
                                      ? "后台任务仍在执行，Agent 会自动查看结果。你也可以补充要求。"
                                      : run.waiting_reason === "step_budget"
                                        ? "已保存本轮进展。可以继续任务，或补充下一步要求。"
                                        : "等待你补充信息，可以在下方继续回复。"
                                    : "正在处理，进展会显示在这里。"}
                            </p>
                          )}
                        </div>
                      </section>
                    ))}
                    {state.detail.messages.length === 0 && (
                      <p className="aw-muted">这段会话还没有消息，从下方输入开始。</p>
                    )}
                  </div>
                ) : state.deniedSession ? (
                  <p className="aw-loading">该会话已删除，或当前身份无法访问。可以新建会话继续。</p>
                ) : null}
              </div>
              {state.connectionError && (
                <div className="aw-banner" role="alert">
                  {state.connectionError}
                  <WorkspaceIconButton label="重新连接" onClick={state.refresh}>
                    <RotateCcw />
                  </WorkspaceIconButton>
                </div>
              )}
              {sessionId && !followLatest && (
                <WorkspaceIconButton className="aw-jump" label="回到最新消息" onClick={jumpLatest}>
                  <ArrowDown size={14} />
                </WorkspaceIconButton>
              )}
              {!state.deniedSession && (
                <div className={`aw-composer-area${!sessionId ? " is-home" : ""}`}>
                  <form
                    className="aw-composer"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void send();
                    }}
                  >
                    <textarea
                      ref={editor}
                      aria-label="消息"
                      placeholder={
                        activeRun
                          ? "补充要求，继续这项任务…"
                          : agentKey
                            ? "希望检查哪些知识？说明目标，我会逐步检查并提供依据…"
                            : "描述你想完成的事，也可以直接粘贴资料…"
                      }
                      value={selected.input}
                      maxLength={32000}
                      rows={3}
                      onChange={(event) => updateView({ input: event.target.value })}
                      onKeyDown={(event) => {
                        if (
                          event.key === "Enter" &&
                          !event.shiftKey &&
                          !event.nativeEvent.isComposing
                        ) {
                          event.preventDefault();
                          void send();
                        }
                      }}
                    />
                    <div className="aw-composer-toolbar">
                      <div className="aw-composer-left">
                        <WorkspaceIconButton
                          className="aw-icon aw-context-button"
                          label="添加上下文"
                          tooltip={
                            selected.context
                              ? `上下文：${state.options?.contexts.find((context) => context.key === selected.context)?.label || "此前知识库不可用"}，点击更换`
                              : "添加上下文"
                          }
                          data-selected={Boolean(selected.context)}
                          disabled={Boolean(activeRun)}
                          onClick={() => setDialog("context")}
                        >
                          <Layers2 size={15} />
                          {selected.context && (
                            <span className="aw-selection-dot" aria-hidden="true" />
                          )}
                        </WorkspaceIconButton>
                        {!sessionId && (
                          <AgentPicker
                            agents={state.options ? (state.options.agents ?? []) : undefined}
                            value={agentKey}
                            disabled={submitting.has(key)}
                            onChange={selectAgent}
                          />
                        )}
                      </div>
                      <div className="aw-composer-right">
                        <span className="aw-model-picker" data-available={Boolean(availableModel)}>
                          <Cpu className="aw-model-icon" aria-hidden="true" />
                          <WorkspaceTooltip
                            label={
                              state.options?.models.find(
                                (model) => model.model_ref === selected.model,
                              )?.display_name
                                ? `对话模型：${state.options.models.find((model) => model.model_ref === selected.model)!.display_name}`
                                : state.options
                                  ? "未配置可用模型，请联系管理员"
                                  : "正在读取可用模型"
                            }
                          >
                            <select
                              className="aw-model-select"
                              aria-label="对话模型"
                              value={selected.model}
                              onChange={(event) => updateView({ model: event.target.value })}
                              disabled={!state.options?.models.length || Boolean(activeRun)}
                            >
                              <option value="" disabled>
                                {state.options ? "未配置可用模型" : "读取模型…"}
                              </option>
                              {selected.model && !availableModel && (
                                <option value={selected.model} disabled>
                                  此前模型不可用
                                </option>
                              )}
                              {state.options?.models.map((model) => (
                                <option value={model.model_ref} key={model.model_ref}>
                                  {model.display_name}
                                </option>
                              ))}
                            </select>
                          </WorkspaceTooltip>
                        </span>
                        {activeRun && (
                          <WorkspaceIconButton
                            className="aw-send"
                            label="停止处理"
                            disabled={operationBusy}
                            onClick={() => void runAction(activeRun, "stop")}
                          >
                            <Square size={14} fill="currentColor" />
                          </WorkspaceIconButton>
                        )}
                        {activeRun?.status !== "awaiting_confirmation" && (
                          <WorkspaceIconButton
                            className="aw-send"
                            type="submit"
                            label={activeRun ? "补充并继续" : "发送消息"}
                            disabled={
                              busy || !selected.input.trim() || !availableModel || unknownAgent
                            }
                          >
                            <ArrowUp size={18} />
                          </WorkspaceIconButton>
                        )}
                      </div>
                    </div>
                  </form>
                  <div className="aw-compose-foot">
                    <span>
                      {selected.input.length > 30000
                        ? `${selected.input.length} / 32000 字符`
                        : "Enter 发送，Shift + Enter 换行"}
                    </span>
                    <span>
                      <ShieldCheck size={12} />
                      按当前身份访问资料
                    </span>
                  </div>
                  {state.options && !state.options.models.length && (
                    <p className="aw-model-warning">
                      当前没有可用对话模型，请联系管理员在 KAP 的模型配置中添加或启用。
                    </p>
                  )}
                  {unknownAgent && (
                    <p className="aw-model-warning" role="alert">
                      当前身份无法使用这个智能体，请在输入框旁选择可用的智能体或通用对话。
                    </p>
                  )}
                  {error && (
                    <p className="aw-inline-error" role="alert">
                      {error}
                    </p>
                  )}
                  {!sessionId && (
                    <div className="aw-shortcuts">
                      {(
                        (agentKey
                          ? [
                              [
                                ShieldCheck,
                                "检查敏感信息",
                                "核对摘要和正文中的泄露风险",
                                "请检查所选知识库中敏感个人信息的泄露风险，列出可核实的依据和需要维护人处理的事项，不要在回复中复述敏感原值。",
                              ],
                              [
                                FileDiff,
                                "核对当前版本",
                                "比较重复资料与版本关系",
                                "请检查所选知识库中可能重复或存在新版的资料，先核对当前版本，再给出判断依据和处理建议。",
                              ],
                              [
                                History,
                                "跟进未解决问题",
                                "查看进展，复检后再关闭",
                                "请跟进所选知识库中还没有解决的维护问题，核对当前版本和处理进展，对已修正的问题复检，通过后再关闭。",
                              ],
                            ]
                          : [
                              [
                                BookOpen,
                                "阅读资料",
                                "提炼要点，解释复杂内容",
                                "请阅读以下资料，整理关键结论和需要进一步确认的问题：\n",
                              ],
                              [
                                FileText,
                                "整理文档",
                                "把想法整理成可编辑文档",
                                "请帮我整理一份文档。用途是：\n需要包含的内容：\n",
                              ],
                              [
                                FileDiff,
                                "比较文件",
                                "粘贴两份内容，梳理差异",
                                "请比较下面两份内容，说明关键差异及影响：\n资料一：\n\n资料二：\n",
                              ],
                              [
                                Table2,
                                "分析表格",
                                "粘贴表格，归纳发现",
                                "请分析以下表格内容，总结趋势、异常和建议：\n",
                              ],
                            ]) as [typeof BookOpen, string, string, string][]
                      ).map(([Icon, name, description, prompt]) => (
                        <button
                          className="aw-shortcut"
                          key={name}
                          onClick={() => {
                            updateView({ input: selected.input || prompt });
                            editor.current?.focus();
                          }}
                        >
                          <Icon />
                          <span>
                            <strong>{name}</strong>
                            <small>{description}</small>
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </section>
            {artifact && (
              <ArtifactPanel
                key={artifact.id}
                savedScrollTop={
                  previewPositions.current[`${artifact.id}:${selected.previewTab}`] ?? 0
                }
                onScrollPosition={(top) => {
                  previewPositions.current[`${artifact.id}:${selected.previewTab}`] = top;
                }}
                sessionId={sessionId}
                artifact={artifact}
                draft={artifactDrafts[artifact.id]}
                updateDraft={updateArtifactDraft}
                tab={selected.previewTab}
                setTab={(previewTab) => updateView({ previewTab })}
                open={showPreview}
                full={selected.previewFull}
                setFull={(previewFull) => updateView({ previewFull })}
                onClose={() => updateView({ previewOpen: false })}
                onSaved={state.refresh}
              />
            )}
          </div>
        ) : view === "maintenance" ? (
          <div className="aw-agent-workspace aw-section-scroll" aria-label="知识维护 Agent 工作区">
            <Suspense
              fallback={
                <p className="aw-loading" role="status">
                  正在打开知识维护 Agent…
                </p>
              }
            >
              <MaintenanceAgentPage
                embedded
                agentSessionId={
                  state.detail?.session.agent_key === MAINTENANCE_AGENT_KEY ? sessionId : undefined
                }
              />
            </Suspense>
          </div>
        ) : (
          <div className="aw-section-scroll">
            <section className="aw-entry">
              {view === "agents" && (
                <>
                  <Bot className="aw-entry-symbol" />
                  <h1>让 Agent 接手一类工作</h1>
                  <p className="aw-section-intro">
                    选择擅长这项工作的 Agent，在会话里交代目标、核对执行依据并持续跟进。
                  </p>
                  {state.options?.agents?.map((item) => (
                    <details className="aw-agent-row" key={item.key}>
                      <summary>
                        <BookOpen />
                        <span>
                          <strong>{item.label}</strong>
                          <small>{item.description}</small>
                        </span>
                        <span className="aw-agent-status">
                          已可用
                          <ChevronRight />
                        </span>
                      </summary>
                      <div className="aw-agent-description">
                        <p>
                          任务与进展保存在会话里；需要确认的操作会先列出具体内容，产物可在右侧预览。
                        </p>
                        <p>{item.tools.map((tool) => tool.label).join(" · ")}</p>
                        <Link className="aw-text-button" to={agentConversationHref(item.key)}>
                          开始任务
                          <ChevronRight />
                        </Link>
                      </div>
                    </details>
                  ))}
                  {state.options && !state.options.agents?.length && (
                    <p className="aw-muted">当前身份没有可用的 Agent。</p>
                  )}
                </>
              )}
              {view === "tools" && (
                <>
                  <Wrench className="aw-entry-symbol" />
                  <h1>工作空间工具</h1>
                  <p className="aw-section-intro">
                    对话会按任务使用这些能力。知识访问遵循你在 KAP 中的权限。
                  </p>
                  {tools.map((tool) => (
                    <div className="aw-tool-row" key={tool.key}>
                      <Wrench />
                      <span>
                        <strong>{tool.label}</strong>
                        <small>{tool.description}</small>
                      </span>
                      <Check />
                    </div>
                  ))}
                  {state.options && !tools.length && (
                    <p className="aw-muted">当前没有已接入的工具。</p>
                  )}
                </>
              )}
              {view === "preferences" && (
                <>
                  <Settings2 className="aw-entry-symbol" />
                  <h1>偏好设置</h1>
                  <div className="aw-preference-row">
                    <span>
                      <strong>界面动效</strong>
                      <small>轻量过渡与欢迎图案。系统减少动态效果的设置始终优先。</small>
                    </span>
                    <input
                      type="checkbox"
                      aria-label="启用界面动效"
                      checked={motion}
                      onChange={(event) => setMotionPreference(event.target.checked)}
                    />
                  </div>
                  <div className="aw-preference-row">
                    <span>
                      <strong>模型与连接</strong>
                      <small>使用 KAP 已配置的模型，无需重复设置密钥。</small>
                    </span>
                    <WorkspaceIconButton label="重新读取模型" onClick={state.reloadOptions}>
                      <RotateCcw />
                    </WorkspaceIconButton>
                  </div>
                  <div className="aw-preference-row">
                    <span>
                      <strong>会话与草稿</strong>
                      <small>
                        已发送消息和已保存文档存储在当前身份下。未发送内容和未保存修改只保留在本页。
                      </small>
                    </span>
                  </div>
                </>
              )}
              {view === "help" && (
                <>
                  <HelpCircle className="aw-entry-symbol" />
                  <h1>把任务交代清楚，再一起推进</h1>
                  <div className="aw-help-row">
                    <strong>先给目标，再给资料</strong>
                    <p>
                      可以连续追问、粘贴内容，或添加有权访问的知识库上下文。未选择知识库时，仅使用本次会话中的内容。
                    </p>
                  </div>
                  <div className="aw-help-row">
                    <strong>查看执行过程和文档</strong>
                    <p>
                      处理过程会持续更新。生成的文档可在右侧阅读、编辑、比较修改并保存，支持复制和下载。
                    </p>
                  </div>
                  <div className="aw-help-row">
                    <strong>补充要求、停止和继续任务</strong>
                    <p>
                      执行中可以补充要求或停止；失败或停止后可从已保存的进展继续。会话顶部可以重命名和删除，删除会同时清理这段会话的文档。
                    </p>
                  </div>
                  <div className="aw-help-row">
                    <strong>在会话里使用 Agent</strong>
                    <p>
                      在新会话输入框旁点击“添加智能体”，即可选择专门的工具和职责。侧栏 Agent
                      可查看介绍。知识维护 Agent
                      可以查看问题、开展巡检和复检、准备维护报告。会话上方的待办、记录与设置用于查看明细和配置；需要确认的操作由你核对后执行。
                    </p>
                  </div>
                  <div className="aw-help-row">
                    <strong>当前支持的资料方式</strong>
                    <p>
                      支持粘贴文本、Markdown
                      和表格文本，以及已授权的知识库上下文。长文档建议按章节提供；本页暂不接收本地文件上传。
                    </p>
                  </div>
                </>
              )}
            </section>
          </div>
        )}
      </main>
      {dialog === "context" && (
        <WorkspaceDialog title="添加上下文" onClose={() => setDialog(null)}>
          <p className="aw-muted">选择当前对话使用的知识库；可访问范围仍由你的权限决定。</p>
          <label className="aw-context-choice">
            <input
              type="radio"
              name="context"
              checked={!selected.context}
              onChange={() => updateView({ context: "" })}
            />
            <span>
              仅当前会话<small>不检索知识库</small>
            </span>
          </label>
          {state.options?.contexts.map((context) => (
            <label className="aw-context-choice" key={context.key}>
              <input
                type="radio"
                name="context"
                checked={selected.context === context.key}
                onChange={() => updateView({ context: context.key })}
              />
              <span>{context.label}</span>
            </label>
          ))}
          <footer>
            <button className="aw-primary" onClick={() => setDialog(null)}>
              完成
            </button>
          </footer>
        </WorkspaceDialog>
      )}
      {(dialog === "rename" || dialog === "delete") && (
        <WorkspaceDialog
          title={dialog === "rename" ? "重命名会话" : "删除会话"}
          onClose={() => {
            if (!operationBusy) setDialog(null);
          }}
        >
          {dialog === "rename" ? (
            <label className="aw-field">
              会话名称
              <input
                value={rename}
                maxLength={120}
                onChange={(event) => setRename(event.target.value)}
              />
            </label>
          ) : (
            <p>
              删除这段会话及其中的消息、执行记录和文档。正在执行的任务会停止，未保存的草稿也会被清理。
            </p>
          )}
          {dialogError && (
            <p role="alert" className="aw-inline-error">
              {dialogError}
            </p>
          )}
          <footer>
            <button
              className="aw-text-button"
              disabled={operationBusy}
              onClick={() => setDialog(null)}
            >
              取消
            </button>
            <button
              className={`aw-primary${dialog === "delete" ? " is-danger" : ""}`}
              disabled={operationBusy || (dialog === "rename" && !rename.trim())}
              onClick={() => void saveSessionChange()}
            >
              {operationBusy ? "处理中…" : dialog === "rename" ? "保存名称" : "确认删除"}
            </button>
          </footer>
        </WorkspaceDialog>
      )}
    </div>
  );
}
