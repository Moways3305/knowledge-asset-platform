import { useState, useMemo, useCallback, useEffect } from "react";
import {
  BriefcaseBusiness,
  CircleCheck,
  CircleOff,
  Link2,
  RefreshCw,
  Search,
  ShieldCheck,
  UserCheck,
  UsersRound,
  X,
} from "lucide-react";
import { useRef } from "react";
import { ApiError } from "../api/http";
import {
  fetchPeople,
  fetchPerson,
  setCompanyRole,
  setUserPassword,
  upsertProjectMembership,
  patchProjectMembership,
  setUserStatus,
  fetchCompanyKnowledgeBase,
  createCompanyKnowledgeBase,
} from "../api/admin";
import type { CompanyKnowledgeBaseDTO, PersonDTO } from "../types/people";
import { formatBeijingTime } from "../utils/time";
import { useAuth } from "../auth/AuthContext";
import { PageHeader, ProductPage } from "../components/ProductLayout";

const companyRoleLabel: Record<string, string> = {
  boss: "总经理",
  consulting_director: "咨询总监",
  consultant: "顾问",
};
const projectRoleLabel: Record<string, string> = {
  consultant: "顾问",
  project_manager: "项目经理",
  coach: "辅导老师",
};
const statusLabel: Record<string, string> = {
  active: "正常",
  inactive: "已停用",
};
const statusCls: Record<string, string> = {
  active: "pp-status-active",
  inactive: "pp-status-disabled",
};

const COMPANY_ROLE_OPTIONS = ["boss", "consulting_director", "consultant"];
const PROJECT_ROLE_OPTIONS = ["project_manager"];
const USER_STATUS_OPTIONS = ["active", "inactive"];

// 用户可见时间统一北京时间。
const fmtTime = (iso: string | null): string => formatBeijingTime(iso);

export default function AdminPeoplePage() {
  const { capabilities } = useAuth();
  const canManageProjects = capabilities.isBoss || capabilities.isConsultingDirector;
  const canManageCompanyRole = (role: string) =>
    role === "consultant" || role === "consulting_director"
      ? canManageProjects
      : capabilities.isBoss;
  const canManageProjectRole = (role: string) => canManageProjects && role === "project_manager";
  const [people, setPeople] = useState<PersonDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterRole, setFilterRole] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [q, setQ] = useState("");

  const [detail, setDetail] = useState<PersonDTO | null>(null);
  const [detailLoadingId, setDetailLoadingId] = useState<string | null>(null);
  const detailRequestVersion = useRef(0);
  const selectedUserIdRef = useRef<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState<string | null>(null);
  const [companyKb, setCompanyKb] = useState<CompanyKnowledgeBaseDTO | null>(null);
  const [companyKbBusy, setCompanyKbBusy] = useState(false);

  const describeError = (e: unknown, fallback: string) =>
    e instanceof ApiError && e.status === 403 ? "当前身份没有执行此操作的权限。" : fallback;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPeople({ role: filterRole, status: filterStatus, q });
      setPeople(data.items);
      setTotal(data.total);
    } catch (e) {
      setError(describeError(e, "人员列表暂时无法加载，请稍后重试"));
      setPeople([]);
    } finally {
      setLoading(false);
    }
  }, [filterRole, filterStatus, q]);

  useEffect(() => {
    void load();
    // 仅按 role/status 变化自动重载；q 由搜索按钮 / 回车触发。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterRole, filterStatus]);

  useEffect(() => {
    if (!canManageProjects) return;
    void fetchCompanyKnowledgeBase()
      .then(setCompanyKb)
      .catch((error: unknown) => {
        console.error("Failed to load company knowledge base:", error);
        setCompanyKb(null);
      });
  }, [canManageProjects]);

  // 已知项目（project_id → name），从已拉取人员的成员关系聚合，供"新增成员关系"选择。
  const knownProjects = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of people) {
      for (const m of p.project_memberships) map.set(m.project_id, m.project_name);
    }
    return Array.from(map, ([id, name]) => ({ id, name }));
  }, [people]);

  const openDetail = useCallback(async (userId: string) => {
    const requestVersion = ++detailRequestVersion.current;
    selectedUserIdRef.current = userId;
    setDetail(null);
    setActionError(null);
    setActionNote(null);
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
    detailRequestVersion.current += 1;
    selectedUserIdRef.current = null;
    setDetailLoadingId(null);
    setDetail(null);
    setActionError(null);
    setActionNote(null);
  }, []);

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

  const totalUsers = people.length;
  const activeUsers = people.filter((p) => p.status === "active").length;
  const withMembership = people.filter((p) =>
    p.project_memberships.some((m) => m.status === "active"),
  ).length;
  const wecomBound = people.filter((p) => p.wecom_bound).length;

  return (
    <ProductPage className="people-page gp-page people89-page">
      <PageHeader
        eyebrow="身份与权限治理"
        title="人员治理"
        description="管理人员账号状态、公司角色与项目成员关系。"
      />
      <div className="gp-governance-console">
        <aside className="gp-summary-panel" aria-label="人员摘要">
          <div className="gp-summary-heading">
            <span className="gp-summary-heading-icon">
              <UsersRound size={16} />
            </span>
            人员概览
          </div>
          <div className="gp-summary-list">
            <div className="gp-summary-item">
              <span className="gp-summary-copy">
                <span className="gp-summary-icon">
                  <UsersRound size={14} />
                </span>
                <span className="gp-summary-label">当前加载</span>
              </span>
              <strong className="gp-summary-value">{totalUsers}</strong>
            </div>
            <div className="gp-summary-item is-success">
              <span className="gp-summary-copy">
                <span className="gp-summary-icon">
                  <UserCheck size={14} />
                </span>
                <span className="gp-summary-label">正常账号</span>
              </span>
              <strong className="gp-summary-value">{activeUsers}</strong>
            </div>
            <div className="gp-summary-item is-linked">
              <span className="gp-summary-copy">
                <span className="gp-summary-icon">
                  <Link2 size={14} />
                </span>
                <span className="gp-summary-label">已绑定企微</span>
              </span>
              <strong className="gp-summary-value">{wecomBound}</strong>
            </div>
            <div className="gp-summary-item is-project">
              <span className="gp-summary-copy">
                <span className="gp-summary-icon">
                  <BriefcaseBusiness size={14} />
                </span>
                <span className="gp-summary-label">拥有项目关系</span>
              </span>
              <strong className="gp-summary-value">{withMembership}</strong>
            </div>
          </div>
        </aside>

        <main className="gp-main-workspace">
          <div className="pp-multi-role-card">
            公司角色和项目角色分别管理。项目知识访问以有效项目成员关系为准；系统管理员不因此获得业务原文权限。
            系统管理员也不进入人员治理。
          </div>

          <section className="pp-section pp-filter-section">
            <div className="pp-toolbar">
              <div className="pp-toolbar-filters">
                <span className="pp-toolbar-label">
                  <Search size={14} />
                  人员筛选
                </span>
                <select value={filterRole} onChange={(e) => setFilterRole(e.target.value)}>
                  <option value="">全部公司角色</option>
                  {COMPANY_ROLE_OPTIONS.map((r) => (
                    <option key={r} value={r}>
                      {companyRoleLabel[r]}
                    </option>
                  ))}
                </select>
                <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
                  <option value="">全部状态</option>
                  {USER_STATUS_OPTIONS.map((status) => (
                    <option key={status} value={status}>
                      {statusLabel[status]}
                    </option>
                  ))}
                </select>
                <input
                  className="up-edit-input"
                  aria-label="搜索姓名"
                  placeholder="搜索姓名"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void load();
                  }}
                />
                <button
                  type="button"
                  className="btn-small"
                  onClick={() => void load()}
                  disabled={loading}
                >
                  <RefreshCw size={13} /> {loading ? "加载中…" : "搜索 / 刷新"}
                </button>
              </div>
              <div className="pp-toolbar-actions">
                <span className="pp-toolbar-hint">共 {total} 人</span>
              </div>
            </div>
          </section>

          {detail && (
            <section
              className="pp-section pp-detail-section"
              role="dialog"
              aria-modal="true"
              aria-label="人员治理详情"
            >
              <div className="pp-detail-panel">
                <div className="pp-detail-head">
                  <span className="pp-detail-title">用户详情 · 治理</span>
                  <button
                    type="button"
                    className="btn-small"
                    aria-label="关闭人员详情"
                    onClick={closeDetail}
                  >
                    <X size={14} /> 关闭
                  </button>
                </div>
                {actionError && (
                  <div
                    className="up-submit-notice"
                    style={{ color: "var(--color-danger-fg, #b00)" }}
                  >
                    {actionError}
                  </div>
                )}
                {actionNote && (
                  <div
                    className="up-submit-notice"
                    style={{ color: "var(--color-success-fg, #176)" }}
                  >
                    {actionNote}
                  </div>
                )}
                <div className="pp-detail-grid">
                  <div className="pp-detail-item">
                    <span className="pp-detail-label">姓名</span>
                    <span className="pp-detail-value">{detail.name}</span>
                  </div>
                  <div className="pp-detail-item">
                    <span className="pp-detail-label">企微绑定</span>
                    <span className="pp-detail-value">
                      {detail.wecom_bound ? "已绑定" : "未绑定"}
                    </span>
                  </div>
                  <div className="pp-detail-item">
                    <span className="pp-detail-label">状态</span>
                    <span className="pp-detail-value">
                      <span className={`pp-status-pill ${statusCls[detail.status] ?? ""}`}>
                        {statusLabel[detail.status] ?? "状态未知"}
                      </span>
                    </span>
                  </div>
                  <div className="pp-detail-item">
                    <span className="pp-detail-label">最近会话</span>
                    <span className="pp-detail-value">{fmtTime(detail.recent_session_at)}</span>
                  </div>
                  <div className="pp-detail-item">
                    <span className="pp-detail-label">密码</span>
                    <span className="pp-detail-value">
                      {detail.password_set
                        ? `已设置（${fmtTime(detail.password_set_at)}）`
                        : "未设置"}
                    </span>
                  </div>
                  <div className="pp-detail-item">
                    <span className="pp-detail-label">活动会话</span>
                    <span className="pp-detail-value">{detail.active_session_count ?? 0} 个</span>
                  </div>
                </div>

                {/* 人员账号治理 */}
                {canManageProjects &&
                (capabilities.isBoss ||
                  !detail.company_roles.some(
                    (role) => role.company_role === "boss" && role.status === "active",
                  )) ? (
                  <>
                    <h4 style={{ marginTop: 14 }}>人员账号状态</h4>
                    <div
                      className="pp-actions-row"
                      style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
                    >
                      <button
                        type="button"
                        disabled={busyKey === "account-status"}
                        onClick={async () => {
                          if (
                            !window.confirm(
                              detail.status === "active" ? "确认停用该账号？" : "确认启用该账号？",
                            )
                          )
                            return;
                          setBusyKey("account-status");
                          setActionError(null);
                          setActionNote(null);
                          const next = detail.status === "active" ? "inactive" : "active";
                          try {
                            await setUserStatus(detail.user_id, next);
                            setActionNote(
                              next === "inactive" ? "已停用账号并撤销其会话" : "已启用账号",
                            );
                            await refreshAfterWrite(detail.user_id);
                          } catch (e) {
                            setActionError(describeError(e, "更新账号状态失败"));
                          } finally {
                            setBusyKey(null);
                          }
                        }}
                      >
                        {busyKey === "account-status"
                          ? "处理中…"
                          : detail.status === "active"
                            ? "停用账号"
                            : "启用账号"}
                      </button>
                    </div>

                    {/* 密码设置 / 重置 */}
                    <h4 style={{ marginTop: 14 }}>登录密码</h4>
                    <SetPasswordForm
                      onSubmit={async (password) => {
                        setActionError(null);
                        setActionNote(null);
                        try {
                          await setUserPassword(detail.user_id, password);
                          setActionNote("密码已设置 / 重置");
                          await refreshAfterWrite(detail.user_id);
                        } catch (e) {
                          setActionError(describeError(e, "设置密码失败"));
                        }
                      }}
                    />
                  </>
                ) : (
                  <p className="pp-no-project" style={{ marginTop: 14 }}>
                    当前身份不可修改该人员的账号状态或密码。
                  </p>
                )}

                {/* 公司角色管理 */}
                <h4 style={{ marginTop: 14 }}>公司角色</h4>
                <div className="pp-project-role-list">
                  {COMPANY_ROLE_OPTIONS.map((role) => {
                    const current = detail.company_roles.find((item) => item.company_role === role);
                    const currentStatus = current?.status ?? "unassigned";
                    const allowed = canManageCompanyRole(role);
                    const nextStatus = currentStatus === "active" ? "inactive" : "active";
                    return (
                      <div
                        key={role}
                        className="pp-project-role-item"
                        style={{ display: "flex", gap: 8, alignItems: "center" }}
                      >
                        <span className="pp-pr-project">{companyRoleLabel[role]}</span>
                        <span className={`pp-status-pill ${statusCls[currentStatus] ?? ""}`}>
                          {current ? statusLabel[currentStatus] : "未授予"}
                        </span>
                        {allowed ? (
                          <button
                            type="button"
                            className="btn-small"
                            disabled={busyKey === `company-${role}`}
                            onClick={async () => {
                              if (
                                !window.confirm(
                                  `确认${currentStatus === "active" ? "停用" : "授予或恢复"}${companyRoleLabel[role]}角色？`,
                                )
                              )
                                return;
                              setBusyKey(`company-${role}`);
                              setActionError(null);
                              setActionNote(null);
                              try {
                                await setCompanyRole(detail.user_id, {
                                  company_role: role,
                                  status: nextStatus,
                                });
                                setActionNote(
                                  nextStatus === "active"
                                    ? `${companyRoleLabel[role]}已恢复或授予`
                                    : `${companyRoleLabel[role]}已停用`,
                                );
                                await refreshAfterWrite(detail.user_id);
                              } catch (e) {
                                setActionError(describeError(e, "更新公司角色失败"));
                              } finally {
                                setBusyKey(null);
                              }
                            }}
                          >
                            {busyKey === `company-${role}`
                              ? "保存中…"
                              : currentStatus === "active"
                                ? "停用"
                                : current
                                  ? "恢复"
                                  : "授予"}
                          </button>
                        ) : (
                          <span className="pp-toolbar-hint">当前身份只读</span>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* 项目成员关系管理 */}
                <h4 style={{ marginTop: 14 }}>项目成员关系</h4>
                <div className="pp-project-role-list">
                  {detail.project_memberships.length > 0 ? (
                    detail.project_memberships.map((m) => (
                      <div
                        key={m.membership_id}
                        className="pp-project-role-item"
                        style={{ display: "flex", gap: 8, alignItems: "center" }}
                      >
                        <span className="pp-pr-project">{m.project_name}</span>
                        {canManageProjectRole(m.project_role) ? (
                          <select
                            className="up-edit-select"
                            disabled={busyKey === `membership-role-${m.membership_id}`}
                            value={m.project_role}
                            onChange={async (e) => {
                              if (!window.confirm("确认更新该项目角色？")) return;
                              setBusyKey(`membership-role-${m.membership_id}`);
                              setActionError(null);
                              setActionNote(null);
                              try {
                                await patchProjectMembership(detail.user_id, m.membership_id, {
                                  project_role: e.target.value,
                                });
                                setActionNote("项目角色已更新");
                                await refreshAfterWrite(detail.user_id);
                              } catch (err) {
                                setActionError(describeError(err, "更新项目角色失败"));
                              } finally {
                                setBusyKey(null);
                              }
                            }}
                          >
                            {PROJECT_ROLE_OPTIONS.map((r) => (
                              <option key={r} value={r}>
                                {projectRoleLabel[r]}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span>{projectRoleLabel[m.project_role] ?? "项目成员"}</span>
                        )}
                        <span className={`pp-status-pill ${statusCls[m.status] ?? ""}`}>
                          {statusLabel[m.status] ?? "状态未知"}
                        </span>
                        {canManageProjectRole(m.project_role) && (
                          <button
                            type="button"
                            className="btn-small"
                            disabled={busyKey === `membership-${m.membership_id}`}
                            onClick={async () => {
                              if (
                                !window.confirm(
                                  m.status === "active"
                                    ? "确认停用该项目成员关系？"
                                    : "确认启用该项目成员关系？",
                                )
                              )
                                return;
                              setBusyKey(`membership-${m.membership_id}`);
                              setActionError(null);
                              setActionNote(null);
                              const next = m.status === "active" ? "inactive" : "active";
                              try {
                                await patchProjectMembership(detail.user_id, m.membership_id, {
                                  status: next,
                                });
                                setActionNote("项目成员状态已更新");
                                await refreshAfterWrite(detail.user_id);
                              } catch (err) {
                                setActionError(describeError(err, "更新成员状态失败"));
                              } finally {
                                setBusyKey(null);
                              }
                            }}
                          >
                            {busyKey === `membership-${m.membership_id}`
                              ? "保存中…"
                              : m.status === "active"
                                ? "停用"
                                : "启用"}
                          </button>
                        )}
                      </div>
                    ))
                  ) : (
                    <span className="pp-no-project">未加入项目</span>
                  )}
                </div>
                {canManageProjects ? (
                  <AddMembershipForm
                    projects={knownProjects}
                    onSubmit={async (project_id, project_role) => {
                      if (!window.confirm("确认新增或更新该项目成员关系？")) return;
                      setBusyKey("membership-add");
                      setActionError(null);
                      setActionNote(null);
                      try {
                        await upsertProjectMembership(detail.user_id, {
                          project_id,
                          project_role,
                          status: "active",
                        });
                        setActionNote("项目成员关系已新增 / 更新");
                        await refreshAfterWrite(detail.user_id);
                      } catch (e) {
                        setActionError(describeError(e, "新增项目成员关系失败"));
                      } finally {
                        setBusyKey(null);
                      }
                    }}
                  />
                ) : (
                  <p className="pp-no-project">
                    总经理或咨询总监任命项目经理；项目经理在本项目内维护辅导老师与顾问。
                  </p>
                )}
              </div>
            </section>
          )}

          <section className="pp-section pp-list-section">
            <div className="gp-panel-heading">
              <span>
                <UsersRound size={17} />
                人员名册
              </span>
              <small>共 {total} 人</small>
            </div>
            {error ? (
              <div className="ig-empty-state">
                <div className="gp-empty-visual is-error" aria-hidden="true">
                  <UsersRound size={22} />
                  <span />
                </div>
                <div className="ig-empty-title">无法加载</div>
                <p className="ig-empty-desc">{error}</p>
                <button type="button" className="btn-small" onClick={() => void load()}>
                  重试
                </button>
              </div>
            ) : loading ? (
              <div className="ig-empty-state">
                <div className="ig-empty-title">加载中…</div>
              </div>
            ) : people.length === 0 ? (
              <div className="ig-empty-state">
                <div className="gp-empty-visual" aria-hidden="true">
                  <UsersRound size={22} />
                  <span />
                </div>
                <div className="ig-empty-title">无匹配用户</div>
                <p className="ig-empty-desc">尝试调整筛选条件。</p>
                <button type="button" className="btn-small" onClick={() => void load()}>
                  <RefreshCw size={13} />
                  重新加载
                </button>
              </div>
            ) : (
              <div className="pp-table-wrap">
                <table className="pp-table">
                  <thead>
                    <tr>
                      <th>姓名</th>
                      <th>企微绑定</th>
                      <th>公司角色</th>
                      <th>项目成员关系</th>
                      <th>状态</th>
                      <th>最近会话</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {people.map((u) => (
                      <tr
                        key={u.user_id}
                        className={u.status === "inactive" ? "pp-row-disabled" : ""}
                      >
                        <td className="pp-cell-name">{u.name}</td>
                        <td>
                          <span
                            className={`pp-field-mark ${u.wecom_bound ? "is-linked" : "is-muted"}`}
                          >
                            <Link2 size={13} />
                            {u.wecom_bound ? "已绑定" : "未绑定"}
                          </span>
                        </td>
                        <td>
                          <span className="pp-role-tags">
                            {u.company_roles
                              .filter((c) => c.status === "active")
                              .map((c) => (
                                <span key={c.role_id} className="pp-role-tag">
                                  <ShieldCheck size={12} />
                                  {companyRoleLabel[c.company_role] ?? "其他角色"}
                                </span>
                              ))}
                          </span>
                        </td>
                        <td className="pp-cell-projects">
                          {u.project_memberships.filter((m) => m.status === "active").length > 0 ? (
                            u.project_memberships
                              .filter((m) => m.status === "active")
                              .map((m) => (
                                <span key={m.membership_id} className="pp-project-role-item">
                                  <BriefcaseBusiness size={12} />
                                  <span className="pp-pr-project">{m.project_name}</span>
                                  <span className="pp-pr-role">
                                    {projectRoleLabel[m.project_role] ?? "项目成员"}
                                  </span>
                                </span>
                              ))
                          ) : (
                            <span className="pp-no-project">—</span>
                          )}
                        </td>
                        <td>
                          <span className={`pp-status-pill ${statusCls[u.status] ?? ""}`}>
                            {u.status === "active" ? (
                              <CircleCheck size={12} />
                            ) : (
                              <CircleOff size={12} />
                            )}
                            {statusLabel[u.status] ?? "状态未知"}
                          </span>
                        </td>
                        <td className="pp-cell-time">{fmtTime(u.recent_session_at)}</td>
                        <td>
                          <button
                            type="button"
                            className="btn-small"
                            disabled={detailLoadingId === u.user_id}
                            onClick={() => void openDetail(u.user_id)}
                          >
                            {detailLoadingId === u.user_id ? "加载中…" : "查看 / 治理"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {canManageProjects && (
            <section className="pp-section pp-support-section" aria-labelledby="company-kb-heading">
              <h3 id="company-kb-heading">公司知识库</h3>
              <p className="pp-toolbar-hint">
                {companyKb?.availability_summary ?? "正在读取公司知识库状态…"}
              </p>
              {companyKb?.exists && (
                <div className="pp-role-tags">
                  <span className="pp-role-tag">{companyKb.display_name ?? "公司知识库"}</span>
                  <span
                    className={`pp-status-pill ${companyKb.available ? statusCls.active : statusCls.inactive}`}
                  >
                    {companyKb.available ? "可用" : "暂不可用"}
                  </span>
                  <span className="pp-toolbar-hint">创建于 {fmtTime(companyKb.created_at)}</span>
                </div>
              )}
              {(!companyKb?.exists || !companyKb.available) && (
                <button
                  type="button"
                  className="btn-small btn-small-primary"
                  disabled={companyKbBusy}
                  onClick={async () => {
                    if (
                      !window.confirm(
                        companyKb?.exists ? "确认重试初始化公司知识库？" : "确认创建公司知识库？",
                      )
                    )
                      return;
                    setCompanyKbBusy(true);
                    setActionError(null);
                    try {
                      setCompanyKb(await createCompanyKnowledgeBase());
                      setActionNote("公司知识库状态已更新");
                    } catch (e) {
                      setActionError(describeError(e, "公司知识库创建失败"));
                    } finally {
                      setCompanyKbBusy(false);
                    }
                  }}
                >
                  {companyKbBusy ? "处理中…" : companyKb?.exists ? "重试初始化" : "创建公司知识库"}
                </button>
              )}
            </section>
          )}
        </main>
      </div>
    </ProductPage>
  );
}

// 设置 / 重置密码表单。密码 type=password、提交后立即清空、绝不回显。
function SetPasswordForm({ onSubmit }: { onSubmit: (password: string) => Promise<void> }) {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!pw || busy) return;
    if (!window.confirm("确认设置或重置该人员的登录密码？")) return;
    setBusy(true);
    try {
      await onSubmit(pw);
      setPw(""); // 保存后立即清空，不回显
    } finally {
      setBusy(false);
    }
  };
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
      <input
        className="up-edit-input"
        type="password"
        placeholder="新密码（至少 8 位）"
        value={pw}
        onChange={(e) => setPw(e.target.value)}
        autoComplete="new-password"
      />
      <button
        type="button"
        className="btn-small btn-small-primary"
        disabled={busy || !pw}
        onClick={() => void submit()}
      >
        {busy ? "设置中…" : "设置 / 重置密码"}
      </button>
    </div>
  );
}

function AddMembershipForm({
  projects,
  onSubmit,
}: {
  projects: { id: string; name: string }[];
  onSubmit: (projectId: string, role: string) => void;
}) {
  const [projectIndex, setProjectIndex] = useState(0);
  const [role, setRole] = useState("consultant");
  if (projects.length === 0) {
    return (
      <p className="pp-no-project" style={{ marginTop: 8 }}>
        暂无可选项目（项目列表来自当前已加载人员的成员关系）。
      </p>
    );
  }
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
      <select
        className="up-edit-select"
        aria-label="目标项目"
        value={projectIndex}
        onChange={(e) => setProjectIndex(Number(e.target.value))}
      >
        {projects.map((p, index) => (
          <option key={p.id} value={index}>
            {p.name}
          </option>
        ))}
      </select>
      <select className="up-edit-select" value={role} onChange={(e) => setRole(e.target.value)}>
        {PROJECT_ROLE_OPTIONS.map((r) => (
          <option key={r} value={r}>
            {projectRoleLabel[r]}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="btn-small btn-small-primary"
        onClick={() => projects[projectIndex] && onSubmit(projects[projectIndex].id, role)}
      >
        新增 / 更新成员关系
      </button>
    </div>
  );
}
