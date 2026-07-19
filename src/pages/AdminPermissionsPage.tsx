import { useCallback, useEffect, useMemo, useState } from "react";
import { Bot, RefreshCw, ShieldCheck, SlidersHorizontal } from "lucide-react";
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
        me.companyRoles.includes("boss") || me.companyRoles.includes("consulting_director"),
      );
      setIsAdmin(me.companyRoles.includes("admin"));
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
      <div className="gp-summary" aria-label="权限规则摘要">
        <span>
          <strong>{rules.length}</strong>规则总数
        </span>
        <span>
          <strong>{enabledRules}</strong>启用规则
        </span>
        <span>
          <strong>{rules.length - enabledRules}</strong>停用规则
        </span>
        <span>
          <strong>{agents.filter((item) => item.enabled).length}</strong>启用助手
        </span>
      </div>
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
                    <strong>{rule.display_name}</strong>
                    <span className="gp-subline">
                      {ruleTypeLabel[rule.rule_type] ?? "治理规则"}
                    </span>
                  </td>
                  <td>{groupLabel[rule.rule_group] ?? "其他治理规则"}</td>
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
                    暂无符合条件的权限规则
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
              {agents.map((agent) => (
                <tr key={agent.id}>
                  <td>
                    <strong>{agent.agent_name}</strong>
                  </td>
                  <td>{capabilityLabel[agent.capability] ?? "已登记能力"}</td>
                  <td>
                    {agent.allowed_scope
                      ? (scopeLabel[agent.allowed_scope] ?? "受限范围")
                      : "全部允许范围"}
                  </td>
                  <td>
                    <span className={`gp-status ${agent.enabled ? "is-on" : ""}`}>
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
              {!loading && !agentError && agents.length === 0 && (
                <tr>
                  <td colSpan={5} className="gp-empty">
                    暂无已登记的外部助手
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </PageSection>
    </ProductPage>
  );
}
