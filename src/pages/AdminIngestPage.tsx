import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Database,
  FileSearch,
  ListFilter,
  RefreshCw,
  RotateCw,
  ScanLine,
  ShieldCheck,
} from "lucide-react";
import {
  fetchIndexingJobs,
  fetchOpsIndexing,
  triggerIndexingReparse,
  triggerIndexingRetry,
} from "../api/admin";
import { fetchAdminIngest } from "../api/ingest";
import IndexDistribution from "../components/IndexDistribution";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import type { AdminIngestItemDTO } from "../types/ingest";
import type { IndexingJobSummaryDTO, OpsIndexingDTO, OpsIndexingFailedItemDTO } from "../types/ops";
import { formatBeijingTime } from "../utils/time";
import "./AdminIngestPage.css";

type LoadState = "loading" | "ready" | "error";
type FailureFilter = "all" | "urgent" | "attention";

const jobOpLabel: Record<string, string> = {
  retry_index: "批量重试索引",
  reparse: "重新解析",
};

const jobStatusLabel: Record<string, string> = {
  queued: "等待执行",
  running: "执行中",
  completed: "已完成",
  completed_with_errors: "完成，部分未成功",
  failed: "执行失败",
};

const ingestStatusLabel: Record<string, string> = {
  processing: "处理中",
  pending_confirmation: "待业务确认",
  completed: "已完成",
  failed: "处理失败",
};

const urgentSeverities = new Set(["critical", "error"]);

function jobTone(status: string) {
  if (status === "completed") return "success";
  if (status === "failed" || status === "completed_with_errors") return "danger";
  return "pending";
}

function safeJobStatus(status: string) {
  return jobStatusLabel[status] ?? "状态待确认";
}

function safeJobOperation(operation: string) {
  return jobOpLabel[operation] ?? "索引维护作业";
}

function failureTone(item: OpsIndexingFailedItemDTO) {
  return urgentSeverities.has(item.severity ?? "") ? "danger" : "warning";
}

function safeFailureMessage(item: OpsIndexingFailedItemDTO) {
  return item.operator_error_message || item.index_error_message || "索引处理异常";
}

export default function AdminIngestPage() {
  const [ingestItems, setIngestItems] = useState<AdminIngestItemDTO[]>([]);
  const [ingestState, setIngestState] = useState<LoadState>("loading");
  const [opsIndex, setOpsIndex] = useState<OpsIndexingDTO | null>(null);
  const [opsState, setOpsState] = useState<LoadState>("loading");
  const [opsJobs, setOpsJobs] = useState<IndexingJobSummaryDTO[]>([]);
  const [jobsState, setJobsState] = useState<LoadState>("loading");
  const [failureFilter, setFailureFilter] = useState<FailureFilter>("all");
  const [retryIncludeSkipped, setRetryIncludeSkipped] = useState(false);
  const [retryIncludeNotIndexed, setRetryIncludeNotIndexed] = useState(false);
  const [opsLimit, setOpsLimit] = useState(50);
  const [opsBusy, setOpsBusy] = useState(false);
  const [opsNote, setOpsNote] = useState<string | null>(null);
  const [opsNoteTone, setOpsNoteTone] = useState<"success" | "danger">("success");

  const loadIngest = useCallback(async () => {
    setIngestState("loading");
    try {
      setIngestItems((await fetchAdminIngest()).items);
      setIngestState("ready");
    } catch {
      setIngestItems([]);
      setIngestState("error");
    }
  }, []);

  const loadOpsIndex = useCallback(async () => {
    setOpsState("loading");
    try {
      setOpsIndex(await fetchOpsIndexing());
      setOpsState("ready");
    } catch {
      setOpsIndex(null);
      setOpsState("error");
    }
  }, []);

  const loadOpsJobs = useCallback(async () => {
    setJobsState("loading");
    try {
      setOpsJobs((await fetchIndexingJobs()).items);
      setJobsState("ready");
    } catch {
      setOpsJobs([]);
      setJobsState("error");
    }
  }, []);

  const refreshAll = useCallback(async () => {
    setOpsNote(null);
    await Promise.all([loadIngest(), loadOpsIndex(), loadOpsJobs()]);
  }, [loadIngest, loadOpsIndex, loadOpsJobs]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const activeJob = opsJobs.some((job) => ["queued", "running"].includes(job.status));
  const actionLocked = opsBusy || activeJob || opsState !== "ready";
  const refreshing = ingestState === "loading" || opsState === "loading" || jobsState === "loading";

  const recordJob = useCallback((job: IndexingJobSummaryDTO) => {
    setOpsJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)]);
    setJobsState("ready");
    setOpsNoteTone("success");
    setOpsNote(
      `${safeJobOperation(job.operation_type)}已提交：共 ${job.total_count} 项，成功 ${job.success_count} 项，失败 ${job.failed_count} 项，跳过 ${job.skipped_count} 项。`,
    );
  }, []);

  const handleBatchRetry = useCallback(async () => {
    if (actionLocked) return;
    setOpsBusy(true);
    setOpsNote(null);
    try {
      const statuses = ["index_failed"];
      if (retryIncludeSkipped) statuses.push("skipped");
      if (retryIncludeNotIndexed) statuses.push("not_indexed");
      recordJob(await triggerIndexingRetry({ scope: "all", statuses, limit: opsLimit }));
      await loadOpsIndex();
    } catch {
      setOpsNoteTone("danger");
      setOpsNote("批量重试未能发起，请稍后重试。");
    } finally {
      setOpsBusy(false);
    }
  }, [
    actionLocked,
    loadOpsIndex,
    opsLimit,
    recordJob,
    retryIncludeNotIndexed,
    retryIncludeSkipped,
  ]);

  const handleReparse = useCallback(async () => {
    if (actionLocked) return;
    setOpsBusy(true);
    setOpsNote(null);
    try {
      recordJob(
        await triggerIndexingReparse({
          scope: "all",
          parse_statuses: ["failed", "pending"],
          limit: opsLimit,
        }),
      );
      await loadOpsIndex();
    } catch {
      setOpsNoteTone("danger");
      setOpsNote("重新解析未能发起，请稍后重试。");
    } finally {
      setOpsBusy(false);
    }
  }, [actionLocked, loadOpsIndex, opsLimit, recordJob]);

  const ingestCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of ingestItems) counts.set(item.status, (counts.get(item.status) ?? 0) + 1);
    return counts;
  }, [ingestItems]);

  const failedItems = useMemo(() => {
    const items = opsIndex?.recent_failed ?? [];
    if (failureFilter === "urgent") {
      return items.filter((item) => urgentSeverities.has(item.severity ?? ""));
    }
    if (failureFilter === "attention") {
      return items.filter((item) => !urgentSeverities.has(item.severity ?? ""));
    }
    return items;
  }, [failureFilter, opsIndex]);

  return (
    <ProductPage className="ao84-page">
      <PageHeader
        title="管理员运维"
        description="查看索引运行、扫描任务和安全审计状态。"
        actions={
          <button
            className="btn-small ao84-refresh"
            onClick={() => void refreshAll()}
            disabled={refreshing || opsBusy}
          >
            <RefreshCw size={15} aria-hidden="true" />
            {refreshing ? "刷新中…" : "刷新"}
          </button>
        }
      />

      <nav className="ao84-tabs" aria-label="管理员运维页面">
        <Link className="is-active" to="/admin/ingest" aria-current="page">
          <Database size={16} aria-hidden="true" />
          索引维护
        </Link>
        <Link to="/admin/wecom-scan">
          <ScanLine size={16} aria-hidden="true" />
          微盘扫描
        </Link>
        <Link to="/admin/audit">
          <ShieldCheck size={16} aria-hidden="true" />
          安全日志
        </Link>
      </nav>

      <div className="ao84-console">
        <section className="ao84-panel ao84-summary" aria-labelledby="ao84-summary-title">
          <header className="ao84-panel-head">
            <div>
              <span className="ao84-eyebrow">索引维护</span>
              <h2 id="ao84-summary-title">全局索引队列</h2>
            </div>
            <Activity size={19} aria-hidden="true" />
          </header>

          {opsState === "loading" ? (
            <div className="ao84-panel-state" role="status">
              正在读取索引运行状态…
            </div>
          ) : opsState === "error" || !opsIndex ? (
            <div className="ao84-panel-state is-error" role="alert">
              <AlertTriangle size={20} aria-hidden="true" />
              <strong>索引状态暂时无法加载</strong>
              <span>入库运行概览仍可独立查看。</span>
            </div>
          ) : (
            <>
              <div
                className={`ao84-health ${opsIndex.counts.index_failed ? "is-warning" : "is-clear"}`}
              >
                {opsIndex.counts.index_failed ? (
                  <AlertTriangle size={18} aria-hidden="true" />
                ) : (
                  <CheckCircle2 size={18} aria-hidden="true" />
                )}
                <div>
                  <strong>
                    {opsIndex.counts.index_failed
                      ? `${opsIndex.counts.index_failed} 项索引失败`
                      : "当前没有索引失败项"}
                  </strong>
                  <span>状态来自平台索引安全统计</span>
                </div>
              </div>
              <IndexDistribution counts={opsIndex.counts} className="ao84-index-grid" />
            </>
          )}

          <div className="ao84-ingest-overview" aria-label="入库运行概览">
            <div className="ao84-subhead">
              <FileSearch size={16} aria-hidden="true" />
              <strong>入库运行概览</strong>
              {ingestState === "ready" && <span>共 {ingestItems.length} 项</span>}
            </div>
            {ingestState === "loading" ? (
              <p>正在读取入库队列…</p>
            ) : ingestState === "error" ? (
              <p className="is-error">入库概览暂时无法加载。</p>
            ) : (
              <div className="ao84-ingest-counts">
                {Object.entries(ingestStatusLabel).map(([status, label]) => (
                  <span key={status}>
                    <strong>{ingestCounts.get(status) ?? 0}</strong>
                    {label}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="ao84-actions" aria-label="索引批量操作">
            <div className="ao84-action-options">
              <label>
                <input
                  type="checkbox"
                  checked={retryIncludeSkipped}
                  onChange={(event) => setRetryIncludeSkipped(event.target.checked)}
                />
                包含已跳过
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={retryIncludeNotIndexed}
                  onChange={(event) => setRetryIncludeNotIndexed(event.target.checked)}
                />
                包含未索引
              </label>
              <label className="ao84-limit">
                处理上限
                <select
                  value={opsLimit}
                  onChange={(event) => setOpsLimit(Number(event.target.value))}
                >
                  {[20, 50, 100, 200].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="ao84-action-buttons">
              <button
                className="btn-small-primary"
                disabled={actionLocked}
                onClick={() => void handleBatchRetry()}
              >
                <RotateCw size={15} aria-hidden="true" />
                {opsBusy ? "提交中…" : activeJob ? "作业执行中" : "批量重试索引"}
              </button>
              <button
                className="btn-small"
                disabled={actionLocked}
                onClick={() => void handleReparse()}
              >
                <FileSearch size={15} aria-hidden="true" />
                重新解析
              </button>
            </div>
          </div>

          {opsNote && (
            <div
              className={`ao84-action-note is-${opsNoteTone}`}
              role={opsNoteTone === "danger" ? "alert" : "status"}
            >
              {opsNote}
            </div>
          )}

          <details className="ao84-jobs">
            <summary>
              <Clock3 size={16} aria-hidden="true" />
              最近作业
              <span>{opsJobs.length} 项</span>
            </summary>
            {jobsState === "loading" ? (
              <p>正在读取作业状态…</p>
            ) : jobsState === "error" ? (
              <p className="is-error">最近作业暂时无法加载。</p>
            ) : opsJobs.length === 0 ? (
              <p>当前没有索引维护作业。</p>
            ) : (
              <ul>
                {opsJobs.map((job) => (
                  <li key={job.job_id}>
                    <div>
                      <strong>{safeJobOperation(job.operation_type)}</strong>
                      <time>
                        {formatBeijingTime(job.finished_at || job.started_at || job.requested_at)}
                      </time>
                    </div>
                    <span className={`ao84-status is-${jobTone(job.status)}`}>
                      {safeJobStatus(job.status)}
                    </span>
                    <small>
                      共 {job.total_count} · 成功 {job.success_count} · 失败 {job.failed_count} ·
                      跳过 {job.skipped_count}
                    </small>
                  </li>
                ))}
              </ul>
            )}
          </details>
        </section>

        <section className="ao84-panel ao84-failures" aria-labelledby="ao84-failures-title">
          <header className="ao84-panel-head">
            <div>
              <span className="ao84-eyebrow">安全任务摘要</span>
              <h2 id="ao84-failures-title">失败索引任务</h2>
            </div>
            <label className="ao84-failure-filter">
              <ListFilter size={15} aria-hidden="true" />
              <span className="sr-only">当前失败列表筛选</span>
              <select
                value={failureFilter}
                onChange={(event) => setFailureFilter(event.target.value as FailureFilter)}
              >
                <option value="all">全部失败任务</option>
                <option value="urgent">需优先处理</option>
                <option value="attention">一般关注</option>
              </select>
            </label>
          </header>

          <div className="ao84-table-wrap">
            <table className="ao84-table">
              <thead>
                <tr>
                  <th>错误类型</th>
                  <th>最后尝试时间</th>
                  <th>状态</th>
                  <th>处理方式</th>
                </tr>
              </thead>
              <tbody>
                {opsState === "ready" &&
                  failedItems.map((item) => (
                    <tr key={item.asset_id}>
                      <td>
                        <div className="ao84-failure-kind">
                          <AlertTriangle size={16} aria-hidden="true" />
                          <div>
                            <strong>索引处理异常</strong>
                            <span>{safeFailureMessage(item)}</span>
                          </div>
                        </div>
                      </td>
                      <td>
                        <time>{formatBeijingTime(item.updated_at)}</time>
                      </td>
                      <td>
                        <span className={`ao84-status is-${failureTone(item)}`}>索引失败</span>
                      </td>
                      <td>
                        <span className="ao84-batch-hint">通过左侧批量重试处理</span>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>

            {opsState === "loading" && (
              <div className="ao84-table-state" role="status">
                正在读取失败任务…
              </div>
            )}
            {opsState === "error" && (
              <div className="ao84-table-state is-error" role="alert">
                <AlertTriangle size={21} aria-hidden="true" />
                <strong>失败任务暂时无法加载</strong>
                <span>刷新后可重新获取安全任务摘要。</span>
              </div>
            )}
            {opsState === "ready" && failedItems.length === 0 && (
              <div className="ao84-table-state">
                <CheckCircle2 size={22} aria-hidden="true" />
                <strong>当前没有索引失败任务</strong>
                <span>
                  {failureFilter === "all" ? "索引失败列表为空。" : "当前筛选条件下没有任务。"}
                </span>
              </div>
            )}
          </div>
        </section>
      </div>
    </ProductPage>
  );
}
