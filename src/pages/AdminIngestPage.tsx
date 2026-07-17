import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock3,
  Database,
  FileSearch,
  ListFilter,
  HeartPulse,
  RefreshCw,
  RotateCw,
  ScanLine,
  ShieldCheck,
} from "lucide-react";
import {
  fetchIndexingJobs,
  fetchIndexingHealth,
  fetchOpsIndexing,
  triggerIndexingReparse,
  triggerIndexingRetry,
  triggerTargetedIndexingRetry,
} from "../api/admin";
import { ApiError } from "../api/http";
import { fetchAdminIngest } from "../api/ingest";
import IndexDistribution from "../components/IndexDistribution";
import ConfirmDialog from "../components/ConfirmDialog";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import type { AdminIngestItemDTO } from "../types/ingest";
import type {
  IndexingHealthDTO,
  IndexingJobSummaryDTO,
  OpsIndexingDTO,
  OpsIndexingFailedItemDTO,
} from "../types/ops";
import { formatBeijingTime } from "../utils/time";
import "./AdminIngestPage.css";

type LoadState = "loading" | "ready" | "error";
type DiagnosticCategory = OpsIndexingFailedItemDTO["diagnostic_category"];
type FailureFilter = "all" | DiagnosticCategory;

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
const diagnosticLabels: Record<DiagnosticCategory, string> = {
  configuration: "配置问题",
  external_service: "外部服务",
  source_content: "文件或内容",
  permission: "权限或访问",
  platform: "平台处理",
  unknown: "待确认",
};

const healthLabels = {
  healthy: "正常",
  degraded: "需关注",
  stale: "心跳过期",
  unknown: "待确认",
};

function trendPointLabel(point: IndexingHealthDTO["trend_points"][number]): string {
  return `${formatBeijingTime(point.observed_at)}，已完成作业 ${point.completed_jobs}，失败或部分失败作业 ${point.failed_jobs}，排队作业 ${point.queued_jobs}，索引失败存量 ${point.index_failed}`;
}

function trendTickLabel(points: IndexingHealthDTO["trend_points"], index: number): string {
  const current = formatBeijingTime(points[index]?.observed_at);
  const previous = index > 0 ? formatBeijingTime(points[index - 1]?.observed_at) : null;
  const time = current.slice(11, 16);
  return previous && previous.slice(0, 10) !== current.slice(0, 10)
    ? `${current.slice(5, 10).replace("-", "/")} ${time}`
    : time;
}

function trendTickIndexes(points: IndexingHealthDTO["trend_points"]): Set<number> {
  if (points.length < 8) return new Set(points.map((_, index) => index));
  const indexes = new Set<number>();
  if (points.length === 24) {
    for (let index = 0; index < points.length; index += 3) indexes.add(index);
  } else {
    const last = points.length - 1;
    for (let tick = 0; tick < 8; tick += 1) indexes.add(Math.round((last * tick) / 7));
  }
  const dateBoundaries: number[] = [];
  for (let index = 1; index < points.length; index += 1) {
    const previousDate = formatBeijingTime(points[index - 1].observed_at).slice(0, 10);
    const currentDate = formatBeijingTime(points[index].observed_at).slice(0, 10);
    if (currentDate !== previousDate) dateBoundaries.push(index);
  }
  for (const boundary of dateBoundaries) {
    for (const index of [...indexes]) {
      if (Math.abs(index - boundary) < 3) indexes.delete(index);
    }
    indexes.add(boundary);
  }
  indexes.add(points.length - 1);
  while (indexes.size < 8) {
    let candidate = -1;
    let candidateDistance = -1;
    for (let index = 0; index < points.length; index += 1) {
      if (indexes.has(index)) continue;
      const distance = Math.min(...[...indexes].map((existing) => Math.abs(existing - index)));
      if (distance > candidateDistance) {
        candidate = index;
        candidateDistance = distance;
      }
    }
    if (candidate < 0) break;
    indexes.add(candidate);
  }
  return indexes;
}

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
  const [health, setHealth] = useState<IndexingHealthDTO | null>(null);
  const [healthState, setHealthState] = useState<LoadState>("loading");
  const [failureFilter, setFailureFilter] = useState<FailureFilter>("all");
  const [retryIncludeSkipped, setRetryIncludeSkipped] = useState(false);
  const [retryIncludeNotIndexed, setRetryIncludeNotIndexed] = useState(false);
  const [opsLimit, setOpsLimit] = useState(50);
  const [opsBusy, setOpsBusy] = useState(false);
  const [opsNote, setOpsNote] = useState<string | null>(null);
  const [opsNoteTone, setOpsNoteTone] = useState<"success" | "danger">("success");
  const [retryTarget, setRetryTarget] = useState<OpsIndexingFailedItemDTO | null>(null);
  const [targetBusy, setTargetBusy] = useState(false);
  const [targetError, setTargetError] = useState<string | null>(null);

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

  const loadHealth = useCallback(async () => {
    setHealthState("loading");
    try {
      setHealth(await fetchIndexingHealth(24));
      setHealthState("ready");
    } catch {
      setHealth(null);
      setHealthState("error");
    }
  }, []);

  const refreshAll = useCallback(async () => {
    setOpsNote(null);
    await Promise.all([loadIngest(), loadOpsIndex(), loadOpsJobs(), loadHealth()]);
  }, [loadHealth, loadIngest, loadOpsIndex, loadOpsJobs]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const activeJob = opsJobs.some((job) => ["queued", "running"].includes(job.status));
  const actionLocked = opsBusy || activeJob || opsState !== "ready";
  const refreshing =
    ingestState === "loading" ||
    opsState === "loading" ||
    jobsState === "loading" ||
    healthState === "loading";

  const recordJob = useCallback((job: IndexingJobSummaryDTO, operationLabel?: string) => {
    setOpsJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)]);
    setJobsState("ready");
    setOpsNoteTone("success");
    setOpsNote(
      `${operationLabel ?? safeJobOperation(job.operation_type)}已提交：共 ${job.total_count} 项，成功 ${job.success_count} 项，失败 ${job.failed_count} 项，跳过 ${job.skipped_count} 项。`,
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

  const handleTargetRetry = useCallback(async () => {
    if (!retryTarget || targetBusy) return;
    setTargetBusy(true);
    setTargetError(null);
    try {
      if (!retryTarget.retry_target) return;
      recordJob(await triggerTargetedIndexingRetry(retryTarget.retry_target), "单条索引重试");
      setRetryTarget(null);
      await Promise.all([loadOpsIndex(), loadOpsJobs(), loadHealth()]);
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        setTargetError("当前身份无权执行此操作。");
      } else if (error instanceof ApiError && error.status === 409) {
        setTargetError("任务状态已变化或正在执行，请刷新后重试。");
      } else {
        setTargetError("单条重试未能发起，请稍后重试。");
      }
    } finally {
      setTargetBusy(false);
    }
  }, [loadHealth, loadOpsIndex, loadOpsJobs, recordJob, retryTarget, targetBusy]);

  const ingestCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of ingestItems) counts.set(item.status, (counts.get(item.status) ?? 0) + 1);
    return counts;
  }, [ingestItems]);

  const failedItems = useMemo(() => {
    const items = opsIndex?.recent_failed ?? [];
    return failureFilter === "all"
      ? items
      : items.filter((item) => item.diagnostic_category === failureFilter);
  }, [failureFilter, opsIndex]);

  const trendMax = useMemo(
    () =>
      Math.max(
        1,
        ...(health?.trend_points.flatMap((point) => [point.completed_jobs, point.failed_jobs]) ??
          []),
      ),
    [health],
  );
  const visibleTrendTicks = useMemo(() => trendTickIndexes(health?.trend_points ?? []), [health]);
  const healthCards: Array<{
    label: string;
    status: keyof typeof healthLabels;
    lastHeartbeat: string | null;
    detail: string | null;
  }> = health
    ? [
        {
          label: "任务进程",
          status: health.worker.status,
          lastHeartbeat: health.worker.last_heartbeat_at,
          detail: null,
        },
        {
          label: "定时调度",
          status: health.beat.status,
          lastHeartbeat: health.beat.last_heartbeat_at,
          detail: null,
        },
        {
          label: "作业队列",
          status: health.queue.status,
          lastHeartbeat: null,
          detail: `等待 ${health.queue.queued_count} 项`,
        },
      ]
    : [];

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
                {Object.entries(diagnosticLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </header>

          {opsState === "ready" && opsIndex && (
            <div className="ao85-diagnostics" aria-label="失败诊断分类数量">
              {Object.entries(diagnosticLabels).map(([category, label]) => (
                <button
                  key={category}
                  type="button"
                  className={failureFilter === category ? "is-active" : ""}
                  onClick={() => setFailureFilter(category as DiagnosticCategory)}
                >
                  <span>{label}</span>
                  <strong>{opsIndex.diagnostic_counts[category as DiagnosticCategory] ?? 0}</strong>
                </button>
              ))}
            </div>
          )}

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
                    <tr key={item.retry_target ?? `${item.scope}-${item.updated_at}`}>
                      <td>
                        <div className="ao84-failure-kind">
                          <AlertTriangle size={16} aria-hidden="true" />
                          <div>
                            <strong>{item.diagnostic_label}</strong>
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
                        {item.retry_eligible && item.retry_target ? (
                          <button
                            type="button"
                            className="btn-small ao85-target-retry"
                            onClick={() => {
                              setTargetError(null);
                              setRetryTarget(item);
                            }}
                          >
                            <RotateCw size={14} aria-hidden="true" />
                            重试索引
                          </button>
                        ) : (
                          <span className="ao84-batch-hint">通过左侧批量重试处理</span>
                        )}
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

          <section className="ao85-runtime" aria-labelledby="ao85-runtime-title">
            <div className="ao85-runtime-head">
              <div>
                <HeartPulse size={17} aria-hidden="true" />
                <h3 id="ao85-runtime-title">运行健康</h3>
              </div>
              <span>最近 24 小时</span>
            </div>
            {healthState === "loading" ? (
              <div className="ao85-runtime-state" role="status">
                正在读取运行健康…
              </div>
            ) : healthState === "error" || !health ? (
              <div className="ao85-runtime-state is-error" role="alert">
                运行健康暂时无法加载。
              </div>
            ) : (
              <>
                <div className="ao85-runtime-statuses">
                  {healthCards.map((card) => (
                    <div key={card.label}>
                      <span>{card.label}</span>
                      <strong className={`is-${card.status}`}>{healthLabels[card.status]}</strong>
                      {card.lastHeartbeat && <time>{formatBeijingTime(card.lastHeartbeat)}</time>}
                      {card.detail && <small>{card.detail}</small>}
                    </div>
                  ))}
                </div>
                {health.insufficient_data ? (
                  <div className="ao85-trend-empty">
                    <BarChart3 size={18} aria-hidden="true" />
                    <strong>正在积累运维数据</strong>
                    <span>形成至少两个真实小时快照后展示趋势。</span>
                  </div>
                ) : (
                  <div className="ao85-trend-block">
                    <div className="ao85-trend-heading">
                      <strong>近 24 小时索引运维趋势</strong>
                      <div className="ao85-trend-legend" aria-label="趋势图例">
                        <span>
                          <i className="is-completed" aria-hidden="true" />
                          深蓝：已完成索引运维作业数
                        </span>
                        <span>
                          <i className="is-failed" aria-hidden="true" />
                          红色：失败或部分失败的索引运维作业数
                        </span>
                      </div>
                    </div>
                    <div className="ao85-trend" aria-label="近 24 小时索引运维趋势">
                      {health.trend_points.map((point, index) => {
                        const label = trendPointLabel(point);
                        const tooltipId = `ao85-trend-tooltip-${index}`;
                        return (
                          <div
                            key={point.observed_at}
                            className={`ao85-trend-point${index < 3 ? " is-near-start" : ""}${index >= health.trend_points.length - 3 ? " is-near-end" : ""}`}
                            role="img"
                            tabIndex={0}
                            aria-label={label}
                            aria-describedby={tooltipId}
                          >
                            <div className="ao85-trend-bars" aria-hidden="true">
                              <span
                                className="is-completed"
                                style={{
                                  height:
                                    point.completed_jobs === 0
                                      ? "0%"
                                      : `${Math.max(2, (point.completed_jobs / trendMax) * 100)}%`,
                                }}
                              />
                              <span
                                className="is-failed"
                                style={{
                                  height:
                                    point.failed_jobs === 0
                                      ? "0%"
                                      : `${Math.max(2, (point.failed_jobs / trendMax) * 100)}%`,
                                }}
                              />
                            </div>
                            <time
                              className={`ao85-trend-tick${visibleTrendTicks.has(index) ? "" : " is-hidden"}`}
                              aria-hidden="true"
                            >
                              {trendTickLabel(health.trend_points, index)}
                            </time>
                            <div id={tooltipId} className="ao85-trend-tooltip" role="tooltip">
                              <strong>{formatBeijingTime(point.observed_at)}</strong>
                              <span>已完成作业 {point.completed_jobs}</span>
                              <span>失败或部分失败作业 {point.failed_jobs}</span>
                              <span>排队作业 {point.queued_jobs}</span>
                              <span>索引失败存量 {point.index_failed}</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </>
            )}
          </section>
        </section>
      </div>

      <ConfirmDialog
        open={retryTarget !== null}
        title="确认重试这项索引？"
        description="此操作仅重新尝试索引，不查看、不下载、不修改原文。"
        confirmText="确认重试"
        busyText="提交中…"
        busy={targetBusy}
        error={targetError}
        onConfirm={() => void handleTargetRetry()}
        onCancel={() => {
          setRetryTarget(null);
          setTargetError(null);
        }}
      />
    </ProductPage>
  );
}
