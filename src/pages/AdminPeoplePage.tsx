import {
  BriefcaseBusiness,
  ChevronDown,
  ChevronUp,
  CircleCheck,
  CircleOff,
  Link2,
  RefreshCw,
  Search,
  ShieldCheck,
  UsersRound,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  patchProjectMembership,
  removeProjectMembership,
  setCompanyRole,
  setUserPassword,
  setUserStatus,
  upsertProjectMembership,
} from "../api/admin";
import { ApiError } from "../api/http";
import CollectionWorkspace from "../components/CollectionWorkspace";
import ConfirmDialog from "../components/ConfirmDialog";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import type { PersonDTO } from "../types/people";
import "./AdminPeoplePage.css";
import {
  AddMembershipForm,
  COMPANY_ROLE_OPTIONS,
  companyRoleLabel,
  fmtTime,
  projectRoleLabel,
  SetPasswordForm,
  statusCls,
  statusLabel,
  USER_STATUS_OPTIONS,
} from "./controllers/AdminPeople/model";
import { useAdminPeople } from "./controllers/AdminPeople/useAdminPeople";

export default function AdminPeoplePage() {
  const {
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
  } = useAdminPeople();

  return (
    <ProductPage className="people-page gp-page people89-page admin-control-page">
      <PageHeader title="人员权限" description="查找成员，核对角色、项目归属与可用状态。" />
      <div className="gp-governance-console">
        <main className="gp-main-workspace">
          <details className="pp-multi-role-card">
            <summary>查看权限边界</summary>
            公司角色和项目角色分别管理。项目知识访问以有效项目成员关系为准；系统管理员不因此获得业务原文权限。
            系统管理员也不进入人员治理。
          </details>

          <CollectionWorkspace
            label="人员筛选"
            filters={
              <section className="pp-section pp-filter-section">
                <div className="pp-toolbar">
                  <div className="pp-toolbar-filters">
                    <span className="pp-toolbar-label">
                      <Search size={14} />
                      人员筛选
                    </span>
                    <select
                      aria-label="公司角色筛选"
                      value={filterRole}
                      onChange={(e) => setFilterRole(e.target.value)}
                    >
                      <option value="">全部公司角色</option>
                      {COMPANY_ROLE_OPTIONS.map((r) => (
                        <option key={r} value={r}>
                          {companyRoleLabel[r]}
                        </option>
                      ))}
                    </select>
                    <select
                      aria-label="人员状态筛选"
                      value={filterStatus}
                      onChange={(e) => setFilterStatus(e.target.value)}
                    >
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
                    <span className="pp-toolbar-hint">支持按姓名查找</span>
                  </div>
                </div>
              </section>
            }
          >
            {detail && (
              <section
                className="pp-section pp-detail-section"
                ref={detailPanel}
                tabIndex={-1}
                onKeyDown={onDetailKeyDown}
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
                      disabled={Boolean(busyKey || pendingConfirm)}
                      onClick={closeDetail}
                    >
                      <X size={14} /> 关闭
                    </button>
                  </div>
                  <div className={`pp-active-identity ${canManageProjects ? "is-governance" : ""}`}>
                    <span>当前工作身份</span>
                    <strong>{activeIdentityLabel}</strong>
                    <small>
                      {canManageProjects
                        ? "可按治理规则管理项目经理"
                        : "如需治理人员，请在左下角身份菜单切换为总经理或咨询总监"}
                    </small>
                  </div>
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

                  <div className="pp-governance-tabs" role="group" aria-label="人员治理分区">
                    {(
                      [
                        ["account", "账号"],
                        ["roles", "公司角色"],
                        ["projects", "项目任命"],
                      ] as const
                    ).map(([key, label]) => (
                      <button
                        className="btn-small"
                        type="button"
                        aria-pressed={detailTab === key}
                        disabled={busyKey !== null}
                        key={key}
                        onClick={() => {
                          setDetailTab(key);
                          setActionError(null);
                          setActionNote(null);
                        }}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <section role="region" aria-label="账号" hidden={detailTab !== "account"}>
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
                            className={`btn-small ${detail.status === "active" ? "pp-remove-btn" : ""}`}
                            disabled={Boolean(busyKey)}
                            onClick={async () => {
                              if (
                                !(await confirmAsync(
                                  detail.status === "active"
                                    ? "确认停用该账号？"
                                    : "确认启用该账号？",
                                  { danger: detail.status === "active" },
                                ))
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
                            setBusyKey("password");
                            setActionError(null);
                            setActionNote(null);
                            try {
                              await setUserPassword(detail.user_id, password);
                              setActionNote("密码已设置 / 重置");
                              await refreshAfterWrite(detail.user_id);
                            } catch (e) {
                              setActionError(describeError(e, "设置密码失败"));
                            } finally {
                              setBusyKey(null);
                            }
                          }}
                        />
                      </>
                    ) : (
                      <p className="pp-no-project" style={{ marginTop: 14 }}>
                        当前身份不可修改该人员的账号状态或密码。
                      </p>
                    )}
                  </section>
                  <section role="region" aria-label="公司角色" hidden={detailTab !== "roles"}>
                    {/* 公司角色管理 */}
                    <h4 style={{ marginTop: 14 }}>公司角色</h4>
                    <div className="pp-project-role-list">
                      {COMPANY_ROLE_OPTIONS.map((role) => {
                        const current = detail.company_roles.find(
                          (item) => item.company_role === role,
                        );
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
                                disabled={Boolean(busyKey)}
                                onClick={async () => {
                                  if (
                                    !(await confirmAsync(
                                      `确认${currentStatus === "active" ? "停用" : "授予或恢复"}${companyRoleLabel[role]}角色？`,
                                    ))
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
                  </section>
                  <section role="region" aria-label="项目任命" hidden={detailTab !== "projects"}>
                    {/* 项目成员关系管理 */}
                    <h4 style={{ marginTop: 14 }}>项目成员关系</h4>
                    <p className="pp-toolbar-hint" style={{ marginBottom: 8 }}>
                      此处仅管理项目经理任命；项目内角色（辅导老师/顾问）请到项目设置页管理。
                    </p>
                    {membershipError && (
                      <div className="pp-membership-inline-error" role="alert">
                        <span>{membershipError.message}</span>
                        <Link to={`/project/${membershipError.projectId}/settings`}>
                          前往“{membershipError.projectName}”项目设置
                        </Link>
                      </div>
                    )}
                    <div className="pp-project-role-list">
                      {detail.project_memberships.length > 0 ? (
                        detail.project_memberships.map((m) => (
                          <div
                            key={m.membership_id}
                            className="pp-project-role-item"
                            style={{ display: "flex", gap: 8, alignItems: "center" }}
                          >
                            <span className="pp-pr-project">{m.project_name}</span>
                            <span>{projectRoleLabel[m.project_role] ?? "项目成员"}</span>
                            <span className={`pp-status-pill ${statusCls[m.status] ?? ""}`}>
                              {statusLabel[m.status] ?? "状态未知"}
                            </span>
                            {canManageProjectRole(m.project_role) && (
                              <>
                                <button
                                  type="button"
                                  className="btn-small"
                                  disabled={Boolean(busyKey)}
                                  onClick={async () => {
                                    if (
                                      !(await confirmAsync(
                                        m.status === "active"
                                          ? "确认停用该项目成员关系？"
                                          : "确认启用该项目成员关系？",
                                      ))
                                    )
                                      return;
                                    setBusyKey(`membership-${m.membership_id}`);
                                    setActionError(null);
                                    setActionNote(null);
                                    const next = m.status === "active" ? "inactive" : "active";
                                    try {
                                      await patchProjectMembership(
                                        detail.user_id,
                                        m.membership_id,
                                        {
                                          status: next,
                                        },
                                      );
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
                                <button
                                  type="button"
                                  className="btn-small pp-remove-btn"
                                  disabled={Boolean(busyKey)}
                                  onClick={async () => {
                                    if (
                                      !(await confirmAsync(
                                        `确认移除“${m.project_name}”的项目成员关系？此操作不可恢复。`,
                                        { danger: true },
                                      ))
                                    )
                                      return;
                                    setBusyKey(`membership-remove-${m.membership_id}`);
                                    setActionError(null);
                                    setActionNote(null);
                                    setMembershipError(null);
                                    try {
                                      await removeProjectMembership(
                                        detail.user_id,
                                        m.membership_id,
                                      );
                                      setActionNote("项目成员关系已移除");
                                      await refreshAfterWrite(detail.user_id);
                                    } catch (err) {
                                      if (
                                        err instanceof ApiError &&
                                        err.deniedReason === "last_project_manager_protected"
                                      ) {
                                        setMembershipError({
                                          message:
                                            "该项目仍然存在，且这是最后一位有效项目经理，不能单独移除。请先在项目设置中完成项目收尾。",
                                          projectId: m.project_id,
                                          projectName: m.project_name,
                                        });
                                      } else {
                                        setActionError(describeError(err, "移除成员关系失败"));
                                      }
                                    } finally {
                                      setBusyKey(null);
                                    }
                                  }}
                                >
                                  {busyKey === `membership-remove-${m.membership_id}`
                                    ? "移除中…"
                                    : "移除"}
                                </button>
                              </>
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
                          if (!(await confirmAsync("确认新增或更新该项目成员关系？"))) return;
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
                  </section>
                  <div className="pp-governance-feedback" aria-live="polite">
                    {actionError && (
                      <div
                        className="up-submit-notice"
                        role="status"
                        style={{ color: "var(--color-danger-fg, #b00)" }}
                      >
                        {actionError}
                      </div>
                    )}
                    {actionNote && (
                      <div
                        className="up-submit-notice"
                        role="status"
                        style={{ color: "var(--color-success-fg, #176)" }}
                      >
                        {actionNote}
                      </div>
                    )}
                  </div>
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
                  <table data-responsive-table className="pp-table">
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
                      {[...people]
                        .sort((left, right) => {
                          const issueScore = (person: PersonDTO) =>
                            Number(person.status !== "active") +
                            Number(!person.company_roles.some((role) => role.status === "active")) +
                            Number(
                              !person.project_memberships.some(
                                (membership) => membership.status === "active",
                              ),
                            );
                          return issueScore(right) - issueScore(left);
                        })
                        .map((u) => {
                          const activeCompanyRoles = u.company_roles.filter(
                            (role) => role.status === "active",
                          );
                          const activeMemberships = u.project_memberships.filter(
                            (membership) => membership.status === "active",
                          );
                          return (
                            <tr
                              key={u.user_id}
                              className={u.status === "inactive" ? "pp-row-disabled" : undefined}
                            >
                              <td data-label="姓名" className="pp-cell-name">
                                {u.name}
                              </td>
                              <td data-label="企微绑定">
                                <span
                                  className={`pp-field-mark ${u.wecom_bound ? "is-linked" : "is-muted"}`}
                                >
                                  <Link2 size={13} />
                                  {u.wecom_bound ? "已绑定" : "未绑定"}
                                </span>
                              </td>
                              <td data-label="公司角色" className="pp-cell-roles">
                                <span className="pp-role-tags">
                                  {(expandedRoles.has(u.user_id)
                                    ? activeCompanyRoles
                                    : activeCompanyRoles.slice(0, 2)
                                  ).map((c) => (
                                    <span key={c.role_id} className="pp-role-tag">
                                      <ShieldCheck size={12} />
                                      {companyRoleLabel[c.company_role] ?? "其他角色"}
                                    </span>
                                  ))}
                                  {activeCompanyRoles.length > 2 && (
                                    <button
                                      type="button"
                                      className="pp-expand-toggle"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        toggleRoleExpand(u.user_id);
                                      }}
                                    >
                                      {expandedRoles.has(u.user_id) ? (
                                        <>
                                          <ChevronUp size={12} /> 收起
                                        </>
                                      ) : (
                                        <>
                                          +{activeCompanyRoles.length - 2} 查看全部{" "}
                                          <ChevronDown size={12} />
                                        </>
                                      )}
                                    </button>
                                  )}
                                </span>
                              </td>
                              <td data-label="项目成员关系" className="pp-cell-projects">
                                {activeMemberships.length > 0 ? (
                                  <span className="pp-project-summary">
                                    {(expandedMemberships.has(u.user_id)
                                      ? activeMemberships
                                      : activeMemberships.slice(0, 2)
                                    ).map((m) => (
                                      <span key={m.membership_id} className="pp-project-role-item">
                                        <BriefcaseBusiness size={12} />
                                        <span className="pp-pr-project">{m.project_name}</span>
                                        <span className="pp-pr-role">
                                          {projectRoleLabel[m.project_role] ?? "项目成员"}
                                        </span>
                                      </span>
                                    ))}
                                    {activeMemberships.length > 2 && (
                                      <button
                                        type="button"
                                        className="pp-expand-toggle"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          toggleMembershipExpand(u.user_id);
                                        }}
                                      >
                                        {expandedMemberships.has(u.user_id) ? (
                                          <>
                                            <ChevronUp size={12} /> 收起
                                          </>
                                        ) : (
                                          <>
                                            +{activeMemberships.length - 2} 查看全部{" "}
                                            <ChevronDown size={12} />
                                          </>
                                        )}
                                      </button>
                                    )}
                                  </span>
                                ) : (
                                  <span className="pp-no-project">—</span>
                                )}
                              </td>
                              <td data-label="状态">
                                <span className={`pp-status-pill ${statusCls[u.status] ?? ""}`}>
                                  {u.status === "active" ? (
                                    <CircleCheck size={12} />
                                  ) : (
                                    <CircleOff size={12} />
                                  )}
                                  {statusLabel[u.status] ?? "状态未知"}
                                </span>
                              </td>
                              <td data-label="最近会话" className="pp-cell-time">
                                {fmtTime(u.recent_session_at)}
                              </td>
                              <td data-label="操作">
                                <button
                                  type="button"
                                  className="btn-small"
                                  disabled={detailLoadingId === u.user_id}
                                  onClick={(event) =>
                                    void openDetail(u.user_id, event.currentTarget)
                                  }
                                >
                                  {detailLoadingId === u.user_id ? "加载中…" : "查看 / 治理"}
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </CollectionWorkspace>
        </main>
      </div>
      <ConfirmDialog
        open={Boolean(pendingConfirm)}
        title={pendingConfirm?.title ?? ""}
        description={pendingConfirm?.description}
        confirmText="确认"
        danger={pendingConfirm?.danger}
        onConfirm={() => pendingConfirm?.onResolve(true)}
        onCancel={() => pendingConfirm?.onResolve(false)}
      />
    </ProductPage>
  );
}
