import { useState, useMemo, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  fetchAuthMe,
  fetchPermissionRules,
  updatePermissionRule,
  fetchAgentRegistry,
  setAgentRegistryEnabled,
} from "../api/client";
import type { PermissionRuleDTO, AgentRegistryRuleDTO } from "../types/permission";
import { formatBeijingTime } from "../utils/time";

const ruleTypeLabel: Record<string, string> = {
  numeric: "数字阈值",
  toggle: "开关规则",
  fixed_path: "固定路径",
};

const groupLabel: Record<string, string> = {
  personal_flow: "个人知识流转",
  project_upgrade: "项目知识升格",
  access_request: "访问申请",
  asset_lifecycle: "资产生命周期",
};

const groupOrder = ["personal_flow", "project_upgrade", "access_request", "asset_lifecycle"];

const scopeLabel: Record<string, string> = {
  project: "项目级",
  company: "公司级",
  personal: "个人级",
  "project:": "项目级",
};

// 用户可见时间统一北京时间（PBC-10C）。
const fmtTime = (iso: string | null): string => formatBeijingTime(iso);

// 规则「当前值」展示（按 rule_type）。
function valueText(r: PermissionRuleDTO): string {
  if (r.rule_type === "numeric") {
    return `${r.value_number ?? 0}${r.unit ? ` ${r.unit}` : ""}`;
  }
  if (r.rule_type === "toggle") {
    return r.value_bool ? "已启用" : "已停用";
  }
  return r.value_text ?? "—";
}

function defaultText(r: PermissionRuleDTO): string {
  if (r.rule_type === "numeric") {
    return `${r.default_number ?? 0}${r.unit ? ` ${r.unit}` : ""}`;
  }
  if (r.rule_type === "toggle") {
    return r.default_bool ? "已启用" : "已停用";
  }
  return r.default_text ?? "—";
}

function isChanged(r: PermissionRuleDTO): boolean {
  if (r.rule_type === "numeric") return r.value_number !== r.default_number;
  if (r.rule_type === "toggle") return r.value_bool !== r.default_bool;
  return false;
}


export default function AdminPermissionsPage() {
  const [rules, setRules] = useState<PermissionRuleDTO[]>([]);
  const [agents, setAgents] = useState<AgentRegistryRuleDTO[]>([]);
  const [agentNote, setAgentNote] = useState<string | null>(null);
  const [canEditRules, setCanEditRules] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState<number>(0);

  const describeError = (e: unknown, fallback: string) =>
    e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : fallback;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setActionError(null);
    // 身份用于区分「可编辑」(boss/咨询总监) 与「只读」(admin)。失败不阻断规则加载。
    let editable = false;
    let admin = false;
    try {
      const me = await fetchAuthMe();
      editable = me.companyRoles.includes("boss") || me.companyRoles.includes("consulting_director");
      admin = me.companyRoles.includes("admin");
    } catch {
      /* 身份获取失败时按只读处理，写动作仍由后端兜底 403 */
    }
    setCanEditRules(editable);
    setIsAdmin(admin);

    try {
      const data = await fetchPermissionRules();
      setRules(data.items);
    } catch (e) {
      setError(describeError(e, "权限规则加载失败（请确认后端已启动）"));
      setRules([]);
    } finally {
      setLoading(false);
    }

    // Agent Registry 为后端兼容接口（admin 管理）。非 admin 读取会被后端拒绝——
    // 不伪造数据，按真实返回 / 真实拒绝处理。
    try {
      const reg = await fetchAgentRegistry();
      setAgents(reg.items);
      setAgentNote(null);
    } catch (e) {
      setAgents([]);
      const reason = e instanceof ApiError ? e.deniedReason ?? String(e.status) : "未知错误";
      setAgentNote(`外部 Agent 接入注册由 admin 管理；当前身份无法读取（${reason}）。`);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const stats = useMemo(() => {
    const total = rules.length;
    const enabledAgents = agents.filter((a) => a.enabled).length;
    const modified = rules.filter(isChanged).length;
    const riskAgents = agents.filter((a) => a.risk_note).length;
    return { total, enabledAgents, modified, riskAgents };
  }, [rules, agents]);

  const groupedRules = useMemo(() => {
    const map: Record<string, PermissionRuleDTO[]> = {
      personal_flow: [], project_upgrade: [], access_request: [], asset_lifecycle: [],
    };
    rules.forEach((r) => { (map[r.rule_group] ??= []).push(r); });
    return map;
  }, [rules]);

  const startEdit = useCallback((rule: PermissionRuleDTO) => {
    if (!rule.editable || rule.rule_type !== "numeric") return;
    setActionError(null);
    setEditingId(rule.rule_id);
    setEditValue(rule.value_number ?? 0);
  }, []);

  const applyUpdate = useCallback(async (ruleId: string, patch: { value_number?: number; value_bool?: boolean }) => {
    setActionError(null);
    try {
      const updated = await updatePermissionRule(ruleId, patch);
      setRules((prev) => prev.map((r) => (r.rule_id === ruleId ? updated : r)));
      setEditingId(null);
    } catch (e) {
      setActionError(describeError(e, "更新规则失败"));
    }
  }, []);

  const toggleAgent = useCallback(async (agent: AgentRegistryRuleDTO) => {
    setActionError(null);
    try {
      const updated = await setAgentRegistryEnabled(agent.id, !agent.enabled);
      setAgents((prev) => prev.map((a) => (a.id === agent.id ? updated : a)));
    } catch (e) {
      setActionError(describeError(e, "更新 Agent 接入状态失败"));
    }
  }, []);

  // consultant 无读权 → 后端 403 permission_rules_forbidden；区分文案。
  const isForbidden = error?.includes("permission_rules_forbidden");

  return (
    <div className="perm-page">
      <div className="kl-header">
        <div className="kl-header-text">
          <h2>权限规则管理</h2>
          <p>配置知识流转阈值、访问申请策略与外部 Agent 接入注册（真实后端 API）。Boss / 咨询总监可修改业务权限规则；admin 只读；修改写入审计日志。</p>
        </div>
        <div className="kl-kpis">
          <div className="kl-kpi"><div className="kl-kpi-value">{stats.total}</div><div className="kl-kpi-label">可配置规则</div></div>
          <div className="kl-kpi"><div className="kl-kpi-value">{stats.enabledAgents}</div><div className="kl-kpi-label">已启用 Agent</div></div>
          <div className="kl-kpi"><div className="kl-kpi-value kl-kpi-warning">{stats.modified}</div><div className="kl-kpi-label">已调整规则</div></div>
          <div className="kl-kpi"><div className={`kl-kpi-value ${stats.riskAgents > 0 ? "perm-kpi-warning" : ""}`}>{stats.riskAgents}</div><div className="kl-kpi-label">风险提示项</div></div>
        </div>
      </div>

      {/* 角色能力提示 */}
      {!loading && !error && (
        canEditRules ? (
          <div className="perm-role-banner perm-role-banner-edit">当前身份可<strong>查看并修改</strong>业务权限规则（Boss / 咨询总监）。</div>
        ) : isAdmin ? (
          <div className="perm-role-banner perm-role-banner-readonly">当前身份为 <strong>admin（系统身份）</strong>：可查看权限规则，但不能修改业务权限规则。修改请使用 Boss / 咨询总监身份。</div>
        ) : null
      )}

      {actionError && <div className="au-error-banner"><p>{actionError}</p></div>}

      {/* 错误态 / 加载态 */}
      {error ? (
        <div className="ig-empty-state">
          <div className="ig-empty-title">无法加载权限规则</div>
          <p className="ig-empty-desc">{error}</p>
          <p className="ig-empty-desc">
            {isForbidden
              ? "权限规则查看仅对 admin / Boss / 咨询总监开放，顾问无权访问。"
              : "可经 VITE_DEV_USER_ID 切换为授权身份后重试。"}
          </p>
          <button className="btn-small" onClick={() => void load()}>重试</button>
        </div>
      ) : loading ? (
        <div className="ig-empty-state"><div className="ig-empty-title">加载中…</div></div>
      ) : (
        <>
          {/* Rule groups */}
          {groupOrder.map((group) => (
            (groupedRules[group] ?? []).length > 0 && (
              <section key={group} className="perm-section">
                <h3>{groupLabel[group] ?? group}</h3>
                <div className="perm-table-wrap">
                  <table className="perm-table">
                    <thead>
                      <tr>
                        <th>规则</th>
                        <th>rule_key</th>
                        <th>当前值</th>
                        <th>默认值</th>
                        <th>说明</th>
                        <th>最近修改</th>
                        <th>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(groupedRules[group] ?? []).map((rule) => {
                        const editing = editingId === rule.rule_id;
                        return (
                          <tr key={rule.rule_id}>
                            <td className="perm-cell-name">
                              {rule.display_name}
                              <span className={`perm-rule-type perm-rule-type-${rule.rule_type}`}>{ruleTypeLabel[rule.rule_type] ?? rule.rule_type}</span>
                            </td>
                            <td className="perm-cell-key"><code>{rule.rule_key}</code></td>
                            <td className="perm-cell-value">
                              {editing && rule.rule_type === "numeric" ? (
                                <span className="perm-edit-inline">
                                  <input
                                    type="number"
                                    className="perm-input"
                                    min={0}
                                    value={editValue}
                                    onChange={(e) => setEditValue(Math.max(0, Number(e.target.value)))}
                                  />
                                  <span className="perm-unit">{rule.unit ?? ""}</span>
                                </span>
                              ) : (
                                <span className={isChanged(rule) ? "perm-value-changed" : ""}>{valueText(rule)}</span>
                              )}
                            </td>
                            <td className="perm-cell-default">{defaultText(rule)}</td>
                            <td className="perm-cell-desc">{rule.description}</td>
                            <td className="perm-cell-modified">
                              <span className="perm-modified-by">{rule.updated_by_name ?? "—"}</span>
                              <span className="perm-modified-at">{rule.updated_by_name ? fmtTime(rule.updated_at) : ""}</span>
                            </td>
                            <td className="perm-cell-actions">
                              {!rule.editable ? (
                                <span className="perm-readonly-hint">只读：固定路径</span>
                              ) : !canEditRules ? (
                                <span className="perm-readonly-hint">{isAdmin ? "admin 只读" : "无修改权"}</span>
                              ) : editing ? (
                                <>
                                  <button className="btn-small-primary" onClick={() => void applyUpdate(rule.rule_id, { value_number: editValue })}>保存</button>
                                  <button className="btn-small" onClick={() => setEditingId(null)}>取消</button>
                                </>
                              ) : rule.rule_type === "toggle" ? (
                                <button className="btn-small" onClick={() => void applyUpdate(rule.rule_id, { value_bool: !rule.value_bool })}>
                                  {rule.value_bool ? "停用" : "启用"}
                                </button>
                              ) : (
                                <button className="btn-small" onClick={() => startEdit(rule)}>编辑</button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            )
          ))}

          {/* Agent registry（真实后端兼容接口） */}
          <section className="perm-section">
            <h3>外部 Agent 接入注册 / Agent Registry</h3>
            {agentNote ? (
              <div className="au-note">{agentNote}本区块来自 provider 中立后端兼容接口 <code>/admin/permissions/agent-whitelist</code>，不在前端伪造数据。</div>
            ) : agents.length === 0 ? (
              <div className="ig-empty-state"><div className="ig-empty-title">暂无已注册的外部 Agent 接入</div></div>
            ) : (
              <div className="perm-table-wrap">
                <table className="perm-table">
                  <thead>
                    <tr>
                      <th>接入名称</th>
                      <th>provider</th>
                      <th>能力</th>
                      <th>调用范围</th>
                      <th>最高保密级</th>
                      <th>状态</th>
                      <th>风险提示</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {agents.map((agent) => (
                      <tr key={agent.id} className={!agent.enabled ? "perm-row-disabled" : ""}>
                        <td className="perm-cell-name">{agent.agent_name}</td>
                        <td><span className="perm-scope-tag">{agent.provider}</span></td>
                        <td>{agent.capability}</td>
                        <td>{agent.allowed_scope ? (scopeLabel[agent.allowed_scope] ?? agent.allowed_scope) : "—"}</td>
                        <td>{agent.max_confidentiality_level}</td>
                        <td>
                          <span className={`perm-status-pill ${agent.enabled ? "perm-status-on" : "perm-status-off"}`}>
                            {agent.enabled ? "已启用" : "已停用"}
                          </span>
                        </td>
                        <td className="perm-cell-risk">{agent.risk_note || <span className="perm-no-risk">—</span>}</td>
                        <td>
                          <button
                            className={agent.enabled ? "btn-small" : "btn-small-primary"}
                            onClick={() => void toggleAgent(agent)}
                          >
                            {agent.enabled ? "停用" : "启用"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}

      <p className="page-help-line">
        权限规则来自真实 <code>permission_rules</code>（Boss / 咨询总监可改、admin 只读、写入审计）；外部 Agent 调用边界与规则运行时口径见 <Link to="/help#integration" className="page-help-link">使用说明 →</Link>
      </p>
    </div>
  );
}
