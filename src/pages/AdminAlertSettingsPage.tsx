import { useCallback, useEffect, useMemo, useState } from "react";
import { BellRing, RefreshCw, ShieldCheck, Siren, SlidersHorizontal } from "lucide-react";
import { fetchAlertRules, updateAlertRule } from "../api/admin";
import { ApiError } from "../api/http";
import {
  PageHeader,
  OperationsSummary,
  PageSection,
  PageToolbar,
  ProductPage,
} from "../components/ProductLayout";
import type { AlertRuleDTO } from "../types/alert";
import { formatBeijingTime } from "../utils/time";

const severityLabel: Record<string, string> = { critical: "严重", error: "错误", warning: "警告" };
const channelLabel: Record<string, string> = {
  in_app: "站内通知",
  wecom: "企业微信",
  email: "邮件",
};
const dedupLabel: Record<string, string> = {
  none: "不合并",
  cooldown: "冷却期内合并",
  daily: "每日合并",
};

export default function AdminAlertSettingsPage() {
  const [rules, setRules] = useState<AlertRuleDTO[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<Set<string>>(new Set());
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterLevel, setFilterLevel] = useState("");
  const [filterEnabled, setFilterEnabled] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const ruleResponse = await fetchAlertRules();
      setRules(ruleResponse.items);
      setDrafts(
        Object.fromEntries(
          ruleResponse.items.map((rule) => [rule.id, String(rule.threshold ?? "")]),
        ),
      );
      setRowErrors({});
    } catch (reason) {
      setRules([]);
      setError(
        reason instanceof ApiError && reason.status === 403
          ? "当前身份没有告警设置查看权限。"
          : "告警设置暂时无法加载，请稍后重试。",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => void load(), [load]);

  const filteredRules = useMemo(
    () =>
      rules.filter(
        (rule) =>
          (!filterLevel || rule.severity === filterLevel) &&
          (!filterEnabled || (filterEnabled === "enabled" ? rule.enabled : !rule.enabled)),
      ),
    [filterEnabled, filterLevel, rules],
  );

  const saveRule = useCallback(
    async (rule: AlertRuleDTO, patch: { enabled?: boolean; threshold?: number }) => {
      if (saving.has(rule.id)) return;
      setSaving((current) => new Set(current).add(rule.id));
      setRowErrors((current) => ({ ...current, [rule.id]: "" }));
      try {
        const updated = await updateAlertRule(rule.id, patch);
        setRules((current) => current.map((item) => (item.id === rule.id ? updated : item)));
        setDrafts((current) => ({ ...current, [rule.id]: String(updated.threshold ?? "") }));
      } catch (reason) {
        setDrafts((current) => ({ ...current, [rule.id]: String(rule.threshold ?? "") }));
        setRowErrors((current) => ({
          ...current,
          [rule.id]:
            reason instanceof ApiError && reason.status === 403
              ? "当前身份不能修改该规则。"
              : "保存失败，请重试。",
        }));
      } finally {
        setSaving((current) => {
          const next = new Set(current);
          next.delete(rule.id);
          return next;
        });
      }
    },
    [saving],
  );

  const commitThreshold = useCallback(
    (rule: AlertRuleDTO) => {
      const value = Number(drafts[rule.id]);
      if (!Number.isFinite(value) || value < 1) {
        setDrafts((current) => ({ ...current, [rule.id]: String(rule.threshold ?? "") }));
        setRowErrors((current) => ({ ...current, [rule.id]: "阈值必须是不小于 1 的数字。" }));
        return;
      }
      if (value !== rule.threshold) void saveRule(rule, { threshold: value });
    },
    [drafts, saveRule],
  );

  const enabledCount = rules.filter((rule) => rule.enabled).length;
  const criticalCount = rules.filter((rule) => rule.severity === "critical").length;
  return (
    <ProductPage className="secops-page alert-settings-page admin-control-page">
      <PageHeader
        eyebrow="安全运营"
        title="告警设置"
        description="维护安全告警触发条件与通知渠道。"
      />
      <div className="secops-console">
        <OperationsSummary
          label="告警摘要"
          titleIcon={<ShieldCheck size={15} aria-hidden="true" />}
          items={[
            {
              label: "启用规则",
              value: enabledCount,
              tone: "success",
              icon: <BellRing size={14} />,
            },
            { label: "严重规则", value: criticalCount, tone: "danger", icon: <Siren size={14} /> },
          ]}
        />
        <main className="secops-main-workspace">
          {error && (
            <div className="secops-banner is-error" role="alert">
              {error}
            </div>
          )}
          <PageSection
            title={
              <span className="secops-section-title">
                <span className="secops-workspace-heading-icon">
                  <Siren size={16} />
                </span>
                告警规则
              </span>
            }
            description="修改仅作用于当前规则，保存期间其他规则仍可查看。"
            className="secops-workspace secops-primary-section"
          >
            <PageToolbar
              className="secops-toolbar"
              start={
                <div className="secops-filters">
                  <SlidersHorizontal size={14} aria-hidden="true" />
                  <label>
                    级别
                    <select
                      aria-label="规则级别"
                      value={filterLevel}
                      onChange={(event) => setFilterLevel(event.target.value)}
                    >
                      <option value="">全部</option>
                      <option value="critical">严重</option>
                      <option value="error">错误</option>
                      <option value="warning">警告</option>
                    </select>
                  </label>
                  <label>
                    状态
                    <select
                      aria-label="规则状态"
                      value={filterEnabled}
                      onChange={(event) => setFilterEnabled(event.target.value)}
                    >
                      <option value="">全部</option>
                      <option value="enabled">已启用</option>
                      <option value="disabled">已停用</option>
                    </select>
                  </label>
                </div>
              }
              end={
                <div className="secops-toolbar-actions">
                  <span className="secops-count">共 {filteredRules.length} 条规则</span>
                  <button className="btn-small" onClick={() => void load()} disabled={loading}>
                    <RefreshCw size={13} aria-hidden="true" /> {loading ? "刷新中…" : "刷新"}
                  </button>
                </div>
              }
            />
            <div className="secops-table-wrap">
              <table className="secops-table">
                <thead>
                  <tr>
                    <th>级别</th>
                    <th>规则名称</th>
                    <th>阈值</th>
                    <th className="secops-col-secondary">通知渠道</th>
                    <th className="secops-col-secondary">防重复</th>
                    <th className="secops-col-secondary">更新时间</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRules.map((rule) => (
                    <tr key={rule.id} className={!rule.enabled ? "is-disabled" : ""}>
                      <td>
                        <span className={`secops-pill severity-${rule.severity}`}>
                          {severityLabel[rule.severity] ?? "未分级"}
                        </span>
                      </td>
                      <td className="secops-primary">{rule.rule_name}</td>
                      <td>
                        <div className="secops-threshold">
                          <input
                            aria-label={`${rule.rule_name}阈值`}
                            type="number"
                            min={1}
                            value={drafts[rule.id] ?? ""}
                            disabled={saving.has(rule.id)}
                            onChange={(event) =>
                              setDrafts((current) => ({
                                ...current,
                                [rule.id]: event.target.value,
                              }))
                            }
                            onBlur={() => commitThreshold(rule)}
                          />
                          <span>{rule.threshold_unit ?? ""}</span>
                        </div>
                        {rowErrors[rule.id] && (
                          <span className="secops-row-error" role="alert">
                            {rowErrors[rule.id]}
                          </span>
                        )}
                      </td>
                      <td className="secops-col-secondary">
                        {rule.notification_channels.map((channel) => (
                          <span className="secops-channel" key={channel}>
                            {channelLabel[channel] ?? "其他渠道"}
                          </span>
                        ))}
                      </td>
                      <td className="secops-col-secondary">
                        {dedupLabel[rule.dedup_strategy ?? ""] ?? "按规则合并"}
                      </td>
                      <td className="secops-time secops-col-secondary">
                        {formatBeijingTime(rule.updated_at)}
                      </td>
                      <td>
                        <button
                          className={`secops-toggle ${rule.enabled ? "is-on" : ""}`}
                          aria-label={`${rule.rule_name}${rule.enabled ? "停用" : "启用"}`}
                          aria-pressed={rule.enabled}
                          disabled={saving.has(rule.id)}
                          onClick={() => void saveRule(rule, { enabled: !rule.enabled })}
                        >
                          {saving.has(rule.id) ? "保存中…" : rule.enabled ? "已启用" : "已停用"}
                        </button>
                      </td>
                    </tr>
                  ))}
                  {!loading && filteredRules.length === 0 && (
                    <tr>
                      <td colSpan={7} className="secops-empty">
                        暂无符合条件的告警规则
                      </td>
                    </tr>
                  )}
                  {loading && (
                    <tr>
                      <td colSpan={7} className="secops-empty">
                        正在加载告警规则…
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
