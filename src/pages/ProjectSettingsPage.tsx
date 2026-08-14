import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, Check, ClipboardCheck, RotateCcw, Save, Trash2, X } from "lucide-react";
import ConfirmDialog from "../components/ConfirmDialog";
import ActionFeedback from "../components/ActionFeedback";
import LoadingError from "../components/LoadingError";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/http";
import {
  addProjectMember,
  deleteProject,
  fetchCandidateMembers,
  fetchProjectDeletionReadiness,
  fetchProjectMembers,
  fetchProjectSettings,
  fetchProjects,
  patchProjectMember,
  removeProjectMember,
  updateProjectSettings,
} from "../api/project";
import type { CandidateMemberDTO } from "../api/project";
import { approveReview, fetchReviews, rejectReview } from "../api/review";
import type {
  ProjectDeletionReadinessDTO,
  ProjectMemberDTO,
  ProjectSettingsDTO,
} from "../types/projectSettings";
import type { ProjectListItemDTO } from "../types/project";
import type { ReviewItemDTO } from "../types/review";
import { formatBeijingTime } from "../utils/time";
import { bizStageOptions } from "./upload/uploadConstants";
import "./ProjectSettingsPage.css";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ROUTE_OPTIONS = ["route_A", "route_B", "route_C"];
const PROJECT_ROLE_OPTIONS = ["coach", "consultant"];
const PENDING_REVIEW_STATUSES = new Set(["pending_reviewer", "approval_failed"]);

const routeLabel: Record<string, string> = {
  route_A: "完整路线",
  route_B: "年度辅导循环",
  route_C: "专项诊断",
};
const projectRoleLabel: Record<string, string> = {
  project_manager: "项目经理",
  coach: "辅导老师",
  consultant: "顾问",
};
const projectStatusLabel: Record<string, string> = {
  active: "进行中",
  completed: "已完成",
  archived: "已归档",
  inactive: "已停用",
};
const memberStatusLabel: Record<string, string> = {
  active: "有效",
  inactive: "已停用",
};
const reviewTypeLabel: Record<string, string> = {
  material_to_asset: "资料资产化",
  personal_to_project: "个人知识升级",
  project_ingest_approval: "项目知识入库",
  lifecycle_change: "生命周期变更",
};

type SettingsDraft = {
  lifecycleRouteKey: string;
  lifecyclePhaseKey: string;
  forceReviewOnIngest: boolean;
  wecomGroupId: string | null;
};

const draftFromSettings = (settings: ProjectSettingsDTO): SettingsDraft => ({
  lifecycleRouteKey: settings.lifecycle_route_key ?? "",
  lifecyclePhaseKey: settings.lifecycle_phase_key ?? "",
  forceReviewOnIngest: settings.force_review_on_ingest,
  wecomGroupId: null,
});

const safeError = (error: unknown, fallback: string): string => {
  if (error instanceof ApiError && error.status === 403) {
    return error.deniedReason === "project_membership_required"
      ? "当前身份不是该项目成员"
      : "当前身份无权执行此操作";
  }
  if (error instanceof ApiError && error.status === 409) {
    return "项目状态已变化，请刷新后重试";
  }
  return fallback;
};

export default function ProjectSettingsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { authMe, reload: reloadAuth } = useAuth();
  const projectId = id && UUID_RE.test(id) ? id : null;
  const authProjectRole = authMe?.projects.find(
    (project) => project.projectId === projectId,
  )?.projectRole;

  const [settings, setSettings] = useState<ProjectSettingsDTO | null>(null);
  const [deletionReadiness, setDeletionReadiness] = useState<ProjectDeletionReadinessDTO | null>(
    null,
  );
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [members, setMembers] = useState<ProjectMemberDTO[]>([]);
  const [canManageMembers, setCanManageMembers] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState<string | null>(null);
  const [memberBusy, setMemberBusy] = useState<string | null>(null);
  const [removeTarget, setRemoveTarget] = useState<ProjectMemberDTO | null>(null);

  // 项目切换器（参考 ProjectOverviewPage / ProjectKnowledgePage 的 ProjectPicker）。
  const [switchProjects, setSwitchProjects] = useState<ProjectListItemDTO[]>([]);

  // 新增成员内联表单状态（仅项目经理可用）。
  const [addMemberOpen, setAddMemberOpen] = useState(false);
  const [allCandidates, setAllCandidates] = useState<CandidateMemberDTO[]>([]);
  const [addMemberCandidates, setAddMemberCandidates] = useState<CandidateMemberDTO[]>([]);
  const [addMemberUserId, setAddMemberUserId] = useState("");
  const [addMemberRole, setAddMemberRole] = useState("coach");
  const [addMemberQuery, setAddMemberQuery] = useState("");
  const [addMemberBusy, setAddMemberBusy] = useState(false);
  const [addMemberError, setAddMemberError] = useState<string | null>(null);

  // 危险操作区：删除项目。
  const [dangerBusy, setDangerBusy] = useState(false);
  const [deleteConfirmName, setDeleteConfirmName] = useState("");
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [dangerError, setDangerError] = useState<string | null>(null);
  const deleteInFlightRef = useRef(false);

  const [reviews, setReviews] = useState<ReviewItemDTO[]>([]);
  const [reviewsLoading, setReviewsLoading] = useState(false);
  const [reviewsError, setReviewsError] = useState<string | null>(null);
  const [reviewBusy, setReviewBusy] = useState<string | null>(null);
  const [rejectTarget, setRejectTarget] = useState<ReviewItemDTO | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectError, setRejectError] = useState<string | null>(null);
  const projectRequestRef = useRef(0);
  const reviewRequestRef = useRef(0);
  const invalidateRequests = useCallback(() => {
    ++projectRequestRef.current;
    ++reviewRequestRef.current;
  }, []);

  const loadReviews = useCallback(async (pid: string) => {
    const requestId = ++reviewRequestRef.current;
    setReviewsLoading(true);
    setReviewsError(null);
    try {
      const authorized = await fetchReviews();
      if (requestId !== reviewRequestRef.current) return;
      setReviews(
        authorized.filter(
          (review) =>
            review.target_project_id === pid &&
            PENDING_REVIEW_STATUSES.has(review.status) &&
            review.can_decide,
        ),
      );
    } catch (error) {
      if (requestId !== reviewRequestRef.current) return;
      setReviews([]);
      setReviewsError(safeError(error, "待确认任务暂时无法加载"));
    } finally {
      if (requestId === reviewRequestRef.current) setReviewsLoading(false);
    }
  }, []);

  const loadProject = useCallback(
    async (pid: string) => {
      const requestId = ++projectRequestRef.current;
      ++reviewRequestRef.current;
      setLoading(true);
      setPageError(null);
      setActionError(null);
      setActionNote(null);
      setReviews([]);
      setReviewsError(null);
      setReviewsLoading(false);
      setRejectTarget(null);
      setRejectReason("");
      setRejectError(null);
      try {
        const [nextSettings, memberResponse, nextDeletionReadiness] = await Promise.all([
          fetchProjectSettings(pid),
          fetchProjectMembers(pid),
          fetchProjectDeletionReadiness(pid),
        ]);
        if (requestId !== projectRequestRef.current) return;
        setSettings(nextSettings);
        setDeletionReadiness(nextDeletionReadiness);
        setDraft(draftFromSettings(nextSettings));
        setMembers(memberResponse.items);
        setCanManageMembers(memberResponse.can_manage);
        if (nextSettings.can_write) {
          setReviews([]);
          void loadReviews(pid);
        } else {
          setReviews([]);
          setReviewsError(null);
          setReviewsLoading(false);
        }
      } catch (error) {
        if (requestId !== projectRequestRef.current) return;
        setSettings(null);
        setDeletionReadiness(null);
        setDraft(null);
        setMembers([]);
        setPageError(safeError(error, "项目设置加载失败"));
      } finally {
        if (requestId === projectRequestRef.current) setLoading(false);
      }
    },
    [loadReviews],
  );

  useEffect(() => {
    if (!projectId) {
      invalidateRequests();
      setLoading(false);
      setPageError("当前地址没有有效的项目上下文");
      return;
    }
    void loadProject(projectId);
    return invalidateRequests;
  }, [invalidateRequests, loadProject, projectId]);

  // 顶部项目切换器：复用 /api/v1/projects 列表（与 ProjectOverviewPage 一致）。
  useEffect(() => {
    let cancelled = false;
    void fetchProjects()
      .then((response) => {
        if (!cancelled) setSwitchProjects(response.items);
      })
      .catch(() => {
        if (!cancelled) setSwitchProjects([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const switchToProject = (targetProjectId: string) => {
    if (targetProjectId && targetProjectId !== projectId) {
      navigate(`/project/${targetProjectId}/settings`);
    }
  };

  // 新增成员表单：加载候选用户（项目经理可读，无需治理角色）。
  const loadCandidateMembers = useCallback(async (pid: string) => {
    setAddMemberError(null);
    try {
      const response = await fetchCandidateMembers(pid);
      setAllCandidates(response.items);
      setAddMemberCandidates(response.items);
    } catch (e) {
      setAllCandidates([]);
      setAddMemberCandidates([]);
      setAddMemberError(
        e instanceof ApiError && e.status === 403
          ? "当前身份无权查看候选用户"
          : "用户列表加载失败，请稍后重试",
      );
    }
  }, []);

  const filterCandidates = useCallback(
    (query: string) => {
      const trimmed = query.trim().toLowerCase();
      if (!trimmed) {
        setAddMemberCandidates(allCandidates);
        return;
      }
      setAddMemberCandidates(
        allCandidates.filter(
          (c) => c.name.toLowerCase().includes(trimmed) || c.email.toLowerCase().includes(trimmed),
        ),
      );
    },
    [allCandidates],
  );

  const openAddMemberForm = () => {
    setAddMemberOpen(true);
    setAddMemberUserId("");
    setAddMemberRole("coach");
    setAddMemberQuery("");
    setAddMemberCandidates([]);
    setAddMemberError(null);
    if (projectId) void loadCandidateMembers(projectId);
  };

  const submitAddMember = async () => {
    if (!projectId || !addMemberUserId) {
      setAddMemberError("请选择要添加的用户");
      return;
    }
    setAddMemberBusy(true);
    setAddMemberError(null);
    try {
      const added = await addProjectMember(projectId, {
        user_id: addMemberUserId,
        project_role: addMemberRole,
        status: "active",
      });
      setMembers((current) => [...current, added]);
      setActionNote("项目成员已添加");
      setAddMemberOpen(false);
      setAddMemberUserId("");
      setAddMemberQuery("");
      setAddMemberCandidates([]);
      setAllCandidates([]);
    } catch (e) {
      setAddMemberError(safeError(e, "添加成员失败"));
    } finally {
      setAddMemberBusy(false);
    }
  };

  const handleRemoveMember = async (member: ProjectMemberDTO) => {
    if (!projectId || !canEditProjectRoles) return;
    // 保护：不能移除自己。
    if (authMe && member.user_id === authMe.userId) {
      setActionError("不能移除自己");
      return;
    }
    // 保护：不能移除项目经理（后端也会校验最后一个项目经理）。
    if (member.project_role === "project_manager") {
      setActionError("项目经理关系请由治理角色在人员权限页调整");
      return;
    }
    setRemoveTarget(member);
  };

  const confirmRemoveMember = async () => {
    const member = removeTarget;
    if (!member || !projectId) return;
    setMemberBusy(member.member_id);
    setActionError(null);
    setActionNote(null);
    try {
      await removeProjectMember(projectId, member.member_id);
      setMembers((current) => current.filter((item) => item.member_id !== member.member_id));
      setRemoveTarget(null);
      setActionNote("成员已移除");
    } catch (e) {
      setActionError(safeError(e, "移除成员失败"));
    } finally {
      setMemberBusy(null);
    }
  };

  const handleDelete = async () => {
    if (!projectId || !canDelete || !settings || deleteInFlightRef.current) return;
    if (deleteConfirmName.trim() !== settings.name) {
      setDangerError("输入的项目名称不匹配");
      return;
    }
    deleteInFlightRef.current = true;
    setDangerBusy(true);
    setDangerError(null);

    const exitDeletedProject = async () => {
      invalidateRequests();
      setDeleteDialogOpen(false);
      setDeleteConfirmName("");
      setDangerError(null);
      setDangerBusy(false);
      try {
        await reloadAuth();
      } catch {
        // 删除已经成为终态；身份刷新失败不能把成功删除误报为失败。
      }
      navigate("/", { replace: true });
    };

    try {
      await deleteProject(projectId);
      await exitDeletedProject();
    } catch (e) {
      const projectAlreadyGone =
        e instanceof ApiError && e.status === 404 && e.deniedReason === "project_not_found";
      if (projectAlreadyGone) {
        await exitDeletedProject();
      } else if (e instanceof ApiError && e.deniedReason === "project_has_assets") {
        setDangerError("项目中仍有资产，请先前往项目知识库清空资产后再删除。");
      } else {
        setDangerError(safeError(e, "删除失败，请刷新项目状态后重试"));
      }
      if (!projectAlreadyGone) {
        void fetchProjectDeletionReadiness(projectId)
          .then(setDeletionReadiness)
          .catch(() => undefined);
      }
    } finally {
      deleteInFlightRef.current = false;
      setDangerBusy(false);
    }
  };

  const canWrite = settings?.can_write ?? false;
  const canEditProjectRoles = canManageMembers && authProjectRole === "project_manager";
  const canDelete = deletionReadiness?.can_delete ?? false;
  const assetCount = deletionReadiness?.asset_count ?? 0;
  const memberCount = deletionReadiness?.member_count ?? members.length;
  const historicalPhase =
    settings?.lifecycle_phase_key && !bizStageOptions.includes(settings.lifecycle_phase_key)
      ? settings.lifecycle_phase_key
      : null;
  const routeOptions = useMemo(() => {
    const current = settings?.lifecycle_route_key;
    return current && !ROUTE_OPTIONS.includes(current)
      ? [current, ...ROUTE_OPTIONS]
      : ROUTE_OPTIONS;
  }, [settings?.lifecycle_route_key]);
  const dirty = Boolean(
    settings &&
    draft &&
    (draft.lifecycleRouteKey !== (settings.lifecycle_route_key ?? "") ||
      draft.lifecyclePhaseKey !== (settings.lifecycle_phase_key ?? "") ||
      draft.forceReviewOnIngest !== settings.force_review_on_ingest ||
      draft.wecomGroupId !== null),
  );

  const discardDraft = () => {
    if (!settings) return;
    setDraft(draftFromSettings(settings));
    setActionError(null);
    setActionNote("已恢复为最近一次保存的设置");
  };

  const saveDraft = async () => {
    if (!projectId || !settings || !draft || !canWrite || !dirty) return;
    const body: Record<string, unknown> = {};
    if (draft.lifecycleRouteKey !== (settings.lifecycle_route_key ?? "")) {
      body.lifecycle_route_key = draft.lifecycleRouteKey;
    }
    if (draft.lifecyclePhaseKey !== (settings.lifecycle_phase_key ?? "")) {
      body.lifecycle_phase_key = draft.lifecyclePhaseKey;
    }
    if (draft.forceReviewOnIngest !== settings.force_review_on_ingest) {
      body.force_review_on_ingest = draft.forceReviewOnIngest;
    }
    if (draft.wecomGroupId !== null) body.wecom_group_id = draft.wecomGroupId;

    setSaving(true);
    setActionError(null);
    setActionNote(null);
    try {
      const updated = await updateProjectSettings(projectId, body);
      setSettings(updated);
      setDraft(draftFromSettings(updated));
      setActionNote("项目设置已保存");
    } catch (error) {
      setActionError(safeError(error, "保存失败，未保存内容已保留"));
    } finally {
      setSaving(false);
    }
  };

  const changeMember = async (
    member: ProjectMemberDTO,
    body: { project_role?: string; status?: string },
  ) => {
    if (!projectId || !canEditProjectRoles || member.project_role === "project_manager") return;
    setMemberBusy(member.member_id);
    setActionError(null);
    setActionNote(null);
    try {
      const updated = await patchProjectMember(projectId, member.member_id, body);
      setMembers((current) =>
        current.map((item) => (item.member_id === updated.member_id ? updated : item)),
      );
      setActionNote("项目成员关系已更新");
    } catch (error) {
      setActionError(safeError(error, "成员更新失败"));
    } finally {
      setMemberBusy(null);
    }
  };

  const approveProjectReview = async (review: ReviewItemDTO) => {
    if (!projectId || !review.can_decide || review.target_project_id !== projectId) return;
    setReviewBusy(review.id);
    setReviewsError(null);
    try {
      await approveReview(review.id, "项目经理确认通过");
      await loadReviews(projectId);
    } catch (error) {
      setReviewsError(safeError(error, "确认操作失败，请重试"));
    } finally {
      setReviewBusy(null);
    }
  };

  const openRejectDialog = (review: ReviewItemDTO) => {
    if (!projectId || !review.can_decide || review.target_project_id !== projectId) return;
    setRejectTarget(review);
    setRejectReason("");
    setRejectError(null);
  };

  const submitReject = async () => {
    const reason = rejectReason.trim();
    if (!reason) {
      setRejectError("请填写驳回理由");
      return;
    }
    if (
      !projectId ||
      !rejectTarget ||
      !rejectTarget.can_decide ||
      rejectTarget.target_project_id !== projectId
    ) {
      setRejectError("当前任务已不可处理，请关闭后刷新");
      return;
    }

    const reviewId = rejectTarget.id;
    setReviewBusy(reviewId);
    setRejectError(null);
    try {
      await rejectReview(reviewId, reason);
      setRejectTarget(null);
      setRejectReason("");
      await loadReviews(projectId);
    } catch (error) {
      setRejectError(safeError(error, "驳回失败，请重试"));
    } finally {
      setReviewBusy(null);
    }
  };

  if (loading) {
    return (
      <ProductPage className="project-settings-page">
        <LoadingError loading loadingTitle="正在加载项目设置…" wrapperClassName="ps74-page-state" />
      </ProductPage>
    );
  }

  if (pageError || !settings || !draft || !projectId) {
    return (
      <ProductPage className="project-settings-page">
        <LoadingError
          error={pageError ?? "当前项目不可用"}
          errorTitle="无法加载项目设置"
          errorDescription={pageError ?? "当前项目不可用"}
          onRetry={projectId ? () => void loadProject(projectId) : undefined}
          wrapperClassName="ps74-page-state"
        />
      </ProductPage>
    );
  }

  return (
    <ProductPage className="project-settings-page">
      <PageHeader
        className="ps74-header"
        eyebrow="项目协作 · 项目设置"
        title={settings.name}
        description="管理项目入库策略、企微群绑定与项目成员关系。"
        scope={settings.name}
        status={
          <StatusBadge
            label={projectStatusLabel[settings.status] ?? "项目状态未知"}
            variant={`ps74-status is-${settings.status}`}
            tone={settings.status === "active" ? "success" : "neutral"}
          />
        }
        actions={
          <>
            <Link className="product-button is-secondary" to={`/project/${projectId}/knowledge`}>
              返回项目知识库
            </Link>
            {switchProjects.length > 1 && (
              <label className="ps74-project-switcher">
                <span>切换项目</span>
                <select value={projectId} onChange={(event) => switchToProject(event.target.value)}>
                  {switchProjects.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {canWrite && dirty && (
              <div className="ps74-header-actions" aria-label="未保存设置操作">
                <button
                  className="product-button is-secondary"
                  disabled={saving}
                  onClick={discardDraft}
                >
                  <RotateCcw size={16} aria-hidden="true" />
                  放弃未保存
                </button>
                <button
                  className="product-button is-primary"
                  disabled={saving}
                  onClick={() => void saveDraft()}
                >
                  <Save size={16} aria-hidden="true" />
                  {saving ? "保存中…" : "保存设置"}
                </button>
              </div>
            )}
          </>
        }
      />

      {actionError && (
        <ActionFeedback
          state="error"
          title="设置未保存"
          description={actionError}
          nextStep="检查输入后重试；当前编辑内容仍会保留。"
        />
      )}
      {actionNote && <ActionFeedback state="success" title="设置已更新" description={actionNote} />}
      {!canWrite && (
        <ActionFeedback
          state="info"
          title="当前为只读模式"
          description="当前身份可查看项目设置，修改仅由本项目经理完成。"
        />
      )}

      <div className="ps74-layout">
        <div className="ps74-main-column">
          <section className="ps74-section" aria-labelledby="project-basic-heading">
            <div className="ps74-section-header">
              <div>
                <h2 id="project-basic-heading">项目基本信息</h2>
                <p>以下信息来自项目治理记录，仅供查看。</p>
              </div>
            </div>
            <dl className="ps74-info-grid">
              <div>
                <dt>项目名称</dt>
                <dd>{settings.name}</dd>
              </div>
              <div>
                <dt>客户名称</dt>
                <dd>{settings.client_name ?? "未提供"}</dd>
              </div>
              <div>
                <dt>项目状态</dt>
                <dd>{projectStatusLabel[settings.status] ?? "状态未知"}</dd>
              </div>
              <div>
                <dt>辅导老师</dt>
                <dd>{settings.coach_name ?? "暂未设置"}</dd>
              </div>
              <div>
                <dt>最近更新</dt>
                <dd>{formatBeijingTime(settings.updated_at)}</dd>
              </div>
            </dl>
          </section>

          <section className="ps74-section" aria-labelledby="project-policy-heading">
            <div className="ps74-section-header">
              <div>
                <h2 id="project-policy-heading">项目入库策略与企微群绑定</h2>
                <p>设置只在统一保存成功后生效。</p>
              </div>
            </div>
            <div className="ps74-settings-grid">
              <label>
                <span>生命周期路线</span>
                <select
                  value={draft.lifecycleRouteKey}
                  disabled={!canWrite || saving}
                  onChange={(event) =>
                    setDraft((current) =>
                      current ? { ...current, lifecycleRouteKey: event.target.value } : current,
                    )
                  }
                >
                  {routeOptions.map((route) => (
                    <option key={route} value={route}>
                      {routeLabel[route] ?? route}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>当前阶段</span>
                <select
                  value={draft.lifecyclePhaseKey}
                  disabled={!canWrite || saving}
                  name="lifecycle-phase-key"
                  onChange={(event) =>
                    setDraft((current) =>
                      current ? { ...current, lifecyclePhaseKey: event.target.value } : current,
                    )
                  }
                >
                  <option value="">未设置</option>
                  {historicalPhase && (
                    <option value={historicalPhase}>历史阶段：{historicalPhase}</option>
                  )}
                  {bizStageOptions.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <label className="ps74-switch-row">
                <span>
                  <strong>入库必须审核</strong>
                  <small>开启后，项目入库任务统一进入项目经理确认。</small>
                </span>
                <input
                  type="checkbox"
                  checked={draft.forceReviewOnIngest}
                  disabled={!canWrite || saving}
                  onChange={(event) =>
                    setDraft((current) =>
                      current ? { ...current, forceReviewOnIngest: event.target.checked } : current,
                    )
                  }
                />
              </label>
              <div className="ps74-wecom-setting">
                <div className="ps74-wecom-status">
                  <span>企微群绑定</span>
                  <strong>
                    {settings.wecom_group_bound
                      ? `已绑定（${settings.wecom_group_label ?? "脱敏标签不可用"}）`
                      : "未绑定"}
                  </strong>
                </div>
                {canWrite && (
                  <div className="ps74-wecom-controls">
                    <label>
                      <span className="sr-only">新的企微群绑定标识</span>
                      <input
                        type="password"
                        autoComplete="new-password"
                        name="wecom-binding-token"
                        placeholder="输入新的企微群绑定标识"
                        value={draft.wecomGroupId ?? ""}
                        disabled={saving}
                        onChange={(event) =>
                          setDraft((current) =>
                            current ? { ...current, wecomGroupId: event.target.value } : current,
                          )
                        }
                      />
                    </label>
                    {settings.wecom_group_bound && (
                      <button
                        type="button"
                        className="product-button is-secondary is-small"
                        disabled={saving}
                        onClick={() =>
                          setDraft((current) =>
                            current ? { ...current, wecomGroupId: "" } : current,
                          )
                        }
                      >
                        解除绑定
                      </button>
                    )}
                  </div>
                )}
                <small>当前绑定仅展示后端提供的脱敏标签，新值不会在保存后回显。</small>
              </div>
            </div>
          </section>

          <section className="ps74-section" aria-labelledby="project-members-heading">
            <div className="ps74-section-header">
              <div>
                <h2 id="project-members-heading">项目成员与项目内角色</h2>
                <p>项目经理可维护本项目的辅导老师和顾问；项目经理身份在此不可调整。</p>
              </div>
            </div>
            <div className="ps74-table-wrap">
              <table className="ps74-members-table">
                <thead>
                  <tr>
                    <th>成员</th>
                    <th>项目内角色</th>
                    <th>成员状态</th>
                    <th>加入时间</th>
                    {canEditProjectRoles && <th className="ps74-member-actions-heading">操作</th>}
                  </tr>
                </thead>
                <tbody>
                  {members.map((member) => {
                    const editable =
                      canEditProjectRoles && member.project_role !== "project_manager";
                    const busy = memberBusy === member.member_id;
                    return (
                      <tr
                        key={member.member_id}
                        className={member.status !== "active" ? "is-muted" : ""}
                      >
                        <td className="ps74-member-name">{member.name}</td>
                        <td>
                          {editable ? (
                            <select
                              aria-label={`调整${member.name}的项目内角色`}
                              value={member.project_role}
                              disabled={busy}
                              onChange={(event) =>
                                void changeMember(member, { project_role: event.target.value })
                              }
                            >
                              {PROJECT_ROLE_OPTIONS.map((role) => (
                                <option key={role} value={role}>
                                  {projectRoleLabel[role]}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <span className={`ps74-role is-${member.project_role}`}>
                              {projectRoleLabel[member.project_role] ?? "项目成员"}
                            </span>
                          )}
                        </td>
                        <td>{memberStatusLabel[member.status] ?? "状态未知"}</td>
                        <td>{formatBeijingTime(member.joined_at)}</td>
                        {canEditProjectRoles && (
                          <td className="ps74-member-actions">
                            <div className="ps74-member-action-controls">
                              {editable ? (
                                <>
                                  <button
                                    className="product-button is-secondary is-small"
                                    disabled={busy}
                                    onClick={() =>
                                      void changeMember(member, {
                                        status: member.status === "active" ? "inactive" : "active",
                                      })
                                    }
                                  >
                                    {member.status === "active" ? "停用" : "启用"}
                                  </button>
                                  <button
                                    className="ps74-remove-btn"
                                    disabled={busy}
                                    onClick={() => void handleRemoveMember(member)}
                                  >
                                    移除
                                  </button>
                                </>
                              ) : (
                                <span className="ps74-locked-role">由治理角色任命</span>
                              )}
                            </div>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                  {members.length === 0 && (
                    <tr>
                      <td colSpan={canEditProjectRoles ? 5 : 4} className="ps74-table-empty">
                        当前项目暂无成员记录
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {canEditProjectRoles && (
              <div className="ps74-member-action-row">
                {!addMemberOpen ? (
                  <button
                    type="button"
                    className="product-button is-secondary is-small"
                    onClick={openAddMemberForm}
                  >
                    添加成员
                  </button>
                ) : (
                  <div className="ps74-add-member-form">
                    <div className="ps74-add-member-fields">
                      <label>
                        <span>搜索用户</span>
                        <input
                          type="text"
                          placeholder="输入姓名搜索"
                          value={addMemberQuery}
                          autoComplete="off"
                          onChange={(event) => {
                            setAddMemberQuery(event.target.value);
                            filterCandidates(event.target.value);
                          }}
                        />
                      </label>
                      <label>
                        <span>选择用户</span>
                        <select
                          value={addMemberUserId}
                          onChange={(event) => setAddMemberUserId(event.target.value)}
                        >
                          <option value="">请选择用户</option>
                          {addMemberCandidates.map((person) => (
                            <option key={person.user_id} value={person.user_id}>
                              {person.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        <span>项目内角色</span>
                        <select
                          value={addMemberRole}
                          onChange={(event) => setAddMemberRole(event.target.value)}
                        >
                          {PROJECT_ROLE_OPTIONS.map((role) => (
                            <option key={role} value={role}>
                              {projectRoleLabel[role]}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    {addMemberError && (
                      <div className="ps74-feedback is-error">{addMemberError}</div>
                    )}
                    <div className="ps74-add-member-actions">
                      <button
                        type="button"
                        className="product-button is-primary is-small"
                        disabled={addMemberBusy || !addMemberUserId}
                        onClick={() => void submitAddMember()}
                      >
                        {addMemberBusy ? "添加中…" : "确认添加"}
                      </button>
                      <button
                        type="button"
                        className="product-button is-secondary is-small"
                        disabled={addMemberBusy}
                        onClick={() => {
                          setAddMemberOpen(false);
                          setAddMemberError(null);
                        }}
                      >
                        取消
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>

        <aside className="ps74-review-column" aria-labelledby="pending-review-heading">
          <div className="ps74-review-header">
            <div>
              <h2 id="pending-review-heading">
                <ClipboardCheck size={18} aria-hidden="true" />
                待项目经理确认
              </h2>
              <p>仅显示当前项目中可由当前身份处理的记录。</p>
            </div>
            {canWrite && !reviewsLoading && <span>{reviews.length}</span>}
          </div>

          {!canWrite ? (
            <div className="ps74-review-state">
              <strong>当前身份无确认权限</strong>
              <p>待确认处理仅向本项目经理开放。</p>
            </div>
          ) : reviewsLoading ? (
            <div className="ps74-review-state" role="status">
              正在加载待确认任务…
            </div>
          ) : reviewsError ? (
            <div className="ps74-review-state is-error">
              <strong>待确认任务加载失败</strong>
              <p>{reviewsError}</p>
              <button
                className="product-button is-secondary is-small"
                onClick={() => void loadReviews(projectId)}
              >
                重试
              </button>
            </div>
          ) : reviews.length === 0 ? (
            <div className="ps74-review-state">
              <strong>暂无待确认任务</strong>
              <p>当前项目没有需要你处理的记录。</p>
            </div>
          ) : (
            <div className="ps74-review-list">
              {reviews.map((review) => {
                const busy = reviewBusy === review.id;
                return (
                  <article key={review.id} className="ps74-review-item">
                    <span className="ps74-review-type">
                      {reviewTypeLabel[review.review_type] ?? "项目知识确认"}
                    </span>
                    <h3>{review.asset_title ?? "待确认项目知识"}</h3>
                    <p>
                      {review.status === "approval_failed"
                        ? "上次入库失败，可重新确认"
                        : "等待项目经理确认"}
                      {review.created_at ? ` · ${formatBeijingTime(review.created_at)}` : ""}
                    </p>
                    <div className="ps74-review-actions">
                      <Link to="/review" className="product-button is-secondary is-small">
                        查看
                      </Link>
                      {review.can_decide && (
                        <>
                          <button
                            className="product-button is-primary is-small"
                            disabled={busy}
                            onClick={() => void approveProjectReview(review)}
                          >
                            <Check size={15} aria-hidden="true" />
                            通过
                          </button>
                          <button
                            className="product-button is-danger is-small"
                            disabled={busy}
                            onClick={() => openRejectDialog(review)}
                          >
                            <X size={15} aria-hidden="true" />
                            驳回
                          </button>
                        </>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </aside>
      </div>

      {canDelete && (
        <section className="ps74-section ps74-danger-zone" aria-labelledby="project-danger-heading">
          <div className="ps74-section-header">
            <div>
              <h2 id="project-danger-heading">删除项目</h2>
              <p>项目经理可删除没有知识资产的项目；此操作不可恢复。</p>
            </div>
          </div>
          {dangerError && !deleteDialogOpen && (
            <div className="ps74-feedback is-error">{dangerError}</div>
          )}
          {assetCount > 0 ? (
            <div className="ps74-delete-blocker" role="status">
              <AlertTriangle size={18} aria-hidden="true" />
              <div>
                <strong>仍有 {assetCount} 个项目知识资产</strong>
                <p>先清理项目知识资产后再删除，避免误删仍在使用的内容。</p>
              </div>
              <Link className="product-button is-secondary" to={`/project/${projectId}/knowledge`}>
                前往项目知识库
              </Link>
            </div>
          ) : (
            <div className="ps74-danger-actions">
              <button
                type="button"
                className="product-button is-danger"
                disabled={dangerBusy}
                aria-describedby="project-delete-readiness"
                onClick={() => {
                  setDeleteConfirmName("");
                  setDangerError(null);
                  setDeleteDialogOpen(true);
                }}
              >
                <Trash2 size={16} aria-hidden="true" />
                删除项目
              </button>
              <p id="project-delete-readiness" className="ps74-delete-readiness">
                删除将一并移除 {memberCount} 条项目成员关系。
              </p>
            </div>
          )}
        </section>
      )}
      <ConfirmDialog
        open={Boolean(removeTarget)}
        title={`确认移除成员“${removeTarget?.name ?? ""}”？`}
        description="此操作不可恢复；成员将从该项目移除，其已提交的项目知识不受影响。"
        confirmText="移除成员"
        busyText="移除中…"
        busy={memberBusy !== null}
        danger
        error={actionError}
        errorDescription={actionError}
        onConfirm={() => void confirmRemoveMember()}
        onCancel={() => setRemoveTarget(null)}
      />
      <ConfirmDialog
        open={deleteDialogOpen}
        title={`删除项目“${settings.name}”`}
        description={`此操作不可恢复，并会一并移除 ${memberCount} 条项目成员关系。服务端将在执行前再次校验资产数量和有效项目经理身份。`}
        confirmText="删除项目"
        busyText="删除中…"
        busy={dangerBusy}
        confirmDisabled={deleteConfirmName.trim() !== settings.name}
        danger
        error={dangerError}
        errorDescription={dangerError}
        onConfirm={() => void handleDelete()}
        onCancel={() => {
          setDeleteDialogOpen(false);
          setDeleteConfirmName("");
          setDangerError(null);
        }}
      >
        <label className="ps74-delete-confirm-field">
          <span>输入项目名称“{settings.name}”确认删除</span>
          <input
            type="text"
            value={deleteConfirmName}
            disabled={dangerBusy}
            onChange={(event) => setDeleteConfirmName(event.target.value)}
            autoComplete="off"
          />
        </label>
      </ConfirmDialog>
      <ConfirmDialog
        open={Boolean(rejectTarget)}
        title="驳回项目知识"
        description={
          rejectTarget?.asset_title
            ? `请说明“${rejectTarget.asset_title}”未通过的具体原因。`
            : "请说明该项目知识未通过的具体原因。"
        }
        confirmText="确认驳回"
        busyText="驳回中…"
        busy={Boolean(rejectTarget && reviewBusy === rejectTarget.id)}
        danger
        error={rejectError}
        errorDescription={rejectError}
        onConfirm={() => void submitReject()}
        onCancel={() => {
          setRejectTarget(null);
          setRejectReason("");
          setRejectError(null);
        }}
      >
        <div className="ps74-reject-field">
          <label htmlFor="project-review-reject-reason">驳回理由</label>
          <textarea
            id="project-review-reject-reason"
            aria-describedby="project-review-reject-hint"
            autoFocus
            rows={4}
            maxLength={500}
            value={rejectReason}
            disabled={Boolean(rejectTarget && reviewBusy === rejectTarget.id)}
            onChange={(event) => {
              setRejectReason(event.target.value);
              if (rejectError) setRejectError(null);
            }}
            placeholder="填写需要补充或修正的具体内容"
          />
          <small id="project-review-reject-hint">该理由将随审核记录保存，并反馈给提交人。</small>
        </div>
      </ConfirmDialog>
    </ProductPage>
  );
}
