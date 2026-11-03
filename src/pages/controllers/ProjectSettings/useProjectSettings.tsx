import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../../../api/http";
import type { CandidateMemberDTO } from "../../../api/project";
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
} from "../../../api/project";
import { approveReview, fetchReviews, rejectReview } from "../../../api/review";
import { useAuth } from "../../../auth/AuthContext";
import type { ProjectListItemDTO } from "../../../types/project";
import type {
  ProjectDeletionReadinessDTO,
  ProjectMemberDTO,
  ProjectSettingsDTO,
} from "../../../types/projectSettings";
import type { ReviewItemDTO } from "../../../types/review";
import { reviewActionFeedback } from "../../../utils/reviewActionFeedback";
import { bizStageOptions } from "../.././upload/uploadConstants";
import {
  PENDING_REVIEW_STATUSES,
  ROUTE_OPTIONS,
  SettingsDraft,
  UUID_RE,
  draftFromSettings,
  safeError,
} from "./model";

export function useProjectSettings() {
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
      draft.projectCode !== (settings.project_code ?? "") ||
      draft.projectCodeActive !== (settings.project_code_active ?? false) ||
      draft.namingDefaultConfidentiality !== (settings.naming_default_confidentiality ?? "L2") ||
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
    if (draft.projectCode !== (settings.project_code ?? "")) {
      body.project_code = draft.projectCode.trim().toUpperCase();
    }
    if (draft.projectCodeActive !== (settings.project_code_active ?? false)) {
      body.project_code_active = draft.projectCodeActive;
    }
    if (draft.namingDefaultConfidentiality !== (settings.naming_default_confidentiality ?? "L2")) {
      body.naming_default_confidentiality = draft.namingDefaultConfidentiality;
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
      const result = await approveReview(review.id, "项目经理确认通过");
      await loadReviews(projectId);
      const outcome = reviewActionFeedback(result, "approve");
      if (outcome.tone === "error") setReviewsError(outcome.text);
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
      const result = await rejectReview(reviewId, reason);
      const outcome = reviewActionFeedback(result, "reject");
      if (outcome.tone === "error") {
        setRejectError(outcome.text);
        return;
      }
      setRejectTarget(null);
      setRejectReason("");
      await loadReviews(projectId);
    } catch (error) {
      setRejectError(safeError(error, "驳回失败，请重试"));
    } finally {
      setReviewBusy(null);
    }
  };
  return {
    loading,
    projectId,
    pageError,
    settings,
    draft,
    loadProject,
    switchProjects,
    switchToProject,
    actionError,
    actionNote,
    canWrite,
    saving,
    setDraft,
    routeOptions,
    historicalPhase,
    dirty,
    discardDraft,
    saveDraft,
    canEditProjectRoles,
    addMemberOpen,
    openAddMemberForm,
    members,
    memberBusy,
    changeMember,
    handleRemoveMember,
    addMemberQuery,
    setAddMemberQuery,
    filterCandidates,
    addMemberUserId,
    setAddMemberUserId,
    addMemberCandidates,
    addMemberRole,
    setAddMemberRole,
    addMemberError,
    addMemberBusy,
    submitAddMember,
    setAddMemberOpen,
    setAddMemberError,
    reviewsLoading,
    reviews,
    reviewsError,
    loadReviews,
    reviewBusy,
    approveProjectReview,
    openRejectDialog,
    canDelete,
    dangerError,
    deleteDialogOpen,
    assetCount,
    dangerBusy,
    setDeleteConfirmName,
    setDangerError,
    setDeleteDialogOpen,
    memberCount,
    removeTarget,
    confirmRemoveMember,
    setRemoveTarget,
    deleteConfirmName,
    handleDelete,
    rejectTarget,
    rejectError,
    submitReject,
    setRejectTarget,
    setRejectReason,
    setRejectError,
    rejectReason,
  };
}
export type ProjectSettingsController = ReturnType<typeof useProjectSettings>;
