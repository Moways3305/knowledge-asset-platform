import { AgentCallButton } from "../components/operations/ReadTools";
import ProjectModuleFrame from "../components/ProjectModuleFrame";
import ResponsiveEvidencePanel from "../components/ResponsiveEvidencePanel";
import ProjectWorkspaceNav from "../components/ProjectWorkspaceNav";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bot,
  CheckSquare,
  FolderKanban,
  Plus,
  RefreshCw,
  Send,
  Upload,
  ArrowRight,
  FileCheck,
  KeyRound,
  LibraryBig,
  Settings2,
} from "lucide-react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  fetchProjectOverview,
  fetchProjectQaModelOptions,
  fetchProjects,
  projectQa,
} from "../api/project";
import { useAuth } from "../auth/AuthContext";
import CreateProjectModal from "../components/CreateProjectModal";
import LoadingError from "../components/LoadingError";
import { PageHeader, PageSection, ProductPage } from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import { formatBeijingTime } from "../utils/time";
import type { ProjectQaModelOptionDTO, ProjectQaResponseDTO } from "../types/agent";
import type { ProjectListItemDTO, ProjectOverviewDTO } from "../types/project";
import "./ProjectOverviewPage.css";

const PROJECT_STATUS: Record<string, string> = {
  active: "进行中",
  completed: "已完成",
  archived: "已归档",
};

const PROJECT_ROLE: Record<string, string> = {
  project_manager: "项目经理",
  coach: "项目教练",
  consultant: "顾问",
};

const MEMBER_STATUS: Record<string, string> = {
  active: "在项目中",
  inactive: "已停用",
};

const KB_STATUS: Record<string, string> = {
  active: "已启用",
  initializing: "配置中",
  pending: "待配置",
  init_failed: "配置失败",
  disabled: "已停用",
};

const CITED_ZONE: Record<string, string> = {
  material: "资料区",
  asset: "资产区",
};

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: ProjectListItemDTO[] };

type OverviewState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: ProjectOverviewDTO };

type ModelState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: ProjectQaModelOptionDTO[]; selectedRef: string };

type ConversationState =
  | { status: "idle" }
  | { status: "asking"; question: string }
  | { status: "error"; question: string }
  | { status: "answer"; question: string; result: ProjectQaResponseDTO };

function safeErrorMessage(): string {
  return "暂时无法加载，请稍后重试";
}

function ProjectPicker({
  projects,
  value,
  onChange,
}: {
  projects: ProjectListItemDTO[];
  value: string;
  onChange: (projectId: string) => void;
}) {
  return (
    <label className="project78-picker">
      <span>切换项目</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {!value && <option value="">选择可访问项目</option>}
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function ProjectWorkspace({
  selectedProject,
  projects,
  onSwitch,
  onCreateClick,
  canCreate,
}: {
  selectedProject: ProjectListItemDTO;
  projects: ProjectListItemDTO[];
  onSwitch: (projectId: string) => void;
  onCreateClick?: () => void;
  canCreate?: boolean;
}) {
  const projectId = selectedProject.id;
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view") === "qa" ? "qa" : "overview";
  const overviewRequest = useRef(0);
  const modelRequest = useRef(0);
  const modelLoaded = useRef(false);
  const qaRequest = useRef(0);
  const [overviewState, setOverviewState] = useState<OverviewState>({ status: "loading" });
  const [modelState, setModelState] = useState<ModelState>({ status: "loading" });
  const [conversation, setConversation] = useState<ConversationState>({ status: "idle" });
  const [question, setQuestion] = useState("");

  const loadOverview = useCallback(async () => {
    const request = ++overviewRequest.current;
    setOverviewState({ status: "loading" });
    try {
      const response = await fetchProjectOverview(projectId);
      if (request !== overviewRequest.current) return;
      if (response.project.project_id !== projectId) {
        setOverviewState({ status: "error", message: safeErrorMessage() });
        return;
      }
      setOverviewState({ status: "ready", data: response });
    } catch {
      if (request === overviewRequest.current) {
        setOverviewState({ status: "error", message: safeErrorMessage() });
      }
    }
  }, [projectId]);

  const loadModels = useCallback(async () => {
    const request = ++modelRequest.current;
    setModelState({ status: "loading" });
    try {
      const response = await fetchProjectQaModelOptions(projectId);
      if (request !== modelRequest.current) return;
      modelLoaded.current = true;
      const selected = response.items.find((item) => item.is_default) ?? response.items[0];
      setModelState({
        status: "ready",
        items: response.items,
        selectedRef: selected?.model_ref ?? "",
      });
    } catch {
      if (request === modelRequest.current) setModelState({ status: "error" });
    }
  }, [projectId]);

  useEffect(() => {
    void loadOverview();
    return () => {
      overviewRequest.current += 1;
      qaRequest.current += 1;
    };
  }, [loadOverview]);

  useEffect(() => {
    if (view === "qa" && !modelLoaded.current) void loadModels();
    return () => {
      modelRequest.current += 1;
    };
  }, [loadModels, view]);

  const submitQuestion = useCallback(
    async (value: string) => {
      const trimmed = value.trim();
      if (!trimmed || modelState.status !== "ready" || !modelState.selectedRef) return;
      const request = ++qaRequest.current;
      setConversation({ status: "asking", question: trimmed });
      setQuestion("");
      try {
        const response = await projectQa(projectId, {
          query: trimmed,
          modelRef: modelState.selectedRef,
        });
        if (request === qaRequest.current) {
          setConversation({ status: "answer", question: trimmed, result: response });
        }
      } catch {
        if (request === qaRequest.current) {
          setConversation({ status: "error", question: trimmed });
        }
      }
    },
    [modelState, projectId],
  );

  if (overviewState.status !== "ready") {
    return (
      <ProjectModuleFrame
        navigation={
          <ProjectWorkspaceNav
            projectId={projectId}
            current={view}
            canManage={selectedProject.can_manage}
          />
        }
      >
        <ProductPage className="project78-page">
          {overviewState.status === "loading" ? (
            <LoadingError loading loadingTitle="正在加载项目空间…" />
          ) : (
            <LoadingError
              error={overviewState.message}
              errorTitle="项目概览加载失败"
              onRetry={() => void loadOverview()}
            />
          )}
        </ProductPage>
      </ProjectModuleFrame>
    );
  }

  const overview = overviewState.data;
  const selectedModel =
    modelState.status === "ready"
      ? modelState.items.find((item) => item.model_ref === modelState.selectedRef)
      : undefined;
  const canAsk = modelState.status === "ready" && Boolean(modelState.selectedRef);
  const asking = conversation.status === "asking";

  return (
    <ProjectModuleFrame
      navigation={
        <ProjectWorkspaceNav
          projectId={projectId}
          current={view}
          canManage={overview.capabilities.can_manage_members}
          canViewKnowledge={overview.capabilities.can_view_knowledge}
        />
      }
    >
      <ProductPage className="project78-page">
        <PageHeader
          title={
            <span className="project78-object-title">
              <span className="workspace-project-mark" aria-hidden="true">
                <FolderKanban size={24} />
              </span>
              {overview.project.name}
            </span>
          }
          description={
            <>
              {overview.project.client_name && <span>{overview.project.client_name} · </span>}
              {PROJECT_ROLE[overview.project.project_role] ?? "项目成员"}
            </>
          }
          status={
            <StatusBadge
              label={PROJECT_STATUS[overview.project.status] ?? "状态待确认"}
              tone={overview.project.status === "active" ? "success" : "neutral"}
            />
          }
          actions={
            <div className="project78-header-actions">
              {canCreate && onCreateClick && (
                <button
                  type="button"
                  className="product-button is-secondary"
                  onClick={onCreateClick}
                >
                  <Plus size={14} aria-hidden="true" />
                  新建项目
                </button>
              )}
              {overview.capabilities.can_upload_material && (
                <Link
                  className="product-button is-primary"
                  to={`/upload?source=local&project_id=${encodeURIComponent(projectId)}`}
                >
                  <Upload size={16} />
                  上传资料
                </Link>
              )}
              <ProjectPicker projects={projects} value={projectId} onChange={onSwitch} />
            </div>
          }
        />

        {view === "overview" ? (
          <div className="project-work-layout">
            <div className="project-work-main">
              <PageSection
                title="项目工作"
                description="查看当前项目的待办情况，继续整理和确认知识。"
              >
                <dl className="project-work-queue">
                  <div>
                    <dt>待确认</dt>
                    <dd>{overview.counts.pending_confirmation_count}</dd>
                    {overview.capabilities.can_upload_material && (
                      <Link to={`/upload?source=local&project_id=${encodeURIComponent(projectId)}`}>
                        <FileCheck size={15} />
                        继续确认上传
                      </Link>
                    )}
                  </div>
                  <div>
                    <dt>待审核</dt>
                    <dd>{overview.counts.pending_review_count}</dd>
                    {overview.capabilities.can_confirm_assets && (
                      <Link to={`/review?project_id=${encodeURIComponent(projectId)}`}>
                        <CheckSquare size={15} />
                        查看项目审核
                      </Link>
                    )}
                  </div>
                  <div>
                    <dt>原文申请</dt>
                    <dd>{overview.counts.original_access_request_count}</dd>
                    {["project_manager", "coach"].includes(overview.project.project_role) && (
                      <Link
                        to={`/original-access?box=inbox&project_id=${encodeURIComponent(projectId)}`}
                      >
                        <KeyRound size={15} />
                        处理原文申请
                      </Link>
                    )}
                  </div>
                </dl>
              </PageSection>

              <nav className="project-work-shortcuts" aria-label="项目常用操作">
                {overview.capabilities.can_view_knowledge && (
                  <Link to={`/project/${encodeURIComponent(projectId)}/knowledge`}>
                    <LibraryBig size={18} />
                    <span>
                      <strong>浏览项目资料</strong>
                      <small>查找过程资料与已验证资产</small>
                    </span>
                    <ArrowRight size={16} />
                  </Link>
                )}
                <Link to={`/project/${encodeURIComponent(projectId)}?view=qa`}>
                  <Bot size={18} />
                  <span>
                    <strong>向项目提问</strong>
                    <small>围绕本项目知识查询与核对依据</small>
                  </span>
                  <ArrowRight size={16} />
                </Link>
              </nav>

              {overview.capabilities.can_view_knowledge && (
                <PageSection
                  title="最近项目资料"
                  description="继续查看本项目最近更新的可访问资料。"
                  actions={
                    <Link to={`/project/${encodeURIComponent(projectId)}/knowledge`}>
                      查看全部资料
                    </Link>
                  }
                >
                  {overview.recent_activity.length > 0 ? (
                    <ul className="project78-recent-list">
                      {overview.recent_activity.map((item) => (
                        <li key={item.asset_id}>
                          <Link
                            to={`/knowledge/${encodeURIComponent(item.asset_id)}`}
                            state={{
                              backTo: `/project/${encodeURIComponent(projectId)}`,
                              backLabel: "返回项目概览",
                              source: "project",
                            }}
                          >
                            {item.title}
                          </Link>
                          <span>{CITED_ZONE[item.zone] ?? "区域待确认"}</span>
                          <time>{formatBeijingTime(item.updated_at)}</time>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="project78-muted">暂无最近更新的项目资料。</p>
                  )}
                </PageSection>
              )}
            </div>
            <aside className="project-work-context" aria-label="项目资料与成员">
              {" "}
              <dl className="project78-facts" aria-label="项目数据概览">
                <div>
                  <dt>资料</dt>
                  <dd>{overview.counts.material_count}</dd>
                </div>
                <div>
                  <dt>资产</dt>
                  <dd>{overview.counts.asset_count}</dd>
                </div>
                <div>
                  <dt>知识库</dt>
                  <dd>
                    {overview.knowledge_base.configured
                      ? (KB_STATUS[overview.knowledge_base.status ?? ""] ?? "状态待确认")
                      : "尚未配置"}
                  </dd>
                </div>
              </dl>{" "}
              {overview.capabilities.can_manage_members && (
                <details className="project78-members">
                  <summary>项目协作成员（{overview.members.length}）</summary>
                  {overview.members.length > 0 ? (
                    <ul>
                      {overview.members.map((member) => (
                        <li key={member.user_id}>
                          <span className="project78-member-mark" aria-hidden="true">
                            {member.name.slice(0, 1)}
                          </span>
                          <span>
                            <strong>{member.name}</strong>
                            <small>{PROJECT_ROLE[member.project_role] ?? "项目成员"}</small>
                          </span>
                          <em>{MEMBER_STATUS[member.status] ?? "状态待确认"}</em>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="project78-muted">暂无成员信息。</p>
                  )}
                </details>
              )}
              {overview.capabilities.can_manage_members && (
                <Link
                  className="project-settings-entry"
                  to={`/project/${encodeURIComponent(projectId)}/settings`}
                >
                  <Settings2 size={16} />
                  成员与设置
                  <ArrowRight size={16} />
                </Link>
              )}
            </aside>
          </div>
        ) : (
          <section className="project78-assistant" aria-labelledby="project78-assistant-title">
            <header className="project78-assistant-header">
              <div className="project78-assistant-title">
                <span className="project78-bot-mark" aria-hidden="true">
                  <Bot size={17} />
                </span>
                <div>
                  <h2 id="project78-assistant-title">项目 AI 助手</h2>
                  <p>
                    {modelState.status === "loading" && "正在确认可用问答模型"}
                    {modelState.status === "error" && "问答模型暂时不可用"}
                    {modelState.status === "ready" &&
                      modelState.items.length === 0 &&
                      "当前项目暂无可用问答模型"}
                    {selectedModel && `当前可用模型：${selectedModel.display_name}`}
                  </p>
                </div>
              </div>
              {modelState.status === "error" && (
                <button
                  type="button"
                  className="project78-model-retry"
                  onClick={() => void loadModels()}
                >
                  <RefreshCw size={14} aria-hidden="true" />
                  重试
                </button>
              )}
            </header>

            <div className="project-answer-layout">
              <div className="project-answer-main">
                <div className="project78-conversation" aria-live="polite">
                  {conversation.status === "idle" && (
                    <div className="project78-message is-assistant is-welcome">
                      <span className="project78-message-avatar" aria-hidden="true">
                        <Bot size={16} />
                      </span>
                      <div>
                        <strong>项目 AI 助手</strong>
                        <p>可以围绕“{overview.project.name}”的项目知识提问。</p>
                      </div>
                    </div>
                  )}

                  {conversation.status !== "idle" && (
                    <div className="project78-message is-user">
                      <div>
                        <strong>你</strong>
                        <p>{conversation.question}</p>
                      </div>
                    </div>
                  )}

                  {conversation.status === "asking" && (
                    <div className="project78-message is-assistant">
                      <span className="project78-message-avatar" aria-hidden="true">
                        <Bot size={16} />
                      </span>
                      <div>
                        <strong>项目 AI 助手</strong>
                        <p className="project78-thinking">正在整理项目知识…</p>
                      </div>
                    </div>
                  )}

                  {conversation.status === "error" && (
                    <div className="project78-message is-assistant is-error">
                      <span className="project78-message-avatar" aria-hidden="true">
                        <Bot size={16} />
                      </span>
                      <div>
                        <strong>问答未成功</strong>
                        <p>暂时无法完成回答，请稍后重试。</p>
                        <button
                          type="button"
                          onClick={() => void submitQuestion(conversation.question)}
                        >
                          重新提问
                        </button>
                      </div>
                    </div>
                  )}

                  {conversation.status === "answer" && (
                    <div className="project78-message is-assistant">
                      <span className="project78-message-avatar" aria-hidden="true">
                        <Bot size={16} />
                      </span>
                      <div>
                        <strong>项目 AI 助手</strong>
                        {conversation.result.answer_status === "insufficient_evidence" && (
                          <span>依据不足</span>
                        )}
                        <p>{conversation.result.response_text}</p>
                        <AgentCallButton callId={conversation.result.call_id} />
                      </div>
                    </div>
                  )}
                </div>

                <div className="project78-composer">
                  <label className="project78-sr-only" htmlFor="project78-question">
                    向项目 AI 助手提问
                  </label>
                  <textarea
                    id="project78-question"
                    value={question}
                    rows={2}
                    placeholder={canAsk ? "向项目知识提问…" : "当前没有可用问答模型"}
                    disabled={!canAsk || asking}
                    onChange={(event) => setQuestion(event.target.value)}
                    onKeyDown={(event) => {
                      if (
                        event.key === "Enter" &&
                        (event.ctrlKey || event.metaKey) &&
                        !event.nativeEvent.isComposing
                      ) {
                        event.preventDefault();
                        void submitQuestion(question);
                      }
                    }}
                  />
                  <div className="project78-composer-controls">
                    <label>
                      <span>问答模型</span>
                      <select
                        aria-label="问答模型"
                        value={modelState.status === "ready" ? modelState.selectedRef : ""}
                        disabled={
                          modelState.status !== "ready" || modelState.items.length === 0 || asking
                        }
                        onChange={(event) => {
                          if (modelState.status === "ready") {
                            setModelState({ ...modelState, selectedRef: event.target.value });
                          }
                        }}
                      >
                        {modelState.status === "loading" && <option value="">正在加载模型…</option>}
                        {modelState.status === "error" && <option value="">模型加载失败</option>}
                        {modelState.status === "ready" && modelState.items.length === 0 && (
                          <option value="">暂无可用模型</option>
                        )}
                        {modelState.status === "ready" &&
                          modelState.items.map((model) => (
                            <option key={model.model_ref} value={model.model_ref}>
                              {model.display_name}
                            </option>
                          ))}
                      </select>
                    </label>
                    <span className="project78-keyboard-hint">Ctrl / ⌘ + Enter 提问</span>
                    <button
                      type="button"
                      className="project78-send"
                      aria-label={asking ? "提问中" : "提问"}
                      title={asking ? "提问中" : "提问"}
                      disabled={!canAsk || !question.trim() || asking}
                      onClick={() => void submitQuestion(question)}
                    >
                      <Send size={17} aria-hidden="true" />
                      {asking ? "提问中" : "提问"}
                    </button>
                  </div>
                </div>
              </div>
              <ResponsiveEvidencePanel>
                {conversation.status === "answer" ? (
                  conversation.result.citations.length === 0 && (
                    <p>本次回答没有可展示的引用资料。</p>
                  )
                ) : (
                  <p>提问后，可在这里对照回答引用的项目资料。</p>
                )}
                {conversation.status === "answer" && conversation.result.citations.length > 0 && (
                  <div className="project78-citations" aria-label="回答引用">
                    {conversation.result.citations.map((citation) => (
                      <div
                        className="project78-citation"
                        key={`${citation.citation_order}-${citation.asset_title}`}
                      >
                        <Link
                          to={`/knowledge/${encodeURIComponent(citation.asset_id)}`}
                          state={{
                            backTo: `/project/${encodeURIComponent(projectId)}?view=qa`,
                            backLabel: "返回项目问答",
                            source: "project",
                          }}
                        >
                          [{citation.citation_order}] {citation.asset_title}
                        </Link>
                        <small>{CITED_ZONE[citation.cited_zone] ?? "来源区域待确认"}</small>
                        {citation.is_pending_review && <em>内容待审核，请谨慎参考</em>}
                      </div>
                    ))}
                  </div>
                )}{" "}
              </ResponsiveEvidencePanel>
            </div>
          </section>
        )}
      </ProductPage>
    </ProjectModuleFrame>
  );
}

export default function ProjectOverviewPage() {
  const { id = "" } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { capabilities } = useAuth();
  const listRequest = useRef(0);
  const [listState, setListState] = useState<ListState>({ status: "loading" });

  // 新建项目模态框状态（仅治理角色可用）。
  const canCreate = capabilities.isGovernance;
  const [createOpen, setCreateOpen] = useState(false);
  const [projectSearch, setProjectSearch] = useState("");

  const loadProjects = useCallback(async () => {
    const request = ++listRequest.current;
    setListState({ status: "loading" });
    try {
      const response = await fetchProjects();
      if (request === listRequest.current) setListState({ status: "ready", items: response.items });
    } catch {
      if (request === listRequest.current) {
        setListState({ status: "error", message: safeErrorMessage() });
      }
    }
  }, []);

  useEffect(() => {
    void loadProjects();
    return () => {
      listRequest.current += 1;
    };
  }, [loadProjects]);

  const openCreateModal = useCallback(() => setCreateOpen(true), []);

  if (listState.status === "loading") {
    return (
      <ProductPage className="project78-page">
        <LoadingError loading loadingTitle="正在加载项目列表…" />
      </ProductPage>
    );
  }

  if (listState.status === "error") {
    return (
      <ProductPage className="project78-page">
        <LoadingError
          error={listState.message}
          errorTitle="项目列表加载失败"
          onRetry={() => void loadProjects()}
        />
      </ProductPage>
    );
  }

  const projects = listState.items;
  if (!id) {
    const visibleProjects = projects.filter((project) =>
      `${project.name} ${project.client_name ?? ""}`
        .toLocaleLowerCase()
        .includes(projectSearch.trim().toLocaleLowerCase()),
    );
    return (
      <ProductPage className="project-hub-page">
        <PageHeader
          title="项目空间"
          description="选择你参与的项目，继续处理资料、审核和问答。"
          actions={
            canCreate && (
              <button type="button" className="product-button is-primary" onClick={openCreateModal}>
                <Plus size={16} />
                新建项目
              </button>
            )
          }
        />
        <section className="project-hub-list" aria-label="我的项目">
          <header>
            <h3>
              我的项目 <span>{projects.length}</span>
            </h3>
            <input
              aria-label="搜索我的项目"
              placeholder="搜索项目或客户"
              value={projectSearch}
              onChange={(event) => setProjectSearch(event.target.value)}
            />
            <button
              type="button"
              className="product-button is-secondary"
              onClick={() => void loadProjects()}
            >
              <RefreshCw size={15} />
              刷新
            </button>
          </header>
          {visibleProjects.length ? (
            <ul>
              {visibleProjects.map((project) => (
                <li key={project.id}>
                  <span className="project-hub-icon">
                    <FolderKanban size={23} />
                  </span>
                  <div className="project-hub-info">
                    <Link
                      className="project-hub-title"
                      to={`/project/${encodeURIComponent(project.id)}`}
                    >
                      {project.name}
                    </Link>
                    <p>
                      {project.client_name || "未填写客户"}
                      <span>{PROJECT_ROLE[project.project_role] ?? "项目成员"}</span>
                    </p>
                  </div>
                  <StatusBadge
                    label={PROJECT_STATUS[project.status] ?? "状态待确认"}
                    tone={project.status === "active" ? "success" : "neutral"}
                  />
                  <Link
                    className="project-hub-open"
                    to={`/project/${encodeURIComponent(project.id)}`}
                    aria-label={`进入${project.name}`}
                  >
                    进入项目
                    <ArrowRight size={16} />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <div className="project-hub-empty">
              <FolderKanban size={30} />
              <h3>{projects.length ? "没有匹配的项目" : "尚未加入项目"}</h3>
              <p>{projects.length ? "换个关键词查找。" : "加入项目后，可在这里处理项目工作。"}</p>
              {projectSearch && (
                <button type="button" onClick={() => setProjectSearch("")}>
                  清除搜索
                </button>
              )}
            </div>
          )}
        </section>
        <aside className="project-hub-discovery">
          <div>
            <strong>查找其他项目的资料</strong>
            <p>可访问的项目摘要仍在知识库查看，摘要可见不代表加入该项目。</p>
          </div>
          <Link className="product-button is-secondary" to="/knowledge?scope=project">
            浏览项目库
            <ArrowRight size={16} />
          </Link>
        </aside>
        <CreateProjectModal
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onCreated={async (created) => {
            setCreateOpen(false);
            await loadProjects();
            navigate(`/project/${created.id}`);
          }}
        />
      </ProductPage>
    );
  }
  if (projects.length === 0 && !canCreate) {
    return (
      <ProductPage className="project78-page">
        <LoadingError empty emptyTitle="暂无可访问项目" emptyDesc="当前身份尚未加入有效项目。">
          <Link className="project78-state-link" to="/">
            返回今日工作台
          </Link>
        </LoadingError>
      </ProductPage>
    );
  }

  if (projects.length === 0 && canCreate) {
    return (
      <ProductPage className="project78-page">
        <LoadingError
          empty
          emptyTitle="暂无可访问项目"
          emptyDesc="当前身份尚未加入有效项目，可新建项目。"
        >
          <button
            type="button"
            className="project78-state-link product-button is-primary"
            onClick={() => void openCreateModal()}
          >
            新建项目
          </button>
          <Link className="project78-state-link" to="/">
            返回今日工作台
          </Link>
        </LoadingError>
        <CreateProjectModal
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          onCreated={async (created) => {
            setCreateOpen(false);
            await loadProjects();
            navigate(`/project/${created.id}`);
          }}
        />
      </ProductPage>
    );
  }

  const selectedProject = projects.find((project) => project.id === id);
  const switchProject = (projectId: string) => {
    if (projects.some((project) => project.id === projectId)) {
      navigate(
        `/project/${encodeURIComponent(projectId)}${searchParams.get("view") === "qa" ? "?view=qa" : ""}`,
      );
    }
  };

  if (!selectedProject) {
    return (
      <ProductPage className="project78-page">
        <div className="project78-unavailable product-state">
          <strong className="product-state-title">项目不可访问</strong>
          <p className="product-state-description">
            请选择当前身份可访问的项目，或返回今日工作台。
          </p>
          <ProjectPicker projects={projects} value="" onChange={switchProject} />
          <Link className="project78-state-link" to="/">
            返回今日工作台
          </Link>
        </div>
      </ProductPage>
    );
  }

  return (
    <>
      <ProjectWorkspace
        key={selectedProject.id}
        selectedProject={selectedProject}
        projects={projects}
        onSwitch={switchProject}
        canCreate={canCreate}
        onCreateClick={() => void openCreateModal()}
      />
      <CreateProjectModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={async (created) => {
          setCreateOpen(false);
          await loadProjects();
          navigate(`/project/${created.id}`);
        }}
      />
    </>
  );
}
