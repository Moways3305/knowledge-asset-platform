import { useState, useMemo, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import { ApiError, fetchAudit, markAuditProcessed } from "../api/client";
import type { AuditEventDTO } from "../types/audit";
import { formatBeijingTime } from "../utils/time";
import {
  auditActionLabel,
  auditLoginSummary,
  auditSnapshotSummary,
  auditTargetTypeLabel,
} from "../utils/auditDisplay";

type LogTab = "operation" | "exception" | "login";

const tabLabel: Record<LogTab, string> = {
  operation: "操作日志",
  exception: "异常日志",
  login: "登录日志",
};

const severityLabel: Record<string, string> = {
  critical: "严重",
  error: "错误",
  warning: "警告",
};

const severityCls: Record<string, string> = {
  critical: "au-sev-critical",
  error: "au-sev-error",
  warning: "au-sev-warning",
};

const roleLabel: Record<string, string> = {
  boss: "Boss",
  consulting_director: "咨询总监",
  consultant: "顾问",
  admin: "管理员",
  project_manager: "项目经理",
  coach: "辅导老师",
};

export default function AdminAuditPage() {
  const [activeTab, setActiveTab] = useState<LogTab>("operation");
  const [events, setEvents] = useState<AuditEventDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<string>("");
  const [filterSeverity, setFilterSeverity] = useState("");
  const [filterResolved, setFilterResolved] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAudit({ pageSize: 200 });
      setEvents(data.items);
      setView(data.view);
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? `${e.message}（${e.deniedReason ?? e.status}）`
          : "审计日志加载失败";
      setError(msg);
      setEvents([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const operationLogs = useMemo(() => events.filter((e) => e.log_type === "operation"), [events]);
  const exceptionLogs = useMemo(() => events.filter((e) => e.log_type === "exception"), [events]);
  const loginLogs = useMemo(() => events.filter((e) => e.log_type === "login"), [events]);

  const unresolvedCount = useMemo(() => exceptionLogs.filter((e) => !e.is_processed).length, [exceptionLogs]);
  // 登录失败计数取自真实 login.failed 审计事件（企微 OAuth 会写入）。
  const loginFailedCount = useMemo(
    () => loginLogs.filter((e) => e.action === "login.failed").length,
    [loginLogs]
  );
  const critErrorCount = useMemo(
    () => exceptionLogs.filter((e) => e.severity === "critical" || e.severity === "error").length,
    [exceptionLogs]
  );

  const filteredExceptions = useMemo(() => {
    let result = exceptionLogs;
    if (filterSeverity) result = result.filter((e) => e.severity === filterSeverity);
    if (filterResolved === "resolved") result = result.filter((e) => e.is_processed);
    if (filterResolved === "unresolved") result = result.filter((e) => !e.is_processed);
    return result;
  }, [exceptionLogs, filterSeverity, filterResolved]);

  const handleMarkProcessed = useCallback(async (id: string) => {
    try {
      await markAuditProcessed(id);
      await load();
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "标记失败";
      setError(msg);
    }
  }, [load]);

  const roleText = (e: AuditEventDTO) =>
    roleLabel[e.actor_company_role ?? ""] ?? (e.actor_company_role || "—");

  return (
    <div className="audit-page">
      {/* Header + KPI */}
      <div className="au-header">
        <div className="au-header-text">
          <h2>审计日志</h2>
          <p>平台关键操作追踪、系统异常监控与登录安全审计 · 经平台权限网关按角色脱敏返回 · 时间均为北京时间（Asia/Shanghai）</p>
        </div>
        <div className="kl-kpis">
          <div className="kl-kpi">
            <div className="kl-kpi-value">{operationLogs.length}</div>
            <div className="kl-kpi-label">操作记录</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value kl-kpi-warning">{unresolvedCount}</div>
            <div className="kl-kpi-label">未处理异常</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value au-kpi-failed">{loginFailedCount}</div>
            <div className="kl-kpi-label">登录失败</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value au-kpi-crit">{critErrorCount}</div>
            <div className="kl-kpi-label">Critical/Error</div>
          </div>
        </div>
      </div>

      {/* 视图档位提示 */}
      {view && !error && (
        <div className="au-view-hint">
          当前审计视图：<strong>{view === "governance" ? "业务治理视图（Boss / 咨询总监）" : "系统元数据视图（admin，已对 L5 / 业务原文脱敏）"}</strong>
        </div>
      )}

      {/* 错误态：非授权角色显示后端业务原因 */}
      {error && (
        <div className="au-error-banner">
          <strong>无法加载审计日志</strong>
          <p>{error}</p>
          <p className="au-error-hint">审计查询仅对 admin / Boss / 咨询总监开放（普通业务用户无全局审计查询权）。可通过 <code>VITE_DEV_USER_ID</code> 切换为授权身份查看。</p>
        </div>
      )}

      {/* Tabs */}
      <div className="au-tabs">
        {(["operation", "exception", "login"] as LogTab[]).map((tab) => (
          <button
            key={tab}
            className={`au-tab ${activeTab === tab ? "active" : ""}`}
            onClick={() => setActiveTab(tab)}
          >
            {tabLabel[tab]}
          </button>
        ))}
        <div className="au-tabs-spacer" />
        <button className="btn-small" onClick={() => void load()} disabled={loading}>
          {loading ? "加载中…" : "刷新"}
        </button>
      </div>

      {/* Operation logs */}
      {activeTab === "operation" && (
        <section className="audit-section">
          <div className="au-toolbar">
            <span className="au-toolbar-hint">共 {operationLogs.length} 条操作记录</span>
          </div>
          <div className="ingest-table-wrap">
            <table className="ingest-table">
              <thead>
                <tr>
                  <th>操作</th>
                  <th>操作者</th>
                  <th>角色</th>
                  <th>对象类型</th>
                  <th>变更 / 结果</th>
                  <th>追踪 ID</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                {operationLogs.map((log) => (
                  <tr key={log.id}>
                    <td className="au-cell-action" title={log.action}>
                      {auditActionLabel(log.action)}
                      <span className="au-cell-raw">{log.action}</span>
                    </td>
                    <td>{log.actor_name ?? "—"}</td>
                    <td><span className="au-role-badge">{roleText(log)}</span></td>
                    <td className="au-cell-target" title={log.target_type ?? ""}>{auditTargetTypeLabel(log.target_type)}</td>
                    <td className="au-cell-state">{auditSnapshotSummary(log)}</td>
                    <td className="au-cell-trace" title={log.trace_id}>{log.trace_id}</td>
                    <td className="cell-time">{formatBeijingTime(log.created_at)}</td>
                  </tr>
                ))}
                {operationLogs.length === 0 && !loading && (
                  <tr><td colSpan={7} className="au-empty-cell">暂无操作日志</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Exception logs */}
      {activeTab === "exception" && (
        <section className="audit-section">
          <div className="au-toolbar">
            <div className="au-toolbar-filters">
              <select value={filterSeverity} onChange={(e) => setFilterSeverity(e.target.value)}>
                <option value="">全部级别</option>
                <option value="critical">严重</option>
                <option value="error">错误</option>
                <option value="warning">警告</option>
              </select>
              <select value={filterResolved} onChange={(e) => setFilterResolved(e.target.value)}>
                <option value="">全部状态</option>
                <option value="unresolved">未处理</option>
                <option value="resolved">已处理</option>
              </select>
            </div>
            <span className="au-toolbar-hint">共 {filteredExceptions.length} 条异常记录</span>
          </div>
          <div className="ingest-table-wrap">
            <table className="ingest-table">
              <thead>
                <tr>
                  <th>动作</th>
                  <th>级别</th>
                  <th>风险</th>
                  <th>对象类型</th>
                  <th>原因</th>
                  <th>追踪 ID</th>
                  <th>状态</th>
                  <th>时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredExceptions.map((log) => (
                  <tr key={log.id}>
                    <td className="au-cell-action" title={log.action}>
                      {auditActionLabel(log.action)}
                      <span className="au-cell-raw">{log.action}</span>
                    </td>
                    <td>
                      {log.severity ? (
                        <span className={`au-severity-pill ${severityCls[log.severity] ?? ""}`}>
                          {severityLabel[log.severity] ?? log.severity}
                        </span>
                      ) : "—"}
                    </td>
                    <td>{log.risk_level ?? "—"}</td>
                    <td className="au-cell-service" title={log.target_type ?? ""}>{auditTargetTypeLabel(log.target_type)}</td>
                    <td className="au-cell-msg">{log.denied_reason ?? "—"}</td>
                    <td className="au-cell-trace" title={log.trace_id}>{log.trace_id}</td>
                    <td>
                      <span className={`au-resolved-pill ${log.is_processed ? "au-resolved-yes" : "au-resolved-no"}`}>
                        {log.is_processed ? "已处理" : "未处理"}
                      </span>
                    </td>
                    <td className="cell-time">{formatBeijingTime(log.created_at)}</td>
                    <td className="cell-actions">
                      {!log.is_processed && (
                        <button className="btn-small btn-small-primary" onClick={() => void handleMarkProcessed(log.id)}>标记已处理</button>
                      )}
                    </td>
                  </tr>
                ))}
                {filteredExceptions.length === 0 && !loading && (
                  <tr><td colSpan={9} className="au-empty-cell">暂无异常记录</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <p className="au-note">标记已处理仅更新处理状态并追加一条 <code>audit.exception_processed</code> 处理事件，<strong>不修改原始审计事实</strong>（仅 admin 可操作）。</p>
        </section>
      )}

      {/* Login logs */}
      {activeTab === "login" && (
        <section className="audit-section">
          <div className="au-toolbar">
            <span className="au-toolbar-hint">共 {loginLogs.length} 条登录记录</span>
          </div>
          <p className="au-note">
            登录 / 登出审计（<code>login.success</code> / <code>login.failed</code> / <code>login.logout</code>）已接入，后端记录时即在此展示，
            <code>login_method</code> 区分 <code>password</code>（密码登录）/ <code>wecom_oauth</code>（企微）/ <code>dev_local</code>（本地开发免密适配器）。
            <strong>密码凭证登录已实现</strong>（所有环境按 email + password 校验）；本地开发使用免密适配器或尚无登录事件时，本表可能为空。
          </p>
          {loginLogs.length === 0 ? (
            <div className="au-empty-state">
              <p>当前无登录审计事件。经企微 OAuth 登录 / 登出后，<code>login.*</code> 事件将在此出现（本地开发态可能为空）。</p>
            </div>
          ) : (
            <div className="ingest-table-wrap">
              <table className="ingest-table">
                <thead>
                  <tr><th>用户</th><th>角色</th><th>动作</th><th>结果 / 原因</th><th>追踪 ID</th><th>时间</th></tr>
                </thead>
                <tbody>
                  {loginLogs.map((log) => (
                    <tr key={log.id}>
                      <td className="au-cell-user">{log.actor_name ?? "—"}</td>
                      <td><span className="au-role-badge">{roleText(log)}</span></td>
                      <td className="au-cell-action" title={log.action}>
                        {auditActionLabel(log.action)}
                        <span className="au-cell-raw">{log.action}</span>
                      </td>
                      <td className="au-cell-msg">{auditLoginSummary(log)}</td>
                      <td className="au-cell-trace" title={log.trace_id}>{log.trace_id}</td>
                      <td className="cell-time">{formatBeijingTime(log.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      <p className="page-help-line">
        同一次操作跨模块共享同一追踪 ID，可用于还原完整链路；详见 <Link to="/help#admin" className="page-help-link">使用说明 →</Link>
      </p>
    </div>
  );
}
