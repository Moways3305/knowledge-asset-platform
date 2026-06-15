import { useState, useMemo, useCallback, useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/http";
import { fetchAuthMe, type AuthMeVM } from "../api/auth";
import {
  fetchProjectSettings,
  updateProjectSettings,
  fetchProjectMembers,
  patchProjectMember,
} from "../api/project";
import type { ProjectSettingsDTO, ProjectMemberDTO } from "../types/projectSettings";
import { formatBeijingTime } from "../utils/time";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const projectRoleLabel: Record<string, string> = {
  coach: "辅导老师",
  project_manager: "项目经理",
  consultant: "顾问",
};
const projectRoleCls: Record<string, string> = {
  coach: "ps-role-coach",
  project_manager: "ps-role-pm",
  consultant: "ps-role-consultant",
};
const companyRoleLabel: Record<string, string> = {
  boss: "Boss",
  consulting_director: "咨询总监",
  consultant: "顾问",
  admin: "管理员",
};
const statusLabel: Record<string, string> = {
  active: "进行中",
  completed: "已完成",
  archived: "已归档",
  inactive: "已停用",
};
const statusCls: Record<string, string> = {
  active: "ps-st-active",
  completed: "ps-st-reviewing",
  archived: "ps-st-archived",
  inactive: "ps-st-archived",
};

// UI 可选项（route 枚举为前端展示元数据，非后端业务数据；当前值始终来自后端）。
const ROUTE_OPTIONS = ["route_A", "route_B", "route_C"];
const routeLabel: Record<string, string> = {
  route_A: "完整路线",
  route_B: "年度辅导循环",
  route_C: "专项诊断",
};
const PROJECT_ROLE_OPTIONS = ["coach", "project_manager", "consultant"];


// 用户可见时间统一北京时间。
const fmtTime = (iso: string | null): string => formatBeijingTime(iso);

export default function ProjectSettingsPage() {
  const { id } = useParams<{ id: string }>();
  const [projectId, setProjectId] = useState<string | null>(null);
  const [settings, setSettings] = useState<ProjectSettingsDTO | null>(null);
  const [members, setMembers] = useState<ProjectMemberDTO[]>([]);
  const [canManage, setCanManage] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState<string | null>(null);
  const [wecomInput, setWecomInput] = useState("");

  const describeError = (e: unknown, fallback: string) =>
    e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : fallback;

  // 解析有效项目：优先路由 UUID（且为本人有效项目），否则回退到第一个有效项目。
  const resolveProjectId = useCallback((me: AuthMeVM): string | null => {
    if (id && UUID_RE.test(id)) {
      const matched = me.projects.find((p) => p.projectId === id);
      if (matched) return matched.projectId;
      return id; // 真实 UUID 直连（治理角色可读非本人项目；后端兜底权限）
    }
    return me.projects[0]?.projectId ?? null;
  }, [id]);

  const loadProject = useCallback(async (pid: string) => {
    setLoading(true);
    setError(null);
    setActionError(null);
    setActionNote(null);
    try {
      const [s, m] = await Promise.all([
        fetchProjectSettings(pid),
        fetchProjectMembers(pid),
      ]);
      setSettings(s);
      setMembers(m.items);
      setCanManage(m.can_manage);
    } catch (e) {
      setError(describeError(e, "项目设置加载失败"));
      setSettings(null);
      setMembers([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await fetchAuthMe();
        if (cancelled) return;
        const pid = resolveProjectId(me);
        setProjectId(pid);
        if (pid) {
          await loadProject(pid);
        } else {
          setError("当前身份没有可展示的项目成员关系；请从项目看板进入，或在「人员权限」维护项目成员关系。");
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError(describeError(e, "加载身份失败（请确认后端已启动并已登录）"));
          setLoading(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [resolveProjectId, loadProject]);

  const refresh = useCallback(async () => {
    if (projectId) await loadProject(projectId);
  }, [projectId, loadProject]);

  const canWrite = settings?.can_write ?? false;

  const patchSettings = useCallback(async (body: Record<string, unknown>, note: string) => {
    if (!projectId) return;
    setSaving(true);
    setActionError(null);
    setActionNote(null);
    try {
      const updated = await updateProjectSettings(projectId, body);
      setSettings(updated);
      setActionNote(note);
    } catch (e) {
      setActionError(describeError(e, "保存失败"));
      // 失败重新拉取，保证 UI 与后端一致（回滚乐观更新）。
      await refresh();
    } finally {
      setSaving(false);
    }
  }, [projectId, refresh]);

  const changeMember = useCallback(async (memberId: string, body: { project_role?: string; status?: string }, note: string) => {
    if (!projectId) return;
    setActionError(null);
    setActionNote(null);
    try {
      const updated = await patchProjectMember(projectId, memberId, body);
      setMembers((prev) => prev.map((m) => (m.member_id === memberId ? updated : m)));
      setActionNote(note);
    } catch (e) {
      setActionError(describeError(e, "更新成员失败"));
    }
  }, [projectId]);

  const stats = useMemo(() => {
    const total = members.length;
    const mgmt = members.filter((m) => (m.project_role === "coach" || m.project_role === "project_manager") && m.status === "active").length;
    return {
      total,
      mgmt,
      wecomBound: settings?.wecom_group_bound ? 1 : 0,
      forceReview: settings?.force_review_on_ingest ?? false,
    };
  }, [members, settings]);

  // 403 文案区分
  const isMembershipErr = error?.includes("project_membership_required");
  const isWriteForbidden = actionError?.includes("project_settings_write_forbidden");
  const isAdminDenied = actionError?.includes("admin_business_permission_denied");

  return (
    <div className="ps-page">
      <div className="kl-header">
        <div className="kl-header-text">
          <h2>项目设置</h2>
          <p>管理项目人员、项目内角色与入库策略（真实后端 API）。{settings ? `当前项目：${settings.name}` : ""}</p>
        </div>
        <div className="kl-kpis">
          <div className="kl-kpi"><div className="kl-kpi-value">{stats.total}</div><div className="kl-kpi-label">项目人员</div></div>
          <div className="kl-kpi"><div className="kl-kpi-value">{stats.mgmt}</div><div className="kl-kpi-label">教练/经理</div></div>
          <div className="kl-kpi"><div className="kl-kpi-value">{stats.wecomBound}</div><div className="kl-kpi-label">绑定企微群</div></div>
          <div className="kl-kpi"><div className={`kl-kpi-value ${stats.forceReview ? "ps-kpi-on" : ""}`}>{stats.forceReview ? "开启" : "关闭"}</div><div className="kl-kpi-label">强制审核</div></div>
        </div>
      </div>

      <p className="page-help-line">
        项目内角色（辅导老师 / 项目经理 / 顾问）职责与设置写权见 <Link to="/help#project" className="page-help-link">使用说明 →</Link>
      </p>

      {actionError && (
        <div className="au-error-banner">
          <p>{actionError}</p>
          {isWriteForbidden && <p className="au-error-hint">顾问成员只读，项目设置修改需 project_manager / coach 或 Boss / 咨询总监。</p>}
          {isAdminDenied && <p className="au-error-hint">admin 是系统身份，不修改项目业务设置。</p>}
        </div>
      )}
      {actionNote && <div className="up-submit-notice" style={{ color: "var(--color-success-fg, #176)" }}>{actionNote}</div>}

      {error ? (
        <div className="ig-empty-state">
          <div className="ig-empty-title">无法加载项目设置</div>
          <p className="ig-empty-desc">{error}</p>
          {isMembershipErr && <p className="ig-empty-desc">项目设置仅对本项目成员 / Boss / 咨询总监 / admin 开放；可经 <code>VITE_DEV_USER_ID</code> 切换授权身份。</p>}
          {projectId && <button className="btn-small" onClick={() => void refresh()}>重试</button>}
        </div>
      ) : loading ? (
        <div className="ig-empty-state"><div className="ig-empty-title">加载中…</div></div>
      ) : settings ? (
        <>
          {!canWrite && (
            <div className="role-context-hint">
              <div className="role-context-hint-title">只读视角</div>
              当前身份对本项目设置为只读（顾问成员 / admin 系统身份）。可查看项目规则与成员，修改需 project_manager / coach 或 Boss / 咨询总监。
            </div>
          )}

          {/* 项目基础信息 */}
          <section className="ps-section">
            <h3>项目基础信息</h3>
            <div className="ps-info-grid">
              <div className="ps-info-item"><span className="ps-info-label">项目名称</span><span className="ps-info-value">{settings.name}</span></div>
              <div className="ps-info-item"><span className="ps-info-label">客户名称</span><span className="ps-info-value">{settings.client_name ?? "—"}</span></div>
              <div className="ps-info-item"><span className="ps-info-label">项目状态</span><span className="ps-info-value"><span className={`ps-status-pill ${statusCls[settings.status] ?? ""}`}>{statusLabel[settings.status] ?? settings.status}</span></span></div>
              <div className="ps-info-item"><span className="ps-info-label">辅导老师</span><span className="ps-info-value">{settings.coach_name ?? "—"}</span></div>
              <div className="ps-info-item"><span className="ps-info-label">最近更新</span><span className="ps-info-value">{fmtTime(settings.updated_at)}</span></div>
            </div>
          </section>

          {/* 生命周期 */}
          <section className="ps-section">
            <h3>项目生命周期路线</h3>
            <div className="lifecycle-route-card">
              <div className="lifecycle-route-current">
                <span className="lifecycle-route-label">当前路线</span>
                <span className="lifecycle-route-value">
                  {canWrite ? (
                    <select
                      className="ps-role-select"
                      value={settings.lifecycle_route_key ?? ""}
                      disabled={saving}
                      onChange={(e) => void patchSettings({ lifecycle_route_key: e.target.value }, "生命周期路线已更新")}
                    >
                      {ROUTE_OPTIONS.map((r) => <option key={r} value={r}>{r} {routeLabel[r]}</option>)}
                    </select>
                  ) : (
                    <>{settings.lifecycle_route_key ?? "—"} {settings.lifecycle_route_key ? routeLabel[settings.lifecycle_route_key] ?? "" : ""}</>
                  )}
                </span>
              </div>
              <div className="lifecycle-route-current">
                <span className="lifecycle-route-label">当前阶段</span>
                <span className="lifecycle-route-value">
                  {canWrite ? (
                    <PhaseEditor
                      value={settings.lifecycle_phase_key ?? ""}
                      saving={saving}
                      onSave={(v) => void patchSettings({ lifecycle_phase_key: v }, "当前阶段已更新")}
                    />
                  ) : (
                    <span className="phase-tag phase-tag-active">{settings.lifecycle_phase_key ?? "—"}</span>
                  )}
                </span>
              </div>
            </div>
          </section>

          {/* 入库策略 */}
          <section className="ps-section">
            <h3>项目入库策略</h3>
            <div className="ps-policy-card">
              <div className="ps-policy-head">
                <div className="ps-policy-info">
                  <span className="ps-policy-key"><code>force_review_on_ingest</code></span>
                  <span className="ps-policy-desc">
                    {settings.force_review_on_ingest
                      ? "已开启：项目库入库任务统一进入项目审核，不允许 direct_ingest"
                      : "已关闭：低风险高置信度任务可直接入项目知识库"}
                  </span>
                </div>
                <button
                  className={`ps-toggle ${settings.force_review_on_ingest ? "ps-toggle-on" : "ps-toggle-off"}`}
                  disabled={!canWrite || saving}
                  title={canWrite ? "" : "只读：需 project_manager / coach 或治理角色"}
                  onClick={() => void patchSettings({ force_review_on_ingest: !settings.force_review_on_ingest }, "入库策略已更新")}
                >
                  {settings.force_review_on_ingest ? "开启" : "关闭"}
                </button>
              </div>
            </div>
          </section>

          {/* 企微群绑定 */}
          <section className="ps-section">
            <h3>企微群绑定</h3>
            <div className="ps-policy-card">
              <div className="ps-info-item">
                <span className="ps-info-label">绑定状态</span>
                <span className="ps-info-value">
                  {settings.wecom_group_bound
                    ? <>已绑定 <code>{settings.wecom_group_label}</code></>
                    : "未绑定"}
                </span>
              </div>
              {canWrite ? (
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10 }}>
                  <input
                    className="up-edit-input"
                    placeholder="输入企微群 ID 以绑定 / 替换（留空提交可解绑）"
                    value={wecomInput}
                    onChange={(e) => setWecomInput(e.target.value)}
                  />
                  <button
                    className="btn-small btn-small-primary"
                    disabled={saving}
                    onClick={() => { void patchSettings({ wecom_group_id: wecomInput }, "企微群绑定已更新"); setWecomInput(""); }}
                  >
                    保存绑定
                  </button>
                </div>
              ) : null}
              <p className="au-note" style={{ marginTop: 8 }}>
                只展示脱敏后缀，不显示企微群完整标识等敏感信息；企微群真实成员同步不在本页范围。未配置企微能力时仅保存项目配置值，不假装同步成功。
              </p>
            </div>
          </section>

          {/* 项目人员 */}
          <section className="ps-section">
            <h3>项目人员</h3>
            {members.length === 0 ? (
              <div className="ig-empty-state"><div className="ig-empty-title">暂无项目成员</div></div>
            ) : (
              <div className="ps-table-wrap">
                <table className="ps-table">
                  <thead>
                    <tr>
                      <th>姓名</th><th>邮箱</th><th>公司角色</th><th>项目内角色</th><th>状态</th><th>加入时间</th>{canManage && <th>操作</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {members.map((m) => (
                      <tr key={m.member_id} className={m.status !== "active" ? "ps-row-disabled" : ""}>
                        <td className="ps-cell-name">{m.name}</td>
                        <td>{m.email}</td>
                        <td>
                          <span className="ps-cell-platform">
                            {m.company_roles.length > 0 ? m.company_roles.map((c) => companyRoleLabel[c] ?? c).join(" / ") : "—"}
                          </span>
                        </td>
                        <td>
                          {canManage ? (
                            <select
                              className="ps-role-select"
                              value={m.project_role}
                              onChange={(e) => void changeMember(m.member_id, { project_role: e.target.value }, "项目角色已更新")}
                            >
                              {PROJECT_ROLE_OPTIONS.map((r) => <option key={r} value={r}>{projectRoleLabel[r]}</option>)}
                            </select>
                          ) : (
                            <span className={`ps-role-pill ${projectRoleCls[m.project_role] ?? ""}`}>{projectRoleLabel[m.project_role] ?? m.project_role}</span>
                          )}
                        </td>
                        <td><span className={`ps-status-pill ${statusCls[m.status] ?? ""}`}>{statusLabel[m.status] ?? m.status}</span></td>
                        <td className="ps-cell-time">{fmtTime(m.joined_at)}</td>
                        {canManage && (
                          <td>
                            <button
                              className="btn-small"
                              onClick={() => void changeMember(m.member_id, { status: m.status === "active" ? "inactive" : "active" }, "成员状态已更新")}
                            >
                              {m.status === "active" ? "停用" : "启用"}
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="au-note" style={{ marginTop: 8 }}>
              新增 / 移除项目成员请到 <Link to="/admin/people">人员权限</Link> 维护项目成员关系；本页只调整已加入成员的项目角色与状态。
            </p>
          </section>

          {/* 关联入口 */}
          <section className="ps-section">
            <h3>关联入口</h3>
            <div className="ps-links-grid">
              <div className="ps-link-card">
                <div className="ps-link-title">项目知识看板</div>
                <div className="ps-link-desc">查看当前项目知识资产、阶段 Q&A 与风险提醒</div>
                <Link to={`/project/${projectId}/knowledge`} className="ps-link-action">前往项目看板 →</Link>
              </div>
              <div className="ps-link-card">
                <div className="ps-link-title">全局人员权限</div>
                <div className="ps-link-desc">管理跨项目、多角色、平台角色与权限边界</div>
                <Link to="/admin/people" className="ps-link-action">前往人员权限 →</Link>
              </div>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

// 阶段编辑器：受控文本输入 + 保存（阶段标签随路线而异，用输入框而非固定枚举）。
function PhaseEditor({ value, saving, onSave }: { value: string; saving: boolean; onSave: (v: string) => void }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => { setDraft(value); }, [value]);
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
      <input
        className="up-edit-input"
        style={{ maxWidth: 180 }}
        placeholder="当前阶段标签"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      <button className="btn-small" disabled={saving || draft === value} onClick={() => onSave(draft)}>保存</button>
    </span>
  );
}

