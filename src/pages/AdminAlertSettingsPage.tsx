import { useState, useMemo, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/http";
import { fetchAlertNotifications, fetchAlertRules, updateAlertRule } from "../api/admin";
import type { AlertRuleDTO, NotificationDTO } from "../types/alert";
import { formatBeijingTime } from "../utils/time";

const levelLabel: Record<string, string> = {
  critical: "Critical",
  error: "Error",
  warning: "Warning",
};

const levelCls: Record<string, string> = {
  critical: "al-level-critical",
  error: "al-level-error",
  warning: "al-level-warning",
};

const statusLabel: Record<string, string> = {
  pending: "待发送",
  sent: "已发送",
  failed: "发送失败",
};

// 用户可见时间统一北京时间。
const fmtTime = (iso: string): string => formatBeijingTime(iso);

export default function AdminAlertSettingsPage() {
  const [rules, setRules] = useState<AlertRuleDTO[]>([]);
  const [notifications, setNotifications] = useState<NotificationDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterLevel, setFilterLevel] = useState("");
  const [filterEnabled, setFilterEnabled] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [rulesData, notifData] = await Promise.all([
        fetchAlertRules(),
        fetchAlertNotifications(),
      ]);
      setRules(rulesData.items);
      setNotifications(notifData.items);
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? `${e.message}（${e.deniedReason ?? e.status}）`
          : "告警设置加载失败";
      setError(msg);
      setRules([]);
      setNotifications([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const enabledCount = useMemo(() => rules.filter((r) => r.enabled).length, [rules]);
  const criticalCount = useMemo(
    () => rules.filter((r) => r.severity === "critical").length,
    [rules],
  );
  const pendingNotif = useMemo(
    () => notifications.filter((n) => n.send_status === "pending").length,
    [notifications],
  );

  const filtered = useMemo(() => {
    let result = rules;
    if (filterLevel) result = result.filter((r) => r.severity === filterLevel);
    if (filterEnabled === "enabled") result = result.filter((r) => r.enabled);
    if (filterEnabled === "disabled") result = result.filter((r) => !r.enabled);
    return result;
  }, [rules, filterLevel, filterEnabled]);

  const patchRule = useCallback(
    async (id: string, patch: { enabled?: boolean; threshold?: number }) => {
      try {
        const updated = await updateAlertRule(id, patch);
        setRules((prev) => prev.map((r) => (r.id === id ? updated : r)));
      } catch (e) {
        const msg =
          e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "更新失败";
        setError(msg);
      }
    },
    [],
  );

  return (
    <div className="alert-settings-page">
      {/* Header + KPI */}
      <div className="al-header">
        <div className="al-header-text">
          <h2>告警设置</h2>
          <p>
            配置归档阈值与运维信号（索引失败/解析停滞/登录安全）告警规则、通知渠道 ·
            经平台权限网关按 admin 角色返回
          </p>
        </div>
        <div className="kl-kpis">
          <div className="kl-kpi">
            <div className="kl-kpi-value kl-kpi-success">{enabledCount}</div>
            <div className="kl-kpi-label">启用规则</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value al-kpi-crit">{criticalCount}</div>
            <div className="kl-kpi-label">Critical 规则</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value">{notifications.length}</div>
            <div className="kl-kpi-label">通知记录</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value kl-kpi-warning">{pendingNotif}</div>
            <div className="kl-kpi-label">待发送</div>
          </div>
        </div>
      </div>

      {/* 错误态：非授权角色显示后端业务原因 */}
      {error && (
        <div className="au-error-banner">
          <strong>无法加载告警设置</strong>
          <p>{error}</p>
          <p className="au-error-hint">
            告警设置仅对 admin 开放。可通过 <code>VITE_DEV_USER_ID</code> 切换为 admin 身份查看。
          </p>
        </div>
      )}

      {/* Rule list */}
      <section className="al-section">
        <h3>告警规则</h3>
        <div className="al-toolbar">
          <div className="al-toolbar-filters">
            <select value={filterLevel} onChange={(e) => setFilterLevel(e.target.value)}>
              <option value="">全部级别</option>
              <option value="critical">Critical</option>
              <option value="error">Error</option>
              <option value="warning">Warning</option>
            </select>
            <select value={filterEnabled} onChange={(e) => setFilterEnabled(e.target.value)}>
              <option value="">全部状态</option>
              <option value="enabled">已启用</option>
              <option value="disabled">已停用</option>
            </select>
          </div>
          <div className="al-toolbar-right">
            <span className="al-toolbar-hint">共 {filtered.length} 条规则</span>
            <button className="btn-small" onClick={() => void load()} disabled={loading}>
              {loading ? "加载中…" : "刷新"}
            </button>
          </div>
        </div>
        <div className="ingest-table-wrap">
          <table className="ingest-table">
            <thead>
              <tr>
                <th>级别</th>
                <th>规则名称</th>
                <th>阈值</th>
                <th>通知渠道</th>
                <th>防重复</th>
                <th>更新时间</th>
                <th>启用</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} className={r.enabled ? "" : "al-row-disabled"}>
                  <td>
                    <span className={`al-level-pill ${levelCls[r.severity] ?? ""}`}>
                      {levelLabel[r.severity] ?? r.severity}
                    </span>
                  </td>
                  <td className="al-cell-metric">{r.rule_name}</td>
                  <td className="al-cell-threshold">
                    <input
                      type="number"
                      className="al-threshold-input"
                      value={r.threshold ?? 0}
                      min={1}
                      onChange={(e) =>
                        patchRule(r.id, { threshold: Math.max(1, Number(e.target.value)) })
                      }
                    />
                    <span className="al-threshold-unit">{r.threshold_unit ?? ""}</span>
                  </td>
                  <td className="al-cell-channels">
                    {r.notification_channels.map((ch) => (
                      <span key={ch} className="al-channel-tag">
                        {ch}
                      </span>
                    ))}
                  </td>
                  <td className="al-cell-cooldown">{r.dedup_strategy ?? "—"}</td>
                  <td className="cell-time">{fmtTime(r.updated_at)}</td>
                  <td>
                    <button
                      className={`al-toggle ${r.enabled ? "al-toggle-on" : "al-toggle-off"}`}
                      onClick={() => patchRule(r.id, { enabled: !r.enabled })}
                    >
                      {r.enabled ? "启用" : "停用"}
                    </button>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && !loading && (
                <tr>
                  <td colSpan={7} className="au-empty-cell">
                    暂无告警规则
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Notification records */}
      <section className="al-section">
        <h3>通知记录</h3>
        <div className="ingest-table-wrap">
          <table className="ingest-table">
            <thead>
              <tr>
                <th>标题</th>
                <th>接收人</th>
                <th>渠道</th>
                <th>状态</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {notifications.map((n) => (
                <tr key={n.id}>
                  <td className="al-cell-metric">{n.title}</td>
                  <td>{n.recipient_name ?? "—"}</td>
                  <td>
                    <span className="al-channel-tag">{n.channel}</span>
                  </td>
                  <td>{statusLabel[n.send_status] ?? n.send_status}</td>
                  <td className="cell-time">{fmtTime(n.created_at)}</td>
                </tr>
              ))}
              {notifications.length === 0 && !loading && (
                <tr>
                  <td colSpan={5} className="au-empty-cell">
                    暂无通知记录（生命周期归档 / 重新启用确认 / 运维告警信号会生成本地通知）
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="au-note">
          当前环境仅记录站内通知，<strong>未配置外部通知通道</strong>（邮件 / 企微 /
          webhook）；记录仅含安全元数据，新建状态恒为「待发送」。
        </p>
      </section>

      <p className="page-help-line">
        归档阈值与去重策略可调；企微通知真实下发受 <code>WECOM_NOTIFY_ENABLED</code>{" "}
        控制（默认仅本地 in_app）。详见{" "}
        <Link to="/help#admin" className="page-help-link">
          使用说明 →
        </Link>
      </p>
    </div>
  );
}
