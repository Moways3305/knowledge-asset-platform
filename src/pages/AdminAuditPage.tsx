import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchAudit, markAuditProcessed } from "../api/admin";
import { ApiError } from "../api/http";
import {
  OperationsSummary,
  PageHeader,
  PageToolbar,
  ProductPage,
} from "../components/ProductLayout";
import type { AuditEventDTO } from "../types/audit";
import { auditActionLabel, auditLoginSummary, auditTargetTypeLabel } from "../utils/auditDisplay";
import { formatBeijingTime } from "../utils/time";

type LogTab = "operation" | "exception" | "login";

const tabLabel: Record<LogTab, string> = { operation: "操作", exception: "异常", login: "登录" };
const severityLabel: Record<string, string> = {
  critical: "严重",
  error: "错误",
  warning: "警告",
};
const roleLabel: Record<string, string> = {
  boss: "总经理",
  consulting_director: "咨询总监",
  consultant: "顾问",
  admin: "管理员",
  project_manager: "项目经理",
  coach: "辅导老师",
};

function safeRole(event: AuditEventDTO) {
  return roleLabel[event.actor_company_role ?? ""] ?? "未标注";
}

export default function AdminAuditPage() {
  const [activeTab, setActiveTab] = useState<LogTab>("operation");
  const [events, setEvents] = useState<AuditEventDTO[]>([]);
  const [view, setView] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filterSeverity, setFilterSeverity] = useState("");
  const [filterProcessed, setFilterProcessed] = useState("");
  const [processingId, setProcessingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchAudit({ pageSize: 200 });
      setEvents(response.items);
      setView(response.view);
    } catch (reason) {
      setEvents([]);
      setView("");
      setError(
        reason instanceof ApiError && reason.status === 403
          ? "当前身份没有审计日志查看权限。"
          : "审计日志暂时无法加载，请稍后重试。",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => void load(), [load]);

  const operationLogs = useMemo(
    () => events.filter((item) => item.log_type === "operation"),
    [events],
  );
  const exceptionLogs = useMemo(
    () => events.filter((item) => item.log_type === "exception"),
    [events],
  );
  const loginLogs = useMemo(() => events.filter((item) => item.log_type === "login"), [events]);
  const filteredExceptions = useMemo(
    () =>
      exceptionLogs.filter(
        (item) =>
          (!filterSeverity || item.severity === filterSeverity) &&
          (!filterProcessed ||
            (filterProcessed === "processed" ? item.is_processed : !item.is_processed)),
      ),
    [exceptionLogs, filterProcessed, filterSeverity],
  );
  const canProcess = view === "admin_metadata";

  const handleMarkProcessed = useCallback(
    async (event: AuditEventDTO) => {
      if (!canProcess || event.is_processed) return;
      setProcessingId(event.id);
      setNotice(null);
      try {
        await markAuditProcessed(event.id);
        setEvents((current) =>
          current.map((item) => (item.id === event.id ? { ...item, is_processed: true } : item)),
        );
        setNotice("异常记录已标记为已处理。");
      } catch (reason) {
        if (reason instanceof ApiError && reason.status === 403) setView("governance");
        setError(
          reason instanceof ApiError && reason.status === 403
            ? "当前身份仅可查看审计记录，不能标记处理。"
            : "处理状态保存失败，请稍后重试。",
        );
      } finally {
        setProcessingId(null);
      }
    },
    [canProcess],
  );

  const logs =
    activeTab === "operation"
      ? operationLogs
      : activeTab === "login"
        ? loginLogs
        : filteredExceptions;

  return (
    <ProductPage className="secops-page audit-page">
      <PageHeader
        eyebrow="安全运营"
        title="审计日志"
        description="核查关键操作、异常处置与登录结果。页面时间均为北京时间。"
      />
      <div className="secops-console">
        <OperationsSummary
          label="审计摘要"
          items={[
            { label: "操作记录", value: operationLogs.length },
            {
              label: "未处理异常",
              value: exceptionLogs.filter((item) => !item.is_processed).length,
              tone: "warning",
            },
            {
              label: "登录失败",
              value: loginLogs.filter((item) => item.action === "login.failed").length,
              tone: "danger",
            },
            {
              label: "严重 / 错误",
              value: exceptionLogs.filter(
                (item) => item.severity === "critical" || item.severity === "error",
              ).length,
              tone: "danger",
            },
          ]}
        />
        <main className="secops-main-workspace">
          {view === "governance" && !error && (
            <div className="secops-banner is-readonly">
              当前为只读审计视图，可核查记录但不能标记处理。
            </div>
          )}
          {error && (
            <div className="secops-banner is-error" role="alert">
              {error}
            </div>
          )}
          {notice && (
            <div className="secops-banner is-success" role="status">
              {notice}
            </div>
          )}
          <section className="secops-workspace" aria-label="审计记录">
            <PageToolbar
              className="secops-toolbar"
              start={
                <div className="secops-tabs" role="tablist">
                  {(Object.keys(tabLabel) as LogTab[]).map((tab) => (
                    <button
                      key={tab}
                      role="tab"
                      aria-selected={activeTab === tab}
                      className={activeTab === tab ? "is-active" : ""}
                      onClick={() => setActiveTab(tab)}
                    >
                      {tabLabel[tab]}
                    </button>
                  ))}
                </div>
              }
              end={
                <div className="secops-toolbar-actions">
                  {activeTab === "exception" ? (
                    <div className="secops-filters">
                      <label>
                        级别
                        <select
                          aria-label="异常级别"
                          value={filterSeverity}
                          onChange={(event) => setFilterSeverity(event.target.value)}
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
                          aria-label="处理状态"
                          value={filterProcessed}
                          onChange={(event) => setFilterProcessed(event.target.value)}
                        >
                          <option value="">全部</option>
                          <option value="unprocessed">未处理</option>
                          <option value="processed">已处理</option>
                        </select>
                      </label>
                    </div>
                  ) : (
                    <span className="secops-count">共 {logs.length} 条</span>
                  )}
                  <button className="btn-small" onClick={() => void load()} disabled={loading}>
                    {loading ? "刷新中…" : "刷新"}
                  </button>
                </div>
              }
            />
            <div className="secops-table-wrap">
              <table className="secops-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>{activeTab === "login" ? "用户" : "事项"}</th>
                    <th>{activeTab === "login" ? "结果" : "操作人"}</th>
                    <th>{activeTab === "exception" ? "级别" : "角色"}</th>
                    <th>{activeTab === "exception" ? "状态" : "对象"}</th>
                    {activeTab === "exception" && <th>操作</th>}
                  </tr>
                </thead>
                <tbody>
                  {logs.map((item) => (
                    <tr key={item.id}>
                      <td className="secops-time">{formatBeijingTime(item.created_at)}</td>
                      <td className="secops-primary">
                        {activeTab === "login"
                          ? (item.actor_name ?? "未知用户")
                          : auditActionLabel(item.action)}
                      </td>
                      <td>
                        {activeTab === "login"
                          ? auditLoginSummary(item)
                          : (item.actor_name ?? "系统操作")}
                      </td>
                      <td>
                        {activeTab === "exception" ? (
                          <span className={`secops-pill severity-${item.severity ?? "unknown"}`}>
                            {severityLabel[item.severity ?? ""] ?? "未分级"}
                          </span>
                        ) : (
                          safeRole(item)
                        )}
                      </td>
                      <td>
                        {activeTab === "exception" ? (
                          <span
                            className={`secops-pill ${item.is_processed ? "is-done" : "is-pending"}`}
                          >
                            {item.is_processed ? "已处理" : "未处理"}
                          </span>
                        ) : (
                          auditTargetTypeLabel(item.target_type)
                        )}
                      </td>
                      {activeTab === "exception" && (
                        <td>
                          {!item.is_processed && canProcess ? (
                            <button
                              className="btn-small"
                              disabled={processingId === item.id}
                              onClick={() => void handleMarkProcessed(item)}
                            >
                              {processingId === item.id ? "保存中…" : "标记已处理"}
                            </button>
                          ) : (
                            <span className="secops-muted">
                              {item.is_processed ? "已完成" : "只读"}
                            </span>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                  {!loading && logs.length === 0 && (
                    <tr>
                      <td colSpan={activeTab === "exception" ? 6 : 5} className="secops-empty">
                        {activeTab === "operation"
                          ? "暂无操作记录"
                          : activeTab === "exception"
                            ? "暂无符合条件的异常记录"
                            : "暂无登录记录"}
                      </td>
                    </tr>
                  )}
                  {loading && (
                    <tr>
                      <td colSpan={activeTab === "exception" ? 6 : 5} className="secops-empty">
                        正在加载审计记录…
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </main>
      </div>
    </ProductPage>
  );
}
