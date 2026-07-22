import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bot,
  BriefcaseBusiness,
  CircleCheck,
  CircleOff,
  Hash,
  Layers3,
  LockKeyhole,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  ToggleLeft,
} from "lucide-react";
import {
  fetchAgentRegistry,
  fetchPermissionRules,
  setAgentRegistryEnabled,
  updatePermissionRule,
} from "../api/admin";
import { fetchAuthMe } from "../api/auth";
import { ApiError } from "../api/http";
import { PageHeader, PageSection, PageToolbar, ProductPage } from "../components/ProductLayout";
import type { AgentRegistryRuleDTO, PermissionRuleDTO } from "../types/permission";
import { formatBeijingTime } from "../utils/time";

const ruleTypeLabel: Record<string, string> = {
  numeric: "数值规则",
  toggle: "开关规则",
  fixed_path: "固定规则",
};
const groupLabel: Record<string, string> = {
  personal_flow: "个人知识流转",
  project_upgrade: "项目知识升格",
  access_request: "访问申请",
  asset_lifecycle: "资产生命周期",
};
const capabilityLabel: Record<string, string> = {
  search: "知识检索",
  semantic_search: "语义检索",
  answer: "知识问答",
  original_access: "原文访问",
  knowledge_write: "知识写入",
};
const scopeLabel: Record<string, string> = {
  project: "项目范围",
  company: "公司范围",
  personal: "个人范围",
  "project:": "项目范围",
};

function valueText(rule: PermissionRuleDTO) {
  if (rule.rule_type === "numeric")
    return `${rule.value_number ?? 0}${rule.unit ? ` ${rule.unit}` : ""}`;
  if (rule.rule_type === "toggle") return rule.value_bool ? "已启用" : "已停用";
  return "由系统固定";
}

export default function AdminPermissionsPage() {
  const [rules, setRules] = useState<PermissionRuleDTO[]>([]);
  const [agents, setAgents] = useState<AgentRegistryRuleDTO[]>([]);
  const [canEditRules, setCanEditRules] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [agentError, setAgentError] = useState<string | null>(null);
  const [groupFilter, setGroupFilter] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState(0);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setAgentError(null);
    try {
      const me = await fetchAuthMe();
      setCanEditRules(
        me.activeCompanyRole === "boss" || me.activeCompanyRole === "consulting_director",
      );
      setIsAdmin(me.activeCompanyRole === "admin");
    } catch {
      setCanEditRules(false);
      setIsAdmin(false);
    }
    try {
      const response = await fetchPermissionRules();
      setRules(response.items);
    } catch (reason) {
      setRules([]);
      setError(
        reason instanceof ApiError && reason.status === 403
          ? "当前身份没有权限规则查看权限。"
          : "权限规则暂时无法加载，请稍后重试。",
      );
    }
    try {
      setAgents((await fetchAgentRegistry()).items);
    } catch (reason) {
      setAgents([]);
      setAgentError(
        reason instanceof ApiError && reason.status === 403
          ? "当前身份不能查看外部助手白名单。"
          : "外部助手白名单暂时无法加载。",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => void load(), [load]);

  const visibleRules = useMemo(
    () => rules.filter((rule) => !groupFilter || rule.rule_group === groupFilter),
    [groupFilter, rules],
  );
  const groups = useMemo(() => Array.from(new Set(rules.map((rule) => rule.rule_group))), [rules]);
  const enabledRules = rules.filter((rule) => rule.enabled).length;

  // 外部助手白名单去重：按 (provider, capability, allowed_scope, allowed_project_id) 分组，
  // 同组只保留一行（enabled 优先），并记录是否发生过去重以提示用户。
  const { dedupedAgents, hasDuplicates } = useMemo(() => {
    const groups = new Map<string, AgentRegistryRuleDTO>();
    let duplicates = 0;
    for (const agent of agents) {
      const key = `${agent.provider}::${agent.capability}::${agent.allowed_scope ?? ""}::${agent.allowed_project_id ?? ""}`;
      const existing = groups.get(key);
      if (!existing) {
        groups.set(key, agent);
        continue;
      }
      duplicates += 1;
      // enabled 优先；同为 enabled/disabled 时保留先出现的（更早登记）。
      if (!existing.enabled && agent.enabled) {
        groups.set(key, agent);
      }
    }
    return {
      dedupedAgents: Array.from(groups.values()),
      hasDuplicates: duplicates > 0,
    };
  }, [agents]);

  const saveRule = useCallback(
    async (rule: PermissionRuleDTO, patch: { value_number?: number; value_bool?: boolean }) => {
      if (savingId) return;
      setSavingId(rule.rule_id);
      setRowErrors((current) => ({ ...current, [rule.rule_id]: "" }));
      try {
        const updated = await updatePermissionRule(rule.rule_id, patch);
        setRules((current) =>
          current.map((item) => (item.rule_id === rule.rule_id ? updated : item)),
        );
        setEditingId(null);
      } catch (reason) {
        setRowErrors((current) => ({
          ...current,
          [rule.rule_id]:
            reason instanceof ApiError && reason.status === 403
              ? "当前身份不能修改该规则。"
              : "规则保存失败，请重试。",
        }));
      } finally {
        setSavingId(null);
      }
    },
    [savingId],
  );

  const toggleAgent = useCallback(
    async (agent: AgentRegistryRuleDTO) => {
      if (savingId) return;
      setSavingId(agent.id);
      setRowErrors((current) => ({ ...current, [agent.id]: "" }));
      try {
        const updated = await setAgentRegistryEnabled(agent.id, !agent.enabled);
        setAgents((current) => current.map((item) => (item.id === agent.id ? updated : item)));
      } catch (reason) {
        setRowErrors((current) => ({
          ...current,
          [agent.id]:
            reason instanceof ApiError && reason.status === 403
              ? "当前身份不能修改白名单。"
              : "白名单状态保存失败，请重试。",
        }));
      } finally {
        setSavingId(null);
      }
    },
    [savingId],
  );

  return (
    <ProductPage className="gp-page permissions89-page">
      <PageHeader
        eyebrow="身份与权限治理"
        title="权限规则"
        description="维护知识流转规则与外部助手接入状态，所有修改仍由服务端权限校验。"
      />
      <div className="gp-governance-console">
        <aside className="gp-summary-panel" aria-label="权限规则摘要">
          <div className="gp-summary-heading">
            <span className="gp-summary-heading-icon">
              <ShieldCheck size={16} />
            </span>
            规则概览
          </div>
          <div className="gp-summary-list">
            <div className="gp-summary-item">
              <span className="gp-summary-copy">
                <span className="gp-summary-icon">
                  <Layers3 size={14} />
                </span>
                <span className="gp-summary-label">规则总数</span>
              </span>
              <strong className="gp-summary-value">{rules.length}</strong>
            </div>
            <div className="gp-summary-item is-success">
              <span className="gp-summary-copy">
                <span className="gp-summary-icon">
                  <CircleCheck size={14} />
                </span>
                <span className="gp-summary-label">启用规则</span>
              </span>
              <strong className="gp-summary-value">{enabledRules}</strong>
            </div>
            <div className="gp-summary-item is-muted">
              <span className="gp-summary-copy">
                <span className="gp-summary-icon">
                  <CircleOff size={14} />
                </span>
                <span className="gp-summary-label">停用规则</span>
              </span>
              <strong className="gp-summary-value">{rules.length - enabledRules}</strong>
            </div>
            <div className="gp-summary-item is-agent">
              <span className="gp-summary-copy">
                <span className="gp-summary-icon">
                  <Bot size={14} />
                </span>
                <span className="gp-summary-label">启用助手</span>
              </span>
              <strong className="gp-summary-value">
                {dedupedAgents.filter((item) => item.enabled).length}
              </strong>
            </div>
          </div>
        </aside>

        <main className="gp-main-workspace">
          {!loading && !error && (
            <div className={`gp-access-note ${canEditRules ? "is-edit" : "is-readonly"}`}>
              {canEditRules
                ? "当前身份可修改业务权限规则。"
                : "当前身份为只读模式，规则修改需总经理或咨询总监权限。"}
            </div>
          )}
          {error && (
            <div className="gp-banner is-error" role="alert">
              {error}
            </div>
          )}
          <PageSection
            title={
              <span className="gp-section-title">
                <ShieldCheck size={17} />
                权限规则列表
              </span>
            }
            description="编辑仅影响当前规则，其他行保持可用。"
            className="gp-panel gp-primary-panel"
          >
            <PageToolbar
              className="gp-toolbar"
              start={
                <label className="gp-filter">
                  <SlidersHorizontal size={14} />
                  规则分组
                  <select
                    aria-label="规则分组"
                    value={groupFilter}
                    onChange={(event) => setGroupFilter(event.target.value)}
                  >
                    <option value="">全部分组</option>
                    {groups.map((group) => (
                      <option value={group} key={group}>
                        {groupLabel[group] ?? "其他治理规则"}
                      </option>
                    ))}
                  </select>
                </label>
              }
              end={
                <div className="gp-toolbar-actions">
                  <span>共 {visibleRules.length} 条</span>
                  <button className="btn-small" onClick={() => void load()} disabled={loading}>
                    <RefreshCw size={13} />
                    {loading ? "刷新中…" : "刷新"}
                  </button>
                </div>
              }
            />
            <div className="gp-table-wrap">
              <table className="gp-table">
                <thead>
                  <tr>
                    <th>规则</th>
                    <th>分组</th>
                    <th>当前设置</th>
                    <th className="gp-secondary-col">说明</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRules.map((rule) => (
                    <tr key={rule.rule_id}>
                      <td>
                        <span className="gp-row-title-mark">
                          <span className="gp-row-icon">
                            {rule.rule_type === "numeric" ? (
                              <Hash size={14} />
                            ) : rule.rule_type === "toggle" ? (
                              <ToggleLeft size={14} />
                            ) : (
                              <LockKeyhole size={14} />
                            )}
                          </span>
                          <strong>{rule.display_name}</strong>
                        </span>
                        <span className="gp-subline">
                          {ruleTypeLabel[rule.rule_type] ?? "治理规则"}
                        </span>
                      </td>
                      <td>
                        <span className="gp-field-mark">
                          <Layers3 size={13} />
                          {groupLabel[rule.rule_group] ?? "其他治理规则"}
                        </span>
                      </td>
                      <td>
                        {editingId === rule.rule_id && rule.rule_type === "numeric" ? (
                          <span className="gp-inline-edit">
                            <input
                              aria-label={`${rule.display_name}数值`}
                              type="number"
                              min={0}
                              value={editValue}
                              onChange={(event) =>
                                setEditValue(Math.max(0, Number(event.target.value)))
                              }
                            />
                            <span>{rule.unit ?? ""}</span>
                          </span>
                        ) : (
                          <span
                            className={`gp-status ${rule.rule_type === "toggle" && rule.value_bool ? "is-on" : ""}`}
                          >
                            <SlidersHorizontal size={12} />
                            {valueText(rule)}
                          </span>
                        )}
                        {rowErrors[rule.rule_id] && (
                          <span className="gp-row-error" role="alert">
                            {rowErrors[rule.rule_id]}
                          </span>
                        )}
                      </td>
                      <td className="gp-secondary-col">
                        {rule.description ?? "该规则暂无补充说明"}
                        {rule.updated_by_name && (
                          <span className="gp-subline">
                            最近修改：{rule.updated_by_name} · {formatBeijingTime(rule.updated_at)}
                          </span>
                        )}
                      </td>
                      <td>
                        <div className="gp-row-actions">
                          {!rule.editable ? (
                            <span className="gp-muted">系统固定</span>
                          ) : !canEditRules ? (
                            <span className="gp-muted">只读</span>
                          ) : editingId === rule.rule_id ? (
                            <>
                              <button
                                className="btn-small btn-small-primary"
                                disabled={savingId === rule.rule_id}
                                onClick={() => void saveRule(rule, { value_number: editValue })}
                              >
                                {savingId === rule.rule_id ? "保存中…" : "保存"}
                              </button>
                              <button className="btn-small" onClick={() => setEditingId(null)}>
                                取消
                              </button>
                            </>
                          ) : rule.rule_type === "toggle" ? (
                            <button
                              className="btn-small"
                              disabled={savingId === rule.rule_id}
                              onClick={() => void saveRule(rule, { value_bool: !rule.value_bool })}
                            >
                              {savingId === rule.rule_id
                                ? "保存中…"
                                : rule.value_bool
                                  ? "停用"
                                  : "启用"}
                            </button>
                          ) : (
                            <button
                              className="btn-small"
                              onClick={() => {
                                setEditingId(rule.rule_id);
                                setEditValue(rule.value_number ?? 0);
                              }}
                            >
                              编辑
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {!loading && visibleRules.length === 0 && (
                    <tr>
                      <td colSpan={5} className="gp-empty">
                        <div className="gp-empty-content">
                          <div className="gp-empty-visual" aria-hidden="true">
                            <ShieldCheck size={22} />
                            <span />
                          </div>
                          <strong>暂无符合条件的权限规则</strong>
                          <span>可调整规则分组，或重新读取服务端规则。</span>
                          <button className="btn-small" onClick={() => void load()}>
                            <RefreshCw size={13} />
                            重新加载
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
                  {loading && (
                    <tr>
                      <td colSpan={5} className="gp-empty">
                        正在加载权限规则…
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </PageSection>
          <PageSection
            title={
              <span className="gp-section-title">
                <Bot size={17} />
                外部助手白名单
              </span>
            }
            description="仅展示已登记助手的业务名称、能力范围和状态。"
            className="gp-panel gp-secondary-panel"
          >
            {agentError && <div className="gp-banner is-readonly">{agentError}</div>}
            {hasDuplicates && !agentError && (
              <div className="gp-banner is-readonly" role="status">
                检测到重复配置，已自动去重展示。
              </div>
            )}
            <div className="gp-table-wrap">
              <table className="gp-table">
                <thead>
                  <tr>
                    <th>助手名称</th>
                    <th>能力</th>
                    <th>范围</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {dedupedAgents.map((agent) => (
                    <tr key={agent.id}>
                      <td>
                        <span className="gp-row-title-mark">
                          <span className="gp-row-icon is-agent">
                            <Bot size={14} />
                          </span>
                          <strong>{agent.agent_name}</strong>
                        </span>
                      </td>
                      <td>
                        <span className="gp-field-mark">
                          <Search size={13} />
                          {capabilityLabel[agent.capability] ?? "已登记能力"}
                        </span>
                      </td>
                      <td>
                        <span className="gp-field-mark">
                          <BriefcaseBusiness size={13} />
                          {agent.allowed_scope
                            ? (scopeLabel[agent.allowed_scope] ?? "受限范围")
                            : "全部允许范围"}
                        </span>
                      </td>
                      <td>
                        <span className={`gp-status ${agent.enabled ? "is-on" : ""}`}>
                          {agent.enabled ? <CircleCheck size={12} /> : <CircleOff size={12} />}
                          {agent.enabled ? "已启用" : "已停用"}
                        </span>
                        {rowErrors[agent.id] && (
                          <span className="gp-row-error" role="alert">
                            {rowErrors[agent.id]}
                          </span>
                        )}
                      </td>
                      <td>
                        {isAdmin ? (
                          <button
                            className="btn-small"
                            disabled={savingId === agent.id}
                            onClick={() => void toggleAgent(agent)}
                          >
                            {savingId === agent.id ? "保存中…" : agent.enabled ? "停用" : "启用"}
                          </button>
                        ) : (
                          <span className="gp-muted">只读</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {!loading && !agentError && dedupedAgents.length === 0 && (
                    <tr>
                      <td colSpan={5} className="gp-empty">
                        <div className="gp-empty-content">
                          <div className="gp-empty-visual is-agent" aria-hidden="true">
                            <Bot size={22} />
                            <span />
                          </div>
                          <strong>暂无已登记的外部助手</strong>
                          <span>白名单为空，可重新读取服务端登记状态。</span>
                          <button className="btn-small" onClick={() => void load()}>
                            <RefreshCw size={13} />
                            重新加载
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </PageSection>
        </main>
      </div>
    </ProductPage>
  );
}
