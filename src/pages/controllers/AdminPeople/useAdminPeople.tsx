import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchPeople, fetchPerson } from "../../../api/admin";
import { ApiError } from "../../../api/http";
import { useAuth } from "../../../auth/AuthContext";
import { useDialogSurface } from "../../../components/useDialogSurface";
import type { PersonDTO } from "../../../types/people";
import { companyRoleLabel } from "./model";

export function useAdminPeople() {
  const { capabilities, authMe } = useAuth();
  const canManageProjects = capabilities.isGovernance;
  const canManageCompanyRole = (role: string) =>
    role === "consultant" || role === "consulting_director"
      ? canManageProjects
      : capabilities.isGovernance;
  const canManageProjectRole = (role: string) => canManageProjects && role === "project_manager";
  const [people, setPeople] = useState<PersonDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterRole, setFilterRole] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [q, setQ] = useState("");

  const [detailTab, setDetailTab] = useState<"account" | "roles" | "projects">("account");
  const [detail, setDetail] = useState<PersonDTO | null>(null);
  const [detailLoadingId, setDetailLoadingId] = useState<string | null>(null);
  const detailRequestVersion = useRef(0);
  const selectedUserIdRef = useRef<string | null>(null);
  const detailTriggerRef = useRef<HTMLElement | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState<string | null>(null);
  const [membershipError, setMembershipError] = useState<{
    message: string;
    projectId: string;
    projectName: string;
  } | null>(null);
  const [pendingConfirm, setPendingConfirm] = useState<{
    title: string;
    description?: string;
    danger?: boolean;
    onResolve: (confirmed: boolean) => void;
  } | null>(null);

  // 将原生 window.confirm 换成统一确认弹窗：弹窗确认/取消后 resolve，
  // 调用方继续原有的 async 流程，改动面最小。
  const confirmAsync = useCallback(
    (title: string, opts: { description?: string; danger?: boolean } = {}): Promise<boolean> =>
      new Promise((resolve) => {
        setPendingConfirm({
          title,
          description: opts.description,
          danger: opts.danger,
          onResolve: (confirmed) => {
            setPendingConfirm(null);
            resolve(confirmed);
          },
        });
      }),
    [],
  );

  // 项目成员关系列的展开/收起状态（按 user_id 索引）
  const [expandedMemberships, setExpandedMemberships] = useState<Set<string>>(new Set());
  const [expandedRoles, setExpandedRoles] = useState<Set<string>>(new Set());

  const describeError = (e: unknown, fallback: string) => {
    if (!(e instanceof ApiError)) return fallback;
    if (
      [
        "admin_business_permission_denied",
        "project_manager_removal_requires_governance",
        "last_project_manager_protected",
        "cannot_remove_self",
      ].includes(e.deniedReason ?? "")
    )
      return e.message;
    return e.status === 403 ? "当前身份没有执行此操作的权限。" : fallback;
  };
  const activeIdentityLabel = authMe?.activeCompanyRole
    ? (companyRoleLabel[authMe.activeCompanyRole] ??
      (authMe.activeCompanyRole === "admin" ? "管理员" : authMe.activeCompanyRole))
    : "未分配";

  const toggleMembershipExpand = useCallback((userId: string) => {
    setExpandedMemberships((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }, []);

  const toggleRoleExpand = useCallback((userId: string) => {
    setExpandedRoles((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }, []);

  const listRequest = useRef(0);
  const detailPanel = useRef<HTMLElement>(null);
  const load = useCallback(async () => {
    const request = ++listRequest.current;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPeople({ role: filterRole, status: filterStatus, q });
      if (request !== listRequest.current) return;
      setPeople(data.items);
      setTotal(data.total);
    } catch (e) {
      if (request !== listRequest.current) return;
      setTotal(0);
      setError(describeError(e, "人员列表暂时无法加载，请稍后重试"));
      setPeople([]);
    } finally {
      if (request === listRequest.current) setLoading(false);
    }
  }, [filterRole, filterStatus, q]);

  useEffect(() => {
    void load();
    return () => {
      listRequest.current += 1;
    };
    // 仅按 role/status 变化自动重载；q 由搜索按钮 / 回车触发。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterRole, filterStatus]);

  // 已知项目（project_id → name），从已拉取人员的成员关系聚合，供"新增成员关系"选择。
  const knownProjects = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of people) {
      for (const m of p.project_memberships) map.set(m.project_id, m.project_name);
    }
    return Array.from(map, ([id, name]) => ({ id, name }));
  }, [people]);

  const openDetail = useCallback(async (userId: string, trigger?: HTMLElement) => {
    setDetailTab("account");
    const requestVersion = ++detailRequestVersion.current;
    if (trigger) detailTriggerRef.current = trigger;
    selectedUserIdRef.current = userId;
    setDetail(null);
    setActionError(null);
    setActionNote(null);
    setMembershipError(null);
    setDetailLoadingId(userId);
    try {
      const person = await fetchPerson(userId);
      if (detailRequestVersion.current === requestVersion && selectedUserIdRef.current === userId)
        setDetail(person);
    } catch (e) {
      if (detailRequestVersion.current === requestVersion && selectedUserIdRef.current === userId)
        setActionError(describeError(e, "加载用户详情失败"));
    } finally {
      if (detailRequestVersion.current === requestVersion) setDetailLoadingId(null);
    }
  }, []);

  const closeDetail = useCallback(() => {
    if (busyKey || pendingConfirm) return;
    const trigger = detailTriggerRef.current;
    detailRequestVersion.current += 1;
    selectedUserIdRef.current = null;
    setDetailLoadingId(null);
    setDetail(null);
    setActionError(null);
    setActionNote(null);
    setMembershipError(null);
    detailTriggerRef.current = null;
    window.requestAnimationFrame(() => trigger?.focus());
  }, [busyKey, pendingConfirm]);
  const { onKeyDown: onDetailKeyDown } = useDialogSurface(
    Boolean(detail),
    detailPanel,
    closeDetail,
    Boolean(busyKey || pendingConfirm),
  );

  const refreshAfterWrite = useCallback(
    async (userId: string) => {
      if (selectedUserIdRef.current === userId) {
        const requestVersion = ++detailRequestVersion.current;
        try {
          const person = await fetchPerson(userId);
          if (
            detailRequestVersion.current === requestVersion &&
            selectedUserIdRef.current === userId
          )
            setDetail(person);
        } catch {
          /* 忽略：列表刷新足够 */
        }
      }
      void load();
    },
    [load],
  );
  return {
    filterRole,
    setFilterRole,
    filterStatus,
    setFilterStatus,
    q,
    setQ,
    load,
    loading,
    detail,
    detailPanel,
    onDetailKeyDown,
    busyKey,
    pendingConfirm,
    closeDetail,
    canManageProjects,
    activeIdentityLabel,
    detailTab,
    setDetailTab,
    setActionError,
    setActionNote,
    capabilities,
    confirmAsync,
    setBusyKey,
    refreshAfterWrite,
    describeError,
    canManageCompanyRole,
    membershipError,
    canManageProjectRole,
    setMembershipError,
    knownProjects,
    actionError,
    actionNote,
    total,
    error,
    people,
    expandedRoles,
    toggleRoleExpand,
    expandedMemberships,
    toggleMembershipExpand,
    detailLoadingId,
    openDetail,
  };
}
export type AdminPeopleController = ReturnType<typeof useAdminPeople>;
