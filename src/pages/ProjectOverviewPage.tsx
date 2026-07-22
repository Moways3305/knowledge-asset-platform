import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, Bot, CheckSquare, Plus, RefreshCw, Send, Settings, Upload } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  createProject,
  fetchProjectOverview,
  fetchProjectQaModelOptions,
  fetchProjects,
  projectQa,
} from "../api/project";
import { fetchPeople } from "../api/admin";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/http";
import LoadingError from "../components/LoadingError";
import { ProductPage } from "../components/ProductLayout";
import type { ProjectQaModelOptionDTO, ProjectQaResponseDTO } from "../types/agent";
import type {
  ProjectCreateResponseDTO,
  ProjectListItemDTO,
  ProjectOverviewDTO,
} from "../types/project";
import type { PersonDTO } from "../types/people";
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
  const overviewRequest = useRef(0);
  const modelRequest = useRef(0);
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
    void loadModels();
    return () => {
      overviewRequest.current += 1;
      modelRequest.current += 1;
      qaRequest.current += 1;
    };
  }, [loadModels, loadOverview]);

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

  if (overviewState.status === "loading") {
    return (
      <ProductPage className="project78-page">
        <LoadingError loading loadingTitle="正在加载项目空间…" />
      </ProductPage>
    );
  }

  if (overviewState.status === "error") {
    return (
      <ProductPage className="project78-page">
        <LoadingError
          error={overviewState.message}
          errorTitle="项目概览加载失败"
          onRetry={() => void loadOverview()}
        />
      </ProductPage>
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
    <ProductPage className="project78-page">
      <header className="project78-switchbar">
        <div>
          <span>项目协作空间</span>
          <strong>{selectedProject.name}</strong>
        </div>
        <div className="project78-switchbar-actions">
          {canCreate && onCreateClick && (
            <button type="button" className="project78-create-btn" onClick={onCreateClick}>
              <Plus size={14} aria-hidden="true" />
              新建项目
            </button>
          )}
          <ProjectPicker projects={projects} value={projectId} onChange={onSwitch} />
        </div>
      </header>

      <div className="project78-workspace">
        <aside className="project78-context" aria-label="项目上下文">
          <section className="project78-project-status">
            <span className="project78-section-label">项目状态</span>
            <h2>{overview.project.name}</h2>
            {overview.project.client_name && <p>{overview.project.client_name}</p>}
            <div className="project78-status-line">
              <span className="project78-status-badge">
                {PROJECT_STATUS[overview.project.status] ?? "状态待确认"}
              </span>
              <span>{PROJECT_ROLE[overview.project.project_role] ?? "项目成员"}</span>
            </div>
          </section>

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
              <dt>待确认</dt>
              <dd>{overview.counts.pending_confirmation_count}</dd>
            </div>
            <div>
              <dt>待审核</dt>
              <dd>{overview.counts.pending_review_count}</dd>
            </div>
            <div>
              <dt>原文申请</dt>
              <dd>{overview.counts.original_access_request_count}</dd>
            </div>
            <div>
              <dt>知识库</dt>
              <dd>
                {overview.knowledge_base.configured
                  ? (KB_STATUS[overview.knowledge_base.status ?? ""] ?? "状态待确认")
                  : "尚未配置"}
              </dd>
            </div>
          </dl>

          <nav className="project78-context-actions" aria-label="项目操作">
            {overview.capabilities.can_view_knowledge && (
              <Link to={`/project/${projectId}/knowledge`}>
                <BookOpen size={16} aria-hidden="true" />
                <span>项目知识库</span>
              </Link>
            )}
            {overview.capabilities.can_upload_material && (
              <Link to="/upload">
                <Upload size={16} aria-hidden="true" />
                <span>上传资料</span>
              </Link>
            )}
            {overview.capabilities.can_confirm_assets &&
              overview.counts.pending_review_count > 0 && (
                <Link to={`/project/${projectId}/settings`} className="is-review-action">
                  <CheckSquare size={16} aria-hidden="true" />
                  <span>处理待审核（{overview.counts.pending_review_count}）</span>
                </Link>
              )}
            {overview.capabilities.can_manage_members && (
              <Link to={`/project/${projectId}/settings`}>
                <Settings size={16} aria-hidden="true" />
                <span>项目设置</span>
              </Link>
            )}
          </nav>

          {overview.capabilities.can_manage_members && (
            <section className="project78-members" aria-labelledby="project78-members-title">
              <span className="project78-section-label">关键成员</span>
              <h3 id="project78-members-title">项目协作成员</h3>
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
            </section>
          )}
        </aside>

        <main className="project78-assistant" aria-labelledby="project78-assistant-title">
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
                  <button type="button" onClick={() => void submitQuestion(conversation.question)}>
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
                  <p>{conversation.result.response_text}</p>
                  {conversation.result.citations.length > 0 && (
                    <div className="project78-citations" aria-label="回答引用">
                      {conversation.result.citations.map((citation) => (
                        <div
                          className="project78-citation"
                          key={`${citation.citation_order}-${citation.asset_title}`}
                        >
                          <span>{citation.asset_title}</span>
                          <small>{CITED_ZONE[citation.cited_zone] ?? "来源区域待确认"}</small>
                          {citation.is_pending_review && <em>内容待审核，请谨慎参考</em>}
                        </div>
                      ))}
                    </div>
                  )}
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
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void submitQuestion(question);
                }
              }}
            />
            <div className="project78-composer-controls">
              <label>
                <span className="project78-sr-only">问答模型</span>
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
              <button
                type="button"
                className="project78-send"
                aria-label={asking ? "提问中" : "提问"}
                title={asking ? "提问中" : "提问"}
                disabled={!canAsk || !question.trim() || asking}
                onClick={() => void submitQuestion(question)}
              >
                <Send size={17} aria-hidden="true" />
              </button>
            </div>
          </div>
        </main>
      </div>
    </ProductPage>
  );
}

export default function ProjectOverviewPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { capabilities } = useAuth();
  const listRequest = useRef(0);
  const [listState, setListState] = useState<ListState>({ status: "loading" });

  // 新建项目模态框状态（仅治理角色可用）。
  const canCreate = capabilities.isGovernance;
  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createClient, setCreateClient] = useState("");
  const [createManagerId, setCreateManagerId] = useState("");
  const [createCandidates, setCreateCandidates] = useState<PersonDTO[]>([]);
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

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

  const openCreateModal = useCallback(async () => {
    setCreateOpen(true);
    setCreateName("");
    setCreateClient("");
    setCreateManagerId("");
    setCreateError(null);
    try {
      const response = await fetchPeople();
      setCreateCandidates(response.items);
    } catch (e) {
      setCreateCandidates([]);
      setCreateError(
        e instanceof ApiError && e.status === 403
          ? "当前身份无权加载用户列表"
          : "用户列表加载失败，请稍后重试",
      );
    }
  }, []);

  const submitCreateProject = useCallback(async () => {
    if (!createName.trim() || !createManagerId) {
      setCreateError("请填写项目名称并选择项目经理");
      return;
    }
    setCreateBusy(true);
    setCreateError(null);
    try {
      const created: ProjectCreateResponseDTO = await createProject({
        name: createName.trim(),
        client_name: createClient.trim() || null,
        project_manager_user_id: createManagerId,
      });
      setCreateOpen(false);
      await loadProjects();
      navigate(`/project/${created.id}`);
    } catch (e) {
      setCreateError(
        e instanceof ApiError && e.status === 403
          ? "当前身份无权创建项目"
          : "项目创建失败，请稍后重试",
      );
    } finally {
      setCreateBusy(false);
    }
  }, [createName, createClient, createManagerId, loadProjects, navigate]);

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
          name={createName}
          client={createClient}
          managerId={createManagerId}
          candidates={createCandidates}
          busy={createBusy}
          error={createError}
          onNameChange={setCreateName}
          onClientChange={setCreateClient}
          onManagerChange={setCreateManagerId}
          onSubmit={() => void submitCreateProject()}
          onClose={() => setCreateOpen(false)}
        />
      </ProductPage>
    );
  }

  const selectedProject = projects.find((project) => project.id === id);
  const switchProject = (projectId: string) => {
    if (projects.some((project) => project.id === projectId)) navigate(`/project/${projectId}`);
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
        name={createName}
        client={createClient}
        managerId={createManagerId}
        candidates={createCandidates}
        busy={createBusy}
        error={createError}
        onNameChange={setCreateName}
        onClientChange={setCreateClient}
        onManagerChange={setCreateManagerId}
        onSubmit={() => void submitCreateProject()}
        onClose={() => setCreateOpen(false)}
      />
    </>
  );
}

function CreateProjectModal({
  open,
  name,
  client,
  managerId,
  candidates,
  busy,
  error,
  onNameChange,
  onClientChange,
  onManagerChange,
  onSubmit,
  onClose,
}: {
  open: boolean;
  name: string;
  client: string;
  managerId: string;
  candidates: PersonDTO[];
  busy: boolean;
  error: string | null;
  onNameChange: (value: string) => void;
  onClientChange: (value: string) => void;
  onManagerChange: (value: string) => void;
  onSubmit: () => void;
  onClose: () => void;
}) {
  if (!open) return null;
  return (
    <div className="project78-modal-overlay" role="dialog" aria-modal="true" aria-label="新建项目">
      <div className="project78-modal">
        <div className="project78-modal-head">
          <h3>新建项目</h3>
          <button
            type="button"
            className="project78-modal-close"
            onClick={onClose}
            aria-label="关闭"
          >
            ×
          </button>
        </div>
        {error && <div className="project78-modal-error">{error}</div>}
        <div className="project78-modal-body">
          <label className="project78-modal-field">
            <span>项目名称</span>
            <input
              type="text"
              value={name}
              onChange={(e) => onNameChange(e.target.value)}
              placeholder="输入项目名称"
              autoComplete="off"
            />
          </label>
          <label className="project78-modal-field">
            <span>客户名称（可选）</span>
            <input
              type="text"
              value={client}
              onChange={(e) => onClientChange(e.target.value)}
              placeholder="输入客户名称"
              autoComplete="off"
            />
          </label>
          <label className="project78-modal-field">
            <span>项目经理</span>
            <select value={managerId} onChange={(e) => onManagerChange(e.target.value)}>
              <option value="">请选择项目经理</option>
              {candidates.map((person) => (
                <option key={person.user_id} value={person.user_id}>
                  {person.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="project78-modal-actions">
          <button
            type="button"
            className="product-button is-primary"
            disabled={busy || !name.trim() || !managerId}
            onClick={onSubmit}
          >
            {busy ? "创建中…" : "创建项目"}
          </button>
          <button
            type="button"
            className="product-button is-secondary"
            disabled={busy}
            onClick={onClose}
          >
            取消
          </button>
        </div>
      </div>
    </div>
  );
}
