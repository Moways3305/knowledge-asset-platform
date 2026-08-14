import { Fragment, useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, RefreshCw, ScrollText, SlidersHorizontal } from "lucide-react";
import { fetchAudit, markAuditProcessed } from "../api/admin";
import { ApiError } from "../api/http";
import { Link } from "react-router-dom";
import { PageHeader, PageToolbar, ProductPage } from "../components/ProductLayout";
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

// 事件 → 当前状态入口：审计是历史快照，资产现状请跳到对应工作区查看。
function stateHref(event: AuditEventDTO): string | null {
  if (!event.target_id) return null;
  if (event.target_type === "knowledge_asset") return `/knowledge/${event.target_id}`;
  if (event.target_type === "ingest_task" || event.target_type === "indexing_operation_job") {
    return "/admin/ingest";
  }
  return null;
}

export default function AdminAuditPage() {
  const [activeTab, setActiveTab] = useState<LogTab>("exception");
  const [items, setItems] = useState<AuditEventDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [view, setView] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filterSeverity, setFilterSeverity] = useState("");
  const [filterProcessed, setFilterProcessed] = useState("unprocessed");
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const PAGE_SIZE = 50;

  const loadList = useCallback(
    async (tab: LogTab, pageNum: number) => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetchAudit({
          logType: tab,
          severity: tab === "exception" ? filterSeverity || undefined : undefined,
          isProcessed:
            tab === "exception" && filterProcessed ? filterProcessed === "processed" : undefined,
          page: pageNum,
          pageSize: PAGE_SIZE,
        });
        setItems(response.items);
        setTotal(response.total);
        setPage(response.page);
        setView(response.view);
        setExpandedId(null);
      } catch (reason) {
        setItems([]);
        setTotal(0);
        setPage(1);
        setError(
          reason instanceof ApiError && reason.status === 403
            ? "当前身份没有审计日志查看权限。"
            : "审计日志暂时无法加载，请稍后重试。",
        );
      } finally {
        setLoading(false);
      }
    },
    [filterProcessed, filterSeverity],
  );

  useEffect(() => {
    void loadList(activeTab, 1);
  }, [activeTab, filterProcessed, filterSeverity, loadList]);

  const canProcess = view === "admin_metadata";

  const handleMarkProcessed = useCallback(
    async (event: AuditEventDTO) => {
      if (!canProcess || event.is_processed) return;
      setProcessingId(event.id);
      setNotice(null);
      try {
        await markAuditProcessed(event.id);
        setItems((current) =>
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

  const logs = items;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <ProductPage className="secops-page audit-page admin-control-page">
      <PageHeader eyebrow="安全运营" title="审计日志" />
      <div className="secops-console">
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
            <div className="secops-workspace-heading">
              <span className="secops-workspace-heading-icon">
                <ScrollText size={16} />
              </span>
              <div>
                <strong>审计记录</strong>
                <span>按记录类型核查平台安全活动</span>
              </div>
            </div>
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
                  {activeTab === "exception" && (
                    <div className="secops-filters">
                      <SlidersHorizontal size={14} aria-hidden="true" />
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
                  )}
                  <span className="secops-count">共 {total} 条</span>
                  <button
                    className="btn-small"
                    onClick={() => {
                      void loadList(activeTab, page);
                    }}
                    disabled={loading}
                  >
                    <RefreshCw size={13} aria-hidden="true" /> {loading ? "刷新中…" : "刷新"}
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
                    <Fragment key={item.id}>
                      <tr
                        className={
                          activeTab === "exception" && !item.is_processed ? "is-actionable" : ""
                        }
                      >
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
                            <div className="secops-row-actions">
                              {stateHref(item) && (
                                <Link className="secops-state-link" to={stateHref(item)!}>
                                  查看当前状态
                                </Link>
                              )}
                              <button
                                className="btn-small secops-detail-toggle"
                                onClick={() =>
                                  setExpandedId(expandedId === item.id ? null : item.id)
                                }
                                aria-expanded={expandedId === item.id}
                                aria-label="展开详情"
                              >
                                {expandedId === item.id ? (
                                  <ChevronDown size={13} aria-hidden="true" />
                                ) : (
                                  <ChevronRight size={13} aria-hidden="true" />
                                )}
                                详情
                              </button>
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
                            </div>
                          </td>
                        )}
                      </tr>
                      {activeTab === "exception" && expandedId === item.id && (
                        <tr className="secops-detail-row">
                          <td colSpan={6}>
                            <div className="secops-detail-grid">
                              {item.trace_id && (
                                <div className="secops-detail-item">
                                  <span className="secops-detail-label">追踪 ID</span>
                                  <code className="secops-detail-value">{item.trace_id}</code>
                                </div>
                              )}
                              {item.denied_reason && (
                                <div className="secops-detail-item">
                                  <span className="secops-detail-label">拒绝原因</span>
                                  <code className="secops-detail-value">{item.denied_reason}</code>
                                </div>
                              )}
                              {item.risk_level && (
                                <div className="secops-detail-item">
                                  <span className="secops-detail-label">风险等级</span>
                                  <span className="secops-detail-value">{item.risk_level}</span>
                                </div>
                              )}
                              {item.actor_user_id && (
                                <div className="secops-detail-item">
                                  <span className="secops-detail-label">操作人 ID</span>
                                  <code className="secops-detail-value">{item.actor_user_id}</code>
                                </div>
                              )}
                              {item.target_id && (
                                <div className="secops-detail-item">
                                  <span className="secops-detail-label">目标 ID</span>
                                  <code className="secops-detail-value">{item.target_id}</code>
                                </div>
                              )}
                              {item.processed_at && (
                                <div className="secops-detail-item">
                                  <span className="secops-detail-label">处理时间</span>
                                  <span className="secops-detail-value">
                                    {formatBeijingTime(item.processed_at)}
                                  </span>
                                </div>
                              )}
                              {item.processed_by && (
                                <div className="secops-detail-item">
                                  <span className="secops-detail-label">处理人 ID</span>
                                  <code className="secops-detail-value">{item.processed_by}</code>
                                </div>
                              )}
                              {item.before_snapshot && (
                                <div className="secops-detail-item secops-detail-snapshot">
                                  <span className="secops-detail-label">变更前</span>
                                  <pre className="secops-detail-value">
                                    {JSON.stringify(item.before_snapshot, null, 2)}
                                  </pre>
                                </div>
                              )}
                              {item.after_snapshot && (
                                <div className="secops-detail-item secops-detail-snapshot">
                                  <span className="secops-detail-label">变更后</span>
                                  <pre className="secops-detail-value">
                                    {JSON.stringify(item.after_snapshot, null, 2)}
                                  </pre>
                                </div>
                              )}
                              {item.extra && (
                                <div className="secops-detail-item secops-detail-snapshot">
                                  <span className="secops-detail-label">附加信息</span>
                                  <pre className="secops-detail-value">
                                    {JSON.stringify(item.extra, null, 2)}
                                  </pre>
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
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
            <div className="secops-pagination">
              <span>
                第 {total === 0 ? 0 : page} / {totalPages} 页 · 共 {total} 条
              </span>
              <button
                type="button"
                className="btn-small"
                disabled={loading || page <= 1}
                onClick={() => void loadList(activeTab, page - 1)}
              >
                上一页
              </button>
              <button
                type="button"
                className="btn-small"
                disabled={loading || page >= totalPages}
                onClick={() => void loadList(activeTab, page + 1)}
              >
                下一页
              </button>
            </div>
          </section>
        </main>
      </div>
    </ProductPage>
  );
}
