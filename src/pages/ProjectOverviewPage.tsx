import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpen, CheckSquare, Settings, Upload } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { fetchProjectOverview, fetchProjects } from "../api/project";
import LoadingError from "../components/LoadingError";
import { ProductPage } from "../components/ProductLayout";
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

const ASSET_TYPE: Record<string, string> = {
  methodology: "方法论",
  deliverable: "交付物",
  case: "案例",
  template: "模板",
  insight: "洞察",
};

const ZONE: Record<string, string> = {
  material: "资料",
  asset: "资产",
};

const KB_STATUS: Record<string, string> = {
  active: "已启用",
  initializing: "配置中",
  pending: "待配置",
  init_failed: "配置失败",
  disabled: "已停用",
};

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: ProjectListItemDTO[] };

type OverviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: ProjectOverviewDTO };

function safeErrorMessage(_error: unknown): string {
  return "暂时无法加载，请稍后重试";
}

function formatDate(value: string | null): string {
  if (!value) return "时间待补充";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间待补充";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
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

export default function ProjectOverviewPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const listRequest = useRef(0);
  const overviewRequest = useRef(0);
  const [listState, setListState] = useState<ListState>({ status: "loading" });
  const [overviewState, setOverviewState] = useState<OverviewState>({ status: "idle" });

  const loadProjects = useCallback(async () => {
    const request = ++listRequest.current;
    setListState({ status: "loading" });
    try {
      const response = await fetchProjects();
      if (request === listRequest.current) setListState({ status: "ready", items: response.items });
    } catch (error) {
      if (request === listRequest.current) {
        setListState({ status: "error", message: safeErrorMessage(error) });
      }
    }
  }, []);

  useEffect(() => {
    void loadProjects();
    return () => {
      listRequest.current += 1;
      overviewRequest.current += 1;
    };
  }, [loadProjects]);

  const projects = listState.status === "ready" ? listState.items : [];
  const selectedProject = projects.find((project) => project.id === id);

  const loadOverview = useCallback(async (projectId: string) => {
    const request = ++overviewRequest.current;
    setOverviewState({ status: "loading" });
    try {
      const response = await fetchProjectOverview(projectId);
      if (request === overviewRequest.current) {
        setOverviewState({ status: "ready", data: response });
      }
    } catch (error) {
      if (request === overviewRequest.current) {
        setOverviewState({ status: "error", message: safeErrorMessage(error) });
      }
    }
  }, []);

  useEffect(() => {
    overviewRequest.current += 1;
    setOverviewState({ status: "idle" });
    if (listState.status === "ready" && selectedProject) void loadOverview(selectedProject.id);
  }, [id, listState.status, selectedProject, loadOverview]);

  const switchProject = (projectId: string) => {
    if (projects.some((project) => project.id === projectId)) navigate(`/project/${projectId}`);
  };

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

  if (projects.length === 0) {
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

  const overview = overviewState.status === "ready" ? overviewState.data : null;
  const project = overview?.project ?? selectedProject;

  return (
    <ProductPage className="project78-page">
      <header className="project78-header">
        <div className="project78-heading">
          <span className="project78-eyebrow">项目空间</span>
          <h2>{project.name}</h2>
          {project.client_name && <p>{project.client_name}</p>}
          <div className="project78-tags" aria-label="项目状态">
            <span>{PROJECT_STATUS[project.status] ?? "状态待确认"}</span>
            <span>{PROJECT_ROLE[project.project_role] ?? "项目成员"}</span>
            {project.lifecycle_phase_key && <span>{project.lifecycle_phase_key}</span>}
          </div>
        </div>
        <ProjectPicker projects={projects} value={selectedProject.id} onChange={switchProject} />
      </header>

      {overviewState.status === "loading" && (
        <LoadingError loading loadingTitle="正在加载项目概览…" />
      )}
      {overviewState.status === "error" && (
        <LoadingError
          error={overviewState.message}
          errorTitle="项目概览加载失败"
          onRetry={() => void loadOverview(selectedProject.id)}
        />
      )}

      {overview && (
        <div className="project78-workspace">
          <main className="project78-main">
            <section className="project78-counts" aria-label="项目数据概览">
              {[
                ["项目资料", overview.counts.material_count],
                ["知识资产", overview.counts.asset_count],
                ["待确认", overview.counts.pending_confirmation_count],
                ["待升级审核", overview.counts.pending_review_count],
                ["原文访问申请", overview.counts.original_access_request_count],
              ].map(([label, value]) => (
                <div key={label} className="project78-count">
                  <strong>{value}</strong>
                  <span>{label}</span>
                </div>
              ))}
            </section>

            <section className="project78-kb" aria-labelledby="project78-kb-title">
              <div>
                <span className="project78-section-kicker">知识库</span>
                <h3 id="project78-kb-title">项目知识库状态</h3>
              </div>
              <strong>
                {overview.knowledge_base.configured
                  ? (KB_STATUS[overview.knowledge_base.status ?? ""] ?? "状态待确认")
                  : "尚未配置"}
              </strong>
            </section>

            <section className="project78-activity" aria-labelledby="project78-activity-title">
              <div className="project78-section-heading">
                <div>
                  <span className="project78-section-kicker">近期动态</span>
                  <h3 id="project78-activity-title">最近更新的知识</h3>
                </div>
              </div>
              {overview.recent_activity.length === 0 ? (
                <p className="project78-empty-copy">暂无近期知识动态。</p>
              ) : (
                <ul>
                  {overview.recent_activity.map((activity) => (
                    <li key={activity.asset_id}>
                      <Link to={`/knowledge/${activity.asset_id}`}>
                        <span className="project78-activity-copy">
                          <strong>{activity.title}</strong>
                          <span>
                            {ZONE[activity.zone] ?? "知识"} ·{" "}
                            {ASSET_TYPE[activity.asset_type] ?? "知识资产"} ·{" "}
                            {activity.confidentiality_level}
                          </span>
                        </span>
                        <span className="project78-activity-date">
                          {formatDate(activity.updated_at)}
                        </span>
                        <ArrowRight size={17} aria-hidden="true" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </main>

          <aside className="project78-side" aria-label="项目操作与成员">
            <section className="project78-actions">
              <span className="project78-section-kicker">快捷操作</span>
              <h3>继续处理项目工作</h3>
              <div className="project78-action-list">
                {overview.capabilities.can_upload_material && (
                  <Link to="/upload">
                    <Upload size={18} aria-hidden="true" />
                    <span>上传资料</span>
                    <ArrowRight size={16} aria-hidden="true" />
                  </Link>
                )}
                {overview.capabilities.can_view_knowledge && (
                  <Link to={`/project/${selectedProject.id}/knowledge`}>
                    <BookOpen size={18} aria-hidden="true" />
                    <span>项目知识库</span>
                    <ArrowRight size={16} aria-hidden="true" />
                  </Link>
                )}
                {overview.capabilities.can_confirm_assets &&
                  overview.counts.pending_confirmation_count > 0 && (
                    <Link to="/upload">
                      <CheckSquare size={18} aria-hidden="true" />
                      <span>处理待确认（{overview.counts.pending_confirmation_count}）</span>
                      <ArrowRight size={16} aria-hidden="true" />
                    </Link>
                  )}
                {overview.capabilities.can_manage_members && (
                  <Link to={`/project/${selectedProject.id}/settings`}>
                    <Settings size={18} aria-hidden="true" />
                    <span>项目设置</span>
                    <ArrowRight size={16} aria-hidden="true" />
                  </Link>
                )}
              </div>
            </section>

            {overview.capabilities.can_manage_members && (
              <section className="project78-members">
                <span className="project78-section-kicker">项目成员</span>
                <h3>当前协作成员</h3>
                {overview.members.length === 0 ? (
                  <p className="project78-empty-copy">暂无成员信息。</p>
                ) : (
                  <ul>
                    {overview.members.map((member) => (
                      <li key={member.user_id}>
                        <span>
                          <strong>{member.name}</strong>
                          <small>{PROJECT_ROLE[member.project_role] ?? "项目成员"}</small>
                        </span>
                        <em>{MEMBER_STATUS[member.status] ?? "状态待确认"}</em>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}
          </aside>
        </div>
      )}
    </ProductPage>
  );
}
