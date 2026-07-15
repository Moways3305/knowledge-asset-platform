import { useState, useMemo, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/http";
import { fetchAuthMe } from "../api/auth";
import {
  fetchPermissionRules,
  updatePermissionRule,
  fetchAgentRegistry,
  setAgentRegistryEnabled,
} from "../api/admin";
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
const fmtTime = (iso: string | null): string => formatBeijingTime(iso);

function valueText(r: PermissionRuleDTO): string {
  if (r.rule_type === "numeric") return `${r.value_number ?? 0}${r.unit ? ` ${r.unit}` : ""}`;
  if (r.rule_type === "toggle") return r.value_bool ? "已启用" : "已停用";
  return r.value_text ?? "—";
}
function defaultText(r: PermissionRuleDTO): string {
  if (r.rule_type === "numeric") return `${r.default_number ?? 0}${r.unit ? ` ${r.unit}` : ""}`;
  if (r.rule_type === "toggle") return r.default_bool ? "已启用" : "已停用";
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
    let editable = false;
    let admin = false;
    try {
      const me = await fetchAuthMe();
      editable =
        me.companyRoles.includes("boss") || me.companyRoles.includes("consulting_director");
      admin = me.companyRoles.includes("admin");
    } catch {
      /* 身份获取失败按只读处理，写动作仍由服务端校验。 */
    }
    setCanEditRules(editable);
    setIsAdmin(admin);

    try {
      const data = await fetchPermissionRules();
      setRules(data.items);
    } catch (e) {
      setError(describeError(e, "权限规则暂时无法加载，请稍后重试"));
      setRules([]);
    } finally {
      setLoading(false);
    }

    try {
      const reg = await fetchAgentRegistry();
      setAgents(reg.items);
      setAgentNote(null);
    } catch (e) {
      setAgents([]);
      const reason = e instanceof ApiError ? (e.deniedReason ?? String(e.status)) : "未知错误";
      setAgentNote(`外部助手接入注册由系统管理员管理；当前身份无法读取（${reason}）。`);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const stats = useMemo(
    () => ({
      total: rules.length,
      enabledAgents: agents.filter((a) => a.enabled).length,
      modified: rules.filter(isChanged).length,
      riskAgents: agents.filter((a) => a.risk_note).length,
    }),
    [rules, agents],
  );

  const groupedRules = useMemo(() => {
    const map: Record<string, PermissionRuleDTO[]> = {
      personal_flow: [],
      project_upgrade: [],
      access_request: [],
      asset_lifecycle: [],
    };
    rules.forEach((r) => {
      (map[r.rule_group] ??= []).push(r);
    });
    return map;
  }, [rules]);

  const startEdit = useCallback((rule: PermissionRuleDTO) => {
    if (!rule.editable || rule.rule_type !== "numeric") return;
    setActionError(null);
    setEditingId(rule.rule_id);
    setEditValue(rule.value_number ?? 0);
  }, []);

  const applyUpdate = useCallback(
    async (ruleId: string, patch: { value_number?: number; value_bool?: boolean }) => {
      setActionError(null);
      try {
        const updated = await updatePermissionRule(ruleId, patch);
        setRules((prev) => prev.map((r) => (r.rule_id === ruleId ? updated : r)));
        setEditingId(null);
      } catch (e) {
        setActionError(describeError(e, "更新规则失败"));
      }
    },
    [],
  );

  const toggleAgent = useCallback(async (agent: AgentRegistryRuleDTO) => {
    setActionError(null);
    try {
      const updated = await setAgentRegistryEnabled(agent.id, !agent.enabled);
      setAgents((prev) => prev.map((a) => (a.id === agent.id ? updated : a)));
    } catch (e) {
      setActionError(describeError(e, "更新 Agent 接入状态失败"));
    }
  }, []);

  const isForbidden = error?.includes("permission_rules_forbidden");
  const displayedGroups = groupOrder.filter((g) => (groupedRules[g] ?? []).length > 0);

  return (
    <div className="policy">
      <div className="kb-masthead">
        <div>
          <div className="kb-eyebrow">Governance · 治理规则册</div>
          <h2 className="kb-title">权限规则管理</h2>
          <p className="kb-lead">
            配置知识流转阈值、访问申请策略与外部 Agent 接入注册。总经理 /
            咨询总监可修改业务权限规则；admin 只读；修改写入审计日志。
          </p>
        </div>
        <div className="kb-metrics">
          <div className="kb-metric">
            <div className="kb-metric-value">{stats.total}</div>
            <div className="kb-metric-label">可配置规则</div>
          </div>
          <div className="kb-metric">
            <div className="kb-metric-value">{stats.enabledAgents}</div>
            <div className="kb-metric-label">已启用 Agent</div>
          </div>
          <div className="kb-metric">
            <div className="kb-metric-value is-warning">{stats.modified}</div>
            <div className="kb-metric-label">已调整</div>
          </div>
          <div className="kb-metric">
            <div className={`kb-metric-value ${stats.riskAgents > 0 ? "is-warning" : "is-muted"}`}>
              {stats.riskAgents}
            </div>
            <div className="kb-metric-label">风险提示</div>
          </div>
        </div>
      </div>

      {!loading &&
        !error &&
        (canEditRules ? (
          <div className="policy-role is-edit">
            当前身份可<strong>查看并修改</strong>业务权限规则（总经理 / 咨询总监）。
          </div>
        ) : isAdmin ? (
          <div className="policy-role is-readonly">
            当前身份为 <strong>admin（系统身份）</strong>
            ：可查看权限规则，但不能修改业务权限规则。修改请使用总经理 / 咨询总监身份。
          </div>
        ) : null)}

      {actionError && <div className="adminx-banner is-error">{actionError}</div>}

      {error ? (
        <div className="kb-state">
          <div className="kb-state-icon is-error">!</div>
          <div className="kb-state-title">无法加载权限规则</div>
          <p className="kb-state-desc">{error}</p>
          <p className="kb-state-desc">
            {isForbidden
              ? "权限规则查看仅对 admin / 总经理 / 咨询总监开放，顾问无权访问。"
              : "切换为授权身份后重试。"}
          </p>
          <button className="btn-secondary" onClick={() => void load()}>
            重试
          </button>
        </div>
      ) : loading ? (
        <div className="kb-state">
          <div className="kb-state-title">加载中…</div>
        </div>
      ) : (
        <>
          {displayedGroups.map((group, gi) => (
            <section key={group} className="policy-group">
              <div className="policy-group-head">
                <span className="policy-group-no">{String(gi + 1).padStart(2, "0")}</span>
                <span className="policy-group-title">{groupLabel[group] ?? group}</span>
                <span className="policy-group-rule">
                  {(groupedRules[group] ?? []).length} 条规则
                </span>
              </div>
              <div className="policy-ledger">
                {(groupedRules[group] ?? []).map((rule) => {
                  const editing = editingId === rule.rule_id;
                  return (
                    <div key={rule.rule_id} className="policy-row">
                      <div>
                        <span className="policy-name">{rule.display_name}</span>
                        <span className="policy-type">
                          {ruleTypeLabel[rule.rule_type] ?? rule.rule_type}
                        </span>
                        <div className="policy-key">{rule.rule_key}</div>
                      </div>
                      <div className="policy-value">
                        {editing && rule.rule_type === "numeric" ? (
                          <span className="policy-edit-inline">
                            <input
                              type="number"
                              className="policy-input"
                              min={0}
                              value={editValue}
                              onChange={(e) => setEditValue(Math.max(0, Number(e.target.value)))}
                            />
                            <span>{rule.unit ?? ""}</span>
                          </span>
                        ) : (
                          <span
                            className={`policy-value-now ${isChanged(rule) ? "is-changed" : ""}`}
                          >
                            {valueText(rule)}
                          </span>
                        )}
                        <span className="policy-value-default">默认 {defaultText(rule)}</span>
                      </div>
                      <div>
                        <div className="policy-desc">{rule.description}</div>
                        {rule.updated_by_name && (
                          <div className="policy-meta">
                            最近修改：{rule.updated_by_name} · {fmtTime(rule.updated_at)}
                          </div>
                        )}
                      </div>
                      <div className="policy-actions">
                        {!rule.editable ? (
                          <span className="policy-readonly">只读 · 固定路径</span>
                        ) : !canEditRules ? (
                          <span className="policy-readonly">
                            {isAdmin ? "admin 只读" : "无修改权"}
                          </span>
                        ) : editing ? (
                          <>
                            <button
                              className="btn-small btn-small-primary"
                              onClick={() =>
                                void applyUpdate(rule.rule_id, { value_number: editValue })
                              }
                            >
                              保存
                            </button>
                            <button className="btn-small" onClick={() => setEditingId(null)}>
                              取消
                            </button>
                          </>
                        ) : rule.rule_type === "toggle" ? (
                          <button
                            className="btn-small"
                            onClick={() =>
                              void applyUpdate(rule.rule_id, { value_bool: !rule.value_bool })
                            }
                          >
                            {rule.value_bool ? "停用" : "启用"}
                          </button>
                        ) : (
                          <button className="btn-small" onClick={() => startEdit(rule)}>
                            编辑
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}

          <section className="policy-group">
            <div className="policy-group-head">
              <span className="policy-group-no">
                {String(displayedGroups.length + 1).padStart(2, "0")}
              </span>
              <span className="policy-group-title">外部助手接入注册</span>
              <span className="policy-group-rule">接入白名单</span>
            </div>
            {agentNote ? (
              <div className="policy-role is-readonly">{agentNote}</div>
            ) : agents.length === 0 ? (
              <div className="kb-state">
                <div className="kb-state-title">暂无已注册的外部助手接入</div>
              </div>
            ) : (
              <div className="policy-ledger">
                {agents.map((agent) => (
                  <div
                    key={agent.id}
                    className={`policy-row ${!agent.enabled ? "is-disabled" : ""}`}
                  >
                    <div>
                      <span className="policy-name">{agent.agent_name}</span>
                      <div className="policy-key">
                        {agent.provider} · {agent.capability} ·{" "}
                        {agent.allowed_scope
                          ? (scopeLabel[agent.allowed_scope] ?? agent.allowed_scope)
                          : "全范围"}{" "}
                        · 最高 {agent.max_confidentiality_level}
                      </div>
                    </div>
                    <div className="policy-value">
                      <span className={`policy-status ${agent.enabled ? "on" : "off"}`}>
                        {agent.enabled ? "已启用" : "已停用"}
                      </span>
                    </div>
                    <div className="policy-desc">
                      {agent.risk_note ? (
                        <span className="policy-risk">{agent.risk_note}</span>
                      ) : (
                        "—"
                      )}
                    </div>
                    <div className="policy-actions">
                      <button
                        className={agent.enabled ? "btn-small" : "btn-small btn-small-primary"}
                        onClick={() => void toggleAgent(agent)}
                      >
                        {agent.enabled ? "停用" : "启用"}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      <p className="page-help-line">
        配置知识访问规则和外部助手接入状态，详细运行说明见{" "}
        <Link to="/help#integration" className="page-help-link">
          使用说明 →
        </Link>
      </p>
    </div>
  );
}
