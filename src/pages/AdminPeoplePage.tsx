import { useState, useMemo, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  fetchPeople,
  fetchPerson,
  setCompanyRole,
  setUserPassword,
  upsertProjectMembership,
  patchProjectMembership,
  revokeUserSessions,
  setUserStatus,
  reconcileWecomIdentity,
} from "../api/client";
import type { PersonDTO } from "../types/people";
import { formatBeijingTime } from "../utils/time";

const companyRoleLabel: Record<string, string> = {
  boss: "Boss",
  consulting_director: "咨询总监",
  consultant: "顾问",
  admin: "管理员",
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

const COMPANY_ROLE_OPTIONS = ["boss", "consulting_director", "consultant", "admin"];
const PROJECT_ROLE_OPTIONS = ["consultant", "project_manager", "coach"];


// 用户可见时间统一北京时间。
const fmtTime = (iso: string | null): string => formatBeijingTime(iso);

export default function AdminPeoplePage() {
  const [people, setPeople] = useState<PersonDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterRole, setFilterRole] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [q, setQ] = useState("");

  const [detail, setDetail] = useState<PersonDTO | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState<string | null>(null);

  const describeError = (e: unknown, fallback: string) =>
    e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : fallback;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPeople({ role: filterRole, status: filterStatus, q });
      setPeople(data.items);
      setTotal(data.total);
    } catch (e) {
      setError(describeError(e, "加载人员列表失败（请确认后端已启动）"));
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

  // 已知项目（project_id → name），从已拉取人员的成员关系聚合，供"新增成员关系"选择。
  const knownProjects = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of people) {
      for (const m of p.project_memberships) map.set(m.project_id, m.project_name);
    }
    return Array.from(map, ([id, name]) => ({ id, name }));
  }, [people]);

  const openDetail = useCallback(async (userId: string) => {
    setActionError(null);
    setActionNote(null);
    try {
      setDetail(await fetchPerson(userId));
    } catch (e) {
      setActionError(describeError(e, "加载用户详情失败"));
    }
  }, []);

  const refreshAfterWrite = useCallback(async (userId: string) => {
    try {
      setDetail(await fetchPerson(userId));
    } catch { /* 忽略：列表刷新足够 */ }
    void load();
  }, [load]);

  const totalUsers = total;
  const withMembership = people.filter((p) => p.project_memberships.some((m) => m.status === "active")).length;
  const multiRole = people.filter(
    (p) => p.company_roles.filter((c) => c.status === "active").length > 1
  ).length;
  const wecomBound = people.filter((p) => p.wecom_bound).length;

  return (
    <div className="people-page">
      <div className="kl-header">
        <div className="kl-header-text">
          <h2>人员权限管理</h2>
          <p>展示用户、公司角色、项目成员关系与权限边界（真实后端 API）。企微 OAuth 已接入，绑定状态来自后端；公司角色与项目角色分离，admin 不因系统身份获得业务原文权。</p>
        </div>
        <div className="kl-kpis">
          <div className="kl-kpi"><div className="kl-kpi-value">{totalUsers}</div><div className="kl-kpi-label">总用户数</div></div>
          <div className="kl-kpi"><div className="kl-kpi-value">{withMembership}</div><div className="kl-kpi-label">有项目成员关系</div></div>
          <div className="kl-kpi"><div className="kl-kpi-value kl-kpi-warning">{multiRole}</div><div className="kl-kpi-label">多公司角色</div></div>
          <div className="kl-kpi"><div className="kl-kpi-value">{wecomBound}</div><div className="kl-kpi-label">已绑定企微</div></div>
        </div>
      </div>

      <div className="pp-multi-role-card">
        <strong>公司角色与项目角色分离</strong> — 公司角色（Boss / 咨询总监 / 顾问 / 管理员）来自 <code>user_company_roles</code>；项目内角色（coach / project_manager / consultant）来自 <code>project_members</code>。同一人可在不同项目担任不同项目角色。<strong>项目知识库权限只来自 active 项目成员关系</strong>；公司角色（含 Boss / 咨询总监）不自动授予项目权限；admin 是系统身份，不等于业务原文访问权。
      </div>


      <section className="pp-section">
        <div className="pp-toolbar">
          <div className="pp-toolbar-filters">
            <span className="pp-toolbar-label">用户筛选</span>
            <select value={filterRole} onChange={(e) => setFilterRole(e.target.value)}>
              <option value="">全部公司角色</option>
              {COMPANY_ROLE_OPTIONS.map((r) => <option key={r} value={r}>{companyRoleLabel[r]}</option>)}
            </select>
            <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
              <option value="">全部状态</option>
              <option value="active">正常</option>
              <option value="inactive">已停用</option>
            </select>
            <input
              className="up-edit-input"
              placeholder="搜索姓名 / 邮箱"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void load(); }}
            />
            <button className="btn-small" onClick={() => void load()} disabled={loading}>
              {loading ? "加载中…" : "搜索 / 刷新"}
            </button>
          </div>
          <div className="pp-toolbar-actions">
            <span className="pp-toolbar-hint">共 {total} 人</span>
          </div>
        </div>
      </section>

      {detail && (
        <section className="pp-section">
          <div className="pp-detail-panel">
            <div className="pp-detail-head">
              <span className="pp-detail-title">用户详情 · 治理</span>
              <button className="btn-small" onClick={() => setDetail(null)}>关闭</button>
            </div>
            {actionError && <div className="up-submit-notice" style={{ color: "var(--color-danger-fg, #b00)" }}>{actionError}</div>}
            {actionNote && <div className="up-submit-notice" style={{ color: "var(--color-success-fg, #176)" }}>{actionNote}</div>}
            <div className="pp-detail-grid">
              <div className="pp-detail-item"><span className="pp-detail-label">姓名</span><span className="pp-detail-value">{detail.name}</span></div>
              <div className="pp-detail-item"><span className="pp-detail-label">邮箱</span><span className="pp-detail-value">{detail.email}</span></div>
              <div className="pp-detail-item"><span className="pp-detail-label">企微绑定</span><span className="pp-detail-value">{detail.wecom_bound ? "已绑定" : "未绑定"}</span></div>
              <div className="pp-detail-item"><span className="pp-detail-label">状态</span><span className="pp-detail-value"><span className={`pp-status-pill ${statusCls[detail.status] ?? ""}`}>{statusLabel[detail.status] ?? detail.status}</span></span></div>
              <div className="pp-detail-item"><span className="pp-detail-label">最近会话</span><span className="pp-detail-value">{fmtTime(detail.recent_session_at)}</span></div>
              <div className="pp-detail-item"><span className="pp-detail-label">密码</span><span className="pp-detail-value">{detail.password_set ? `已设置（${fmtTime(detail.password_set_at)}）` : "未设置"}</span></div>
              <div className="pp-detail-item"><span className="pp-detail-label">活动会话</span><span className="pp-detail-value">{detail.active_session_count ?? 0} 个</span></div>
            </div>

            {/* 登录会话与账号安全 */}
            <h4 style={{ marginTop: 14 }}>登录会话与账号安全（仅系统管理员）</h4>
            <div className="pp-actions-row" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                disabled={(detail.active_session_count ?? 0) === 0}
                onClick={async () => {
                  setActionError(null); setActionNote(null);
                  try {
                    const r = await revokeUserSessions(detail.user_id, { reason: "admin force offline" });
                    setActionNote(`已撤销 ${r.revoked_count} 个平台会话`);
                    await refreshAfterWrite(detail.user_id);
                  } catch (e) {
                    setActionError(describeError(e, "撤销会话失败"));
                  }
                }}
              >
                撤销全部会话
              </button>
              <button
                onClick={async () => {
                  setActionError(null); setActionNote(null);
                  const next = detail.status === "active" ? "inactive" : "active";
                  try {
                    await setUserStatus(detail.user_id, next);
                    setActionNote(next === "inactive" ? "已停用账号并撤销其会话" : "已启用账号");
                    await refreshAfterWrite(detail.user_id);
                  } catch (e) {
                    setActionError(describeError(e, "更新账号状态失败"));
                  }
                }}
              >
                {detail.status === "active" ? "停用账号" : "启用账号"}
              </button>
              {detail.wecom_bound && (
                <button
                  onClick={async () => {
                    setActionError(null); setActionNote(null);
                    try {
                      const r = await reconcileWecomIdentity({ user_id: detail.user_id });
                      setActionNote(
                        r.deactivated > 0
                          ? `企微对账：成员失效，已停用并撤销 ${r.items[0]?.sessions_revoked ?? 0} 个会话`
                          : r.failed > 0
                            ? "企微对账：状态核验失败，请稍后重试"
                            : "企微对账：成员仍有效"
                      );
                      await refreshAfterWrite(detail.user_id);
                    } catch (e) {
                      setActionError(describeError(e, "企微身份对账失败"));
                    }
                  }}
                >
                  企微身份对账
                </button>
              )}
            </div>

            {/* 密码设置 / 重置 */}
            <h4 style={{ marginTop: 14 }}>登录密码（仅系统管理员）</h4>
            <SetPasswordForm
              onSubmit={async (password) => {
                setActionError(null); setActionNote(null);
                try {
                  await setUserPassword(detail.user_id, password);
                  setActionNote("密码已设置 / 重置");
                  await refreshAfterWrite(detail.user_id);
                } catch (e) {
                  setActionError(describeError(e, "设置密码失败"));
                }
              }}
            />

            {/* 公司角色管理 */}
            <h4 style={{ marginTop: 14 }}>公司角色</h4>
            <div className="pp-role-tags">
              {detail.company_roles.length > 0 ? detail.company_roles.map((c) => (
                <span key={c.role_id} className="pp-role-tag">
                  {companyRoleLabel[c.company_role] ?? c.company_role}（{statusLabel[c.status] ?? c.status}）
                </span>
              )) : <span className="pp-no-project">—</span>}
            </div>
            <CompanyRoleForm
              onSubmit={async (company_role, status) => {
                setActionError(null); setActionNote(null);
                try {
                  await setCompanyRole(detail.user_id, { company_role, status });
                  setActionNote("公司角色已更新");
                  await refreshAfterWrite(detail.user_id);
                } catch (e) {
                  setActionError(describeError(e, "更新公司角色失败"));
                }
              }}
            />

            {/* 项目成员关系管理 */}
            <h4 style={{ marginTop: 14 }}>项目成员关系</h4>
            <div className="pp-project-role-list">
              {detail.project_memberships.length > 0 ? detail.project_memberships.map((m) => (
                <div key={m.membership_id} className="pp-project-role-item" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span className="pp-pr-project">{m.project_name}</span>
                  <select
                    className="up-edit-select"
                    value={m.project_role}
                    onChange={async (e) => {
                      setActionError(null); setActionNote(null);
                      try {
                        await patchProjectMembership(detail.user_id, m.membership_id, { project_role: e.target.value });
                        setActionNote("项目角色已更新");
                        await refreshAfterWrite(detail.user_id);
                      } catch (err) { setActionError(describeError(err, "更新项目角色失败")); }
                    }}
                  >
                    {PROJECT_ROLE_OPTIONS.map((r) => <option key={r} value={r}>{projectRoleLabel[r]}</option>)}
                  </select>
                  <span className={`pp-status-pill ${statusCls[m.status] ?? ""}`}>{statusLabel[m.status] ?? m.status}</span>
                  <button
                    className="btn-small"
                    onClick={async () => {
                      setActionError(null); setActionNote(null);
                      const next = m.status === "active" ? "inactive" : "active";
                      try {
                        await patchProjectMembership(detail.user_id, m.membership_id, { status: next });
                        setActionNote("项目成员状态已更新");
                        await refreshAfterWrite(detail.user_id);
                      } catch (err) { setActionError(describeError(err, "更新成员状态失败")); }
                    }}
                  >
                    {m.status === "active" ? "停用" : "启用"}
                  </button>
                </div>
              )) : <span className="pp-no-project">未加入项目</span>}
            </div>
            <AddMembershipForm
              projects={knownProjects}
              onSubmit={async (project_id, project_role) => {
                setActionError(null); setActionNote(null);
                try {
                  await upsertProjectMembership(detail.user_id, { project_id, project_role, status: "active" });
                  setActionNote("项目成员关系已新增 / 更新");
                  await refreshAfterWrite(detail.user_id);
                } catch (e) { setActionError(describeError(e, "新增项目成员关系失败")); }
              }}
            />
          </div>
        </section>
      )}

      <section className="pp-section">
        <h3>用户列表</h3>
        {error ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">无法加载</div>
            <p className="ig-empty-desc">{error}</p>
            <p className="ig-empty-desc">人员治理查看仅对 admin / Boss / 咨询总监开放；可经 <code>VITE_DEV_USER_ID</code> 切换授权身份。</p>
            <button className="btn-small" onClick={() => void load()}>重试</button>
          </div>
        ) : loading ? (
          <div className="ig-empty-state"><div className="ig-empty-title">加载中…</div></div>
        ) : people.length === 0 ? (
          <div className="ig-empty-state"><div className="ig-empty-title">无匹配用户</div><p className="ig-empty-desc">尝试调整筛选条件。</p></div>
        ) : (
          <div className="pp-table-wrap">
            <table className="pp-table">
              <thead>
                <tr>
                  <th>姓名</th><th>邮箱</th><th>公司角色</th><th>项目成员关系</th><th>状态</th><th>最近会话</th><th>操作</th>
                </tr>
              </thead>
              <tbody>
                {people.map((u) => (
                  <tr key={u.user_id} className={u.status === "inactive" ? "pp-row-disabled" : ""}>
                    <td className="pp-cell-name">{u.name}</td>
                    <td>{u.email}</td>
                    <td>
                      <span className="pp-role-tags">
                        {u.company_roles.filter((c) => c.status === "active").map((c) => (
                          <span key={c.role_id} className="pp-role-tag">{companyRoleLabel[c.company_role] ?? c.company_role}</span>
                        ))}
                      </span>
                    </td>
                    <td className="pp-cell-projects">
                      {u.project_memberships.filter((m) => m.status === "active").length > 0
                        ? u.project_memberships.filter((m) => m.status === "active").map((m) => (
                            <span key={m.membership_id} className="pp-project-role-item">
                              <span className="pp-pr-project">{m.project_name}</span>
                              <span className="pp-pr-role">{projectRoleLabel[m.project_role] ?? m.project_role}</span>
                            </span>
                          ))
                        : <span className="pp-no-project">—</span>}
                    </td>
                    <td><span className={`pp-status-pill ${statusCls[u.status] ?? ""}`}>{statusLabel[u.status] ?? u.status}</span></td>
                    <td className="pp-cell-time">{fmtTime(u.recent_session_at)}</td>
                    <td><button className="btn-small" onClick={() => void openDetail(u.user_id)}>查看 / 治理</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="page-help-line">
        人员 / 公司角色 / 项目成员关系经后端权限校验与审计；身份与权限边界见 <Link to="/help#identity" className="page-help-link">使用说明 →</Link>
      </p>
    </div>
  );
}

function CompanyRoleForm({ onSubmit }: { onSubmit: (role: string, status: string) => void }) {
  const [role, setRole] = useState("consultant");
  const [status, setStatus] = useState("active");
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
      <select className="up-edit-select" value={role} onChange={(e) => setRole(e.target.value)}>
        {COMPANY_ROLE_OPTIONS.map((r) => <option key={r} value={r}>{companyRoleLabel[r]}</option>)}
      </select>
      <select className="up-edit-select" value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="active">正常</option>
        <option value="inactive">已停用</option>
      </select>
      <button className="btn-small btn-small-primary" onClick={() => onSubmit(role, status)}>设置公司角色</button>
    </div>
  );
}

// 设置 / 重置密码表单。密码 type=password、提交后立即清空、绝不回显。
function SetPasswordForm({ onSubmit }: { onSubmit: (password: string) => Promise<void> }) {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!pw || busy) return;
    setBusy(true);
    try {
      await onSubmit(pw);
      setPw("");  // 保存后立即清空，不回显
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
      <button className="btn-small btn-small-primary" disabled={busy || !pw} onClick={() => void submit()}>
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
  const [projectId, setProjectId] = useState("");
  const [role, setRole] = useState("consultant");
  useEffect(() => {
    if (!projectId && projects.length > 0) setProjectId(projects[0].id);
  }, [projects, projectId]);
  if (projects.length === 0) {
    return <p className="pp-no-project" style={{ marginTop: 8 }}>暂无可选项目（项目列表来自当前已加载人员的成员关系）。</p>;
  }
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
      <select className="up-edit-select" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
        {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
      <select className="up-edit-select" value={role} onChange={(e) => setRole(e.target.value)}>
        {PROJECT_ROLE_OPTIONS.map((r) => <option key={r} value={r}>{projectRoleLabel[r]}</option>)}
      </select>
      <button className="btn-small btn-small-primary" onClick={() => projectId && onSubmit(projectId, role)}>新增 / 更新成员关系</button>
    </div>
  );
}

