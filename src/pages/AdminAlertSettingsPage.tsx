import { AlertHistoryButton } from "../components/operations/ReadTools";
import TaskModal from "../components/TaskModal";
import CollectionWorkspace from "../components/CollectionWorkspace";
import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, SlidersHorizontal } from "lucide-react";
import { fetchAlertRules, updateAlertRule } from "../api/admin";
import { ApiError } from "../api/http";
import { PageHeader, PageSection, PageToolbar, ProductPage } from "../components/ProductLayout";
import type { AlertRuleDTO } from "../types/alert";
import { formatBeijingTime } from "../utils/time";
import "./AdminAlertSettingsPage.css";

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
  const [editingIds, setEditingIds] = useState<Set<string>>(new Set());
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
      setEditingIds(new Set());
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
      rules
        .filter(
          (rule) =>
            (!filterLevel || rule.severity === filterLevel) &&
            (!filterEnabled || (filterEnabled === "enabled" ? rule.enabled : !rule.enabled)),
        )
        .sort((left, right) => {
          const priority: Record<string, number> = { critical: 0, error: 1, warning: 2 };
          return (priority[left.severity] ?? 3) - (priority[right.severity] ?? 3);
        }),
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
        if (patch.threshold !== undefined)
          setEditingIds((current) => {
            const next = new Set(current);
            next.delete(rule.id);
            return next;
          });
        setDrafts((current) => ({ ...current, [rule.id]: String(updated.threshold ?? "") }));
      } catch (reason) {
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
        setRowErrors((current) => ({ ...current, [rule.id]: "阈值必须是不小于 1 的数字。" }));
        return;
      }
      if (value !== rule.threshold) void saveRule(rule, { threshold: value });
      else
        setEditingIds((current) => {
          const next = new Set(current);
          next.delete(rule.id);
          return next;
        });
    },
    [drafts, saveRule],
  );

  const editingRule = rules.find((rule) => editingIds.has(rule.id));
  const cancelEdit = () => {
    if (!editingRule || saving.has(editingRule.id)) return;
    setDrafts((current) => ({ ...current, [editingRule.id]: String(editingRule.threshold ?? "") }));
    setRowErrors((current) => ({ ...current, [editingRule.id]: "" }));
    setEditingIds(new Set());
  };

  return (
    <ProductPage className="secops-page alert-settings-page admin-control-page">
      <PageHeader
        title="告警设置"
        actions={<AlertHistoryButton />}
        description="管理触发阈值与通知状态。规则级别代表告警严重程度，不表示当前发生了故障。"
      />
      <div className="secops-console">
        <main className="secops-main-workspace">
          {error && (
            <div className="secops-banner is-error" role="alert">
              {error}
            </div>
          )}
          <PageSection className="secops-workspace secops-primary-section">
            <CollectionWorkspace
              filters={
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
                      <button
                        className="btn-small"
                        onClick={() => void load()}
                        disabled={loading || saving.size > 0 || editingIds.size > 0}
                      >
                        <RefreshCw size={13} aria-hidden="true" /> {loading ? "刷新中…" : "刷新"}
                      </button>
                    </div>
                  }
                />
              }
            >
              <div className="secops-table-wrap">
                <table data-responsive-table className="secops-table">
                  <thead>
                    <tr>
                      <th className="alert-severity-column">级别</th>
                      <th>规则名称</th>
                      <th className="alert-threshold-column">阈值</th>
                      <th className="alert-status-column">状态</th>
                      <th className="alert-action-column">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRules.map((rule) => (
                      <tr key={rule.id} className={!rule.enabled ? "is-disabled" : undefined}>
                        <td data-label="级别">
                          <span className={`secops-pill severity-${rule.severity}`}>
                            {severityLabel[rule.severity] ?? "未分级"}
                          </span>
                        </td>
                        <td data-label="规则名称" className="secops-primary">
                          {rule.rule_name}
                          <details className="admin-row-details">
                            <summary>通知与更新时间</summary>
                            <p>
                              通知渠道：
                              {rule.notification_channels
                                .map((channel) => channelLabel[channel] ?? "其他渠道")
                                .join("、") || "未设置"}
                            </p>
                            <p>防重复：{dedupLabel[rule.dedup_strategy ?? ""] ?? "按规则合并"}</p>
                            <small>更新时间：{formatBeijingTime(rule.updated_at)}</small>
                          </details>
                        </td>
                        <td data-label="阈值">
                          <div className="secops-threshold">
                            <div className="alert-threshold-value">
                              <span>{rule.threshold ?? "—"}</span>
                              <span>{rule.threshold_unit ?? ""}</span>
                            </div>
                          </div>
                          {rowErrors[rule.id] && !editingIds.has(rule.id) && (
                            <span className="secops-row-error" role="alert">
                              {rowErrors[rule.id]}
                            </span>
                          )}
                        </td>
                        <td data-label="状态" className="alert-status-cell">
                          <button
                            className={`secops-toggle ${rule.enabled ? "is-on" : ""}`}
                            aria-label={`${rule.rule_name}${rule.enabled ? "停用" : "启用"}`}
                            aria-pressed={rule.enabled}
                            disabled={loading || saving.size > 0 || editingIds.size > 0}
                            onClick={() => void saveRule(rule, { enabled: !rule.enabled })}
                          >
                            {saving.has(rule.id) ? "保存中…" : rule.enabled ? "已启用" : "已停用"}
                          </button>
                        </td>
                        <td data-label="操作" className="alert-action-cell">
                          <button
                            className="btn-small"
                            aria-label={`编辑${rule.rule_name}阈值`}
                            disabled={loading || saving.size > 0 || editingIds.size > 0}
                            onClick={() => {
                              setDrafts((current) => ({
                                ...current,
                                [rule.id]: String(rule.threshold ?? ""),
                              }));
                              setRowErrors((current) => ({ ...current, [rule.id]: "" }));
                              setEditingIds(new Set([rule.id]));
                            }}
                          >
                            编辑
                          </button>
                        </td>
                      </tr>
                    ))}
                    {!loading && !error && filteredRules.length === 0 && (
                      <tr>
                        <td colSpan={5} className="secops-empty">
                          暂无符合条件的告警规则
                        </td>
                      </tr>
                    )}
                    {loading && (
                      <tr>
                        <td colSpan={5} className="secops-empty">
                          正在加载告警规则…
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CollectionWorkspace>
          </PageSection>
        </main>
      </div>
      <TaskModal
        portal
        open={Boolean(editingRule)}
        title="编辑告警阈值"
        description={editingRule?.rule_name}
        size="small"
        onClose={cancelEdit}
        busy={Boolean(editingRule && saving.has(editingRule.id))}
        footer={
          editingRule && (
            <div
              className="alert-rule-editor-actions"
              role="group"
              aria-label={`${editingRule.rule_name}阈值操作`}
            >
              <button
                className="product-button is-secondary"
                disabled={saving.has(editingRule.id)}
                onClick={cancelEdit}
              >
                取消
              </button>
              <button
                className="product-button is-primary"
                disabled={saving.has(editingRule.id)}
                onClick={() => commitThreshold(editingRule)}
              >
                {saving.has(editingRule.id) ? "保存中…" : "保存阈值"}
              </button>
            </div>
          )
        }
      >
        {editingRule && (
          <div className="alert-rule-editor">
            <label>
              触发阈值
              <div className="alert-rule-editor-input">
                <input
                  aria-label={`${editingRule.rule_name}阈值`}
                  type="number"
                  min={1}
                  value={drafts[editingRule.id] ?? ""}
                  disabled={saving.has(editingRule.id)}
                  onChange={(event) =>
                    setDrafts((current) => ({ ...current, [editingRule.id]: event.target.value }))
                  }
                />
                <span>{editingRule.threshold_unit ?? ""}</span>
              </div>
            </label>
            <p>保存后按新阈值执行此规则，通知渠道和启用状态保持当前设置。</p>
            {rowErrors[editingRule.id] && (
              <p className="secops-row-error" role="alert">
                {rowErrors[editingRule.id]}
              </p>
            )}
          </div>
        )}
      </TaskModal>
    </ProductPage>
  );
}
