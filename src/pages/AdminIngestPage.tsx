import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  RotateCw,
  ScanLine,
  ShieldCheck,
} from "lucide-react";
import {
  fetchIndexingJobs,
  fetchIndexingHealth,
  fetchLLMUsage,
  fetchOpsIndexing,
  triggerIndexingReparse,
  triggerIndexingRetry,
  triggerTargetedIndexingRetry,
} from "../api/admin";
import { ApiError } from "../api/http";
import { fetchAdminIngest } from "../api/ingest";
import IndexDistribution from "../components/IndexDistribution";
import ConfirmDialog from "../components/ConfirmDialog";
import ActionFeedback, { type ActionFeedbackState } from "../components/ActionFeedback";
import DetailDrawer from "../components/DetailDrawer";
import OperationStatusCard from "../components/OperationStatusCard";
import { operationStatusFromJob } from "../components/operationStatus";
import Button from "../components/Button";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import type { AdminIngestItemDTO } from "../types/ingest";
import type {
  IndexingHealthDTO,
  IndexingJobSummaryDTO,
  LLMUsageAggregateItemDTO,
  OpsIndexingDTO,
  OpsIndexingFailedItemDTO,
} from "../types/ops";
import { formatBeijingTime } from "../utils/time";
import "./AdminIngestPage.css";

type LoadState = "loading" | "ready" | "error";
type DiagnosticCategory = OpsIndexingFailedItemDTO["diagnostic_category"];
type FailureFilter = "all" | DiagnosticCategory;

const JOB_POLL_INTERVAL_MS = 1_500;
const JOB_POLL_MAX_ATTEMPTS = 20;
const OPS_AUTO_REFRESH_MS = 60_000;

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
  no_action: "未找到可处理项",
};

const ingestStatusLabel: Record<string, string> = {
  processing: "处理中",
  pending_confirmation: "待业务确认",
  completed: "已完成",
  failed: "处理失败",
};

function ingestFailureLabel(errorType: string | null): string {
  if (errorType === "processing_timeout") return "处理超时";
  if (errorType?.includes("extract")) return "内容提取失败";
  if (errorType === "queue_unavailable") return "任务排队失败";
  if (errorType?.includes("storage")) return "临时文件处理失败";
  return "文件处理失败";
}

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
  return `${formatBeijingTime(point.observed_at)}，已完成作业 ${point.completed_jobs}，失败或部分失败作业 ${point.failed_jobs}，排队作业 ${point.queued_jobs}，索引失败存量 ${point.index_failed}，解析失败存量 ${point.parse_failed}`;
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
  if (status === "no_action") return "warning";
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
  const [llmUsage, setLLMUsage] = useState<LLMUsageAggregateItemDTO[]>([]);
  const [llmUsageState, setLLMUsageState] = useState<LoadState>("loading");
  const [failureFilter, setFailureFilter] = useState<FailureFilter>("all");
  const [retryIncludeSkipped, setRetryIncludeSkipped] = useState(false);
  const [retryIncludeNotIndexed, setRetryIncludeNotIndexed] = useState(false);
  const [opsLimit, setOpsLimit] = useState(50);
  const [opsBusy, setOpsBusy] = useState(false);
  const [opsBusyOperation, setOpsBusyOperation] = useState<string | null>(null);
  const [opsNote, setOpsNote] = useState<string | null>(null);
  const [opsFeedbackState, setOpsFeedbackState] = useState<ActionFeedbackState>("info");
  const [retryTarget, setRetryTarget] = useState<OpsIndexingFailedItemDTO | null>(null);
  const [targetBusy, setTargetBusy] = useState(false);
  const [targetError, setTargetError] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<IndexingJobSummaryDTO | null>(null);
  const ingestRequestRef = useRef(0);
  const opsRequestRef = useRef(0);
  const jobsRequestRef = useRef(0);
  const jobsFetchInFlightRef = useRef<Promise<IndexingJobSummaryDTO[]> | null>(null);
  const autoRefreshInFlightRef = useRef(false);
  const healthRequestRef = useRef(0);
  const llmUsageRequestRef = useRef(0);

  const loadIngest = useCallback(async () => {
    const requestId = ++ingestRequestRef.current;
    setIngestState("loading");
    try {
      const items = (await fetchAdminIngest()).items;
      if (ingestRequestRef.current !== requestId) return null;
      setIngestItems(items);
      setIngestState("ready");
      return items;
    } catch {
      if (ingestRequestRef.current !== requestId) return null;
      setIngestItems([]);
      setIngestState("error");
      return null;
    }
  }, []);

  const loadOpsIndex = useCallback(async () => {
    const requestId = ++opsRequestRef.current;
    setOpsState("loading");
    try {
      const index = await fetchOpsIndexing();
      if (opsRequestRef.current !== requestId) return null;
      setOpsIndex(index);
      setOpsState("ready");
      return index;
    } catch {
      if (opsRequestRef.current !== requestId) return null;
      setOpsIndex(null);
      setOpsState("error");
      return null;
    }
  }, []);

  const fetchJobsSerialized = useCallback(() => {
    const inFlight = jobsFetchInFlightRef.current;
    if (inFlight) return inFlight;

    const request = fetchIndexingJobs().then((response) => response.items);
    jobsFetchInFlightRef.current = request;
    void request.then(
      () => {
        if (jobsFetchInFlightRef.current === request) jobsFetchInFlightRef.current = null;
      },
      () => {
        if (jobsFetchInFlightRef.current === request) jobsFetchInFlightRef.current = null;
      },
    );
    return request;
  }, []);

  const loadOpsJobs = useCallback(async () => {
    const requestId = ++jobsRequestRef.current;
    setJobsState("loading");
    try {
      const items = await fetchJobsSerialized();
      if (jobsRequestRef.current !== requestId) return null;
      setOpsJobs(items);
      setJobsState("ready");
      return items;
    } catch {
      if (jobsRequestRef.current !== requestId) return null;
      setOpsJobs([]);
      setJobsState("error");
      return null;
    }
  }, [fetchJobsSerialized]);

  const loadHealth = useCallback(async () => {
    const requestId = ++healthRequestRef.current;
    setHealthState("loading");
    try {
      const nextHealth = await fetchIndexingHealth(24);
      if (healthRequestRef.current !== requestId) return null;
      setHealth(nextHealth);
      setHealthState("ready");
      return nextHealth;
    } catch {
      if (healthRequestRef.current !== requestId) return null;
      setHealth(null);
      setHealthState("error");
      return null;
    }
  }, []);

  const loadLLMUsage = useCallback(async () => {
    const requestId = ++llmUsageRequestRef.current;
    setLLMUsageState("loading");
    try {
      const response = await fetchLLMUsage(14);
      if (llmUsageRequestRef.current !== requestId) return null;
      setLLMUsage(response.items);
      setLLMUsageState("ready");
      return response.items;
    } catch {
      if (llmUsageRequestRef.current !== requestId) return null;
      setLLMUsage([]);
      setLLMUsageState("error");
      return null;
    }
  }, []);

  const refreshAll = useCallback(
    async (clearNote = true) => {
      if (clearNote) setOpsNote(null);
      await Promise.all([
        loadIngest(),
        loadOpsIndex(),
        loadOpsJobs(),
        loadHealth(),
        loadLLMUsage(),
      ]);
    },
    [loadHealth, loadIngest, loadLLMUsage, loadOpsIndex, loadOpsJobs],
  );

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  // 全局计数自动刷新：与作业轮询解耦，避免「解析处理中」等数字停留在旧值。
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "hidden" || autoRefreshInFlightRef.current) return;
      autoRefreshInFlightRef.current = true;
      void refreshAll(false).finally(() => {
        autoRefreshInFlightRef.current = false;
      });
    }, OPS_AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refreshAll]);

  const activeJob = opsJobs.find((job) => ["queued", "running"].includes(job.status));
  const activeJobId = activeJob?.job_id ?? null;
  const activeJobStatus = activeJob?.status ?? null;
  const activeJobOperation = activeJob?.operation_type ?? null;
  const activeOperation = opsBusyOperation ?? activeJobOperation;
  const actionLocked = opsBusy || activeJobId !== null || opsState !== "ready";
  const llmUsageTotals = llmUsage.reduce(
    (total, item) => ({
      requests: total.requests + item.request_count,
      tokens: total.tokens + item.total_tokens,
      hits: total.hits + item.cache_hits,
      misses: total.misses + item.cache_misses,
    }),
    { requests: 0, tokens: 0, hits: 0, misses: 0 },
  );

  useEffect(() => {
    if (!activeJobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof window.setTimeout> | null = null;
    let attempts = 0;

    const schedule = () => {
      if (
        cancelled ||
        timer !== null ||
        attempts >= JOB_POLL_MAX_ATTEMPTS ||
        document.visibilityState === "hidden"
      ) {
        return;
      }
      timer = window.setTimeout(() => {
        timer = null;
        void poll();
      }, JOB_POLL_INTERVAL_MS);
    };
    const poll = async () => {
      if (cancelled) return;
      if (document.visibilityState === "hidden") return;
      attempts += 1;
      const requestId = ++jobsRequestRef.current;
      setJobsState("loading");
      try {
        const jobs = await fetchJobsSerialized();
        if (cancelled) return;
        if (jobsRequestRef.current !== requestId) {
          schedule();
          return;
        }
        if (jobs.some((job) => ["queued", "running"].includes(job.status))) {
          setOpsJobs(jobs);
          setJobsState("ready");
          schedule();
          return;
        }
        await Promise.all([loadIngest(), loadOpsIndex(), loadHealth()]);
        if (cancelled || jobsRequestRef.current !== requestId) return;
        setOpsJobs(jobs);
        setJobsState("ready");
      } catch {
        if (cancelled || jobsRequestRef.current !== requestId) return;
        setOpsJobs([]);
        setJobsState("error");
      }
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        if (timer !== null) window.clearTimeout(timer);
        timer = null;
        return;
      }
      schedule();
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    schedule();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [activeJobId, activeJobStatus, fetchJobsSerialized, loadHealth, loadIngest, loadOpsIndex]);

  useEffect(
    () => () => {
      ingestRequestRef.current += 1;
      opsRequestRef.current += 1;
      jobsRequestRef.current += 1;
      healthRequestRef.current += 1;
    },
    [],
  );

  const recordJob = useCallback((job: IndexingJobSummaryDTO, operationLabel?: string) => {
    const label = operationLabel ?? safeJobOperation(job.operation_type);
    setOpsJobs((current) => [job, ...current.filter((item) => item.job_id !== job.job_id)]);
    setJobsState("ready");
    if (job.total_count === 0) {
      setOpsFeedbackState("info");
      setOpsNote(
        job.operation_type === "reparse"
          ? `${label}未找到可处理项：仅处理已索引、已有底座文档且解析失败或待解析的资产。`
          : `${label}未找到可处理项：本次没有符合条件的索引失败、未索引或已跳过资产。`,
      );
      return;
    }
    const isTerminal = ["completed", "completed_with_errors", "failed", "no_action"].includes(
      job.status,
    );
    setOpsFeedbackState(
      !isTerminal
        ? "submitted"
        : job.status === "completed"
          ? "success"
          : job.status === "completed_with_errors"
            ? "partial"
            : "error",
    );
    setOpsNote(
      isTerminal
        ? `${label}已到达终态：共 ${job.total_count} 项，成功 ${job.success_count} 项，失败 ${job.failed_count} 项，跳过 ${job.skipped_count} 项。`
        : `${label}请求已提交，共 ${job.total_count} 项；作业仍在排队或处理中，当前计数不是最终结果。`,
    );
  }, []);

  const handleBatchRetry = useCallback(async () => {
    if (actionLocked) return;
    setOpsBusy(true);
    setOpsBusyOperation("retry_index");
    setOpsNote(null);
    try {
      const statuses = ["index_failed"];
      if (retryIncludeSkipped) statuses.push("skipped");
      if (retryIncludeNotIndexed) statuses.push("not_indexed");
      recordJob(
        await triggerIndexingRetry({ scope: "all", statuses, limit: opsLimit }),
        "批量重试索引",
      );
      await refreshAll(false);
    } catch {
      setOpsFeedbackState("error");
      setOpsNote("批量重试未能发起，请稍后重试。");
    } finally {
      setOpsBusy(false);
      setOpsBusyOperation(null);
    }
  }, [actionLocked, opsLimit, recordJob, refreshAll, retryIncludeNotIndexed, retryIncludeSkipped]);

  const handleReparse = useCallback(async () => {
    if (actionLocked) return;
    setOpsBusy(true);
    setOpsBusyOperation("reparse");
    setOpsNote(null);
    try {
      recordJob(
        await triggerIndexingReparse({
          scope: "all",
          parse_statuses: ["failed", "pending"],
          limit: opsLimit,
        }),
        "重新解析",
      );
      await refreshAll(false);
    } catch {
      setOpsFeedbackState("error");
      setOpsNote("重新解析未能发起，请稍后重试。");
    } finally {
      setOpsBusy(false);
      setOpsBusyOperation(null);
    }
  }, [actionLocked, opsLimit, recordJob, refreshAll]);

  const handleTargetRetry = useCallback(async () => {
    if (!retryTarget || targetBusy) return;
    setTargetBusy(true);
    setTargetError(null);
    try {
      if (!retryTarget.retry_target) return;
      recordJob(await triggerTargetedIndexingRetry(retryTarget.retry_target), "单条索引重试");
      setRetryTarget(null);
      await refreshAll(false);
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
  }, [recordJob, refreshAll, retryTarget, targetBusy]);

  const ingestCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of ingestItems) counts.set(item.status, (counts.get(item.status) ?? 0) + 1);
    return counts;
  }, [ingestItems]);
  const failedIngestItems = useMemo(
    () => ingestItems.filter((item) => item.status === "failed"),
    [ingestItems],
  );

  const failedItems = useMemo(() => {
    const items = opsIndex?.recent_failed ?? [];
    return failureFilter === "all"
      ? items
      : items.filter((item) => item.diagnostic_category === failureFilter);
  }, [failureFilter, opsIndex]);
  const retryActionableCount = Math.min(
    opsLimit,
    (opsIndex?.counts.index_failed ?? 0) +
      (retryIncludeSkipped ? (opsIndex?.counts.skipped ?? 0) : 0) +
      (retryIncludeNotIndexed ? (opsIndex?.counts.not_indexed ?? 0) : 0),
  );
  const reparseActionableCount = Math.min(opsLimit, opsIndex?.reparse_actionable_count ?? 0);
  const headerActionIsReparse = retryActionableCount === 0 && reparseActionableCount > 0;
  const attentionCount =
    failedIngestItems.length +
    (opsIndex?.counts.index_failed ?? 0) +
    (opsIndex?.counts.parse_failed ?? 0) +
    (opsIndex?.counts.parse_stalled ?? 0);
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
    <ProductPage className="ao84-page admin-control-page">
      <PageHeader
        title="入库管理"
        description="优先恢复失败、卡住和待确认的入库与索引任务。"
        status={
          <StatusBadge
            tone={
              activeJob ? "info" : opsState === "error" || attentionCount ? "danger" : "success"
            }
            label={
              activeJob
                ? `${safeJobOperation(activeJob.operation_type)}${activeJob.status === "queued" ? "已排队" : "处理中"}`
                : opsState === "error"
                  ? "运行状态读取失败"
                  : attentionCount
                    ? `${attentionCount} 项待处置`
                    : "当前无失败任务"
            }
          />
        }
        actions={
          <div className="ao84-refresh-actions">
            <button
              className="btn-small-primary ao84-refresh"
              data-operation={headerActionIsReparse ? "reparse" : "retry_index"}
              onClick={() => void (headerActionIsReparse ? handleReparse() : handleBatchRetry())}
              disabled={
                actionLocked || (retryActionableCount === 0 && reparseActionableCount === 0)
              }
            >
              <RotateCw size={15} aria-hidden="true" />
              {activeOperation
                ? `正在执行：${safeJobOperation(activeOperation)}`
                : headerActionIsReparse
                  ? "重新解析"
                  : "批量重试索引"}
            </button>
            <button
              className="btn-icon"
              aria-label="刷新"
              title="刷新"
              onClick={() => void refreshAll(false)}
              disabled={opsBusy}
            >
              <RotateCw size={15} aria-hidden="true" />
            </button>
          </div>
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
                className={`ao84-health ${
                  opsIndex.counts.index_failed || opsIndex.counts.parse_failed
                    ? "is-warning"
                    : "is-clear"
                }`}
              >
                {opsIndex.counts.index_failed || opsIndex.counts.parse_failed ? (
                  <AlertTriangle size={18} aria-hidden="true" />
                ) : (
                  <CheckCircle2 size={18} aria-hidden="true" />
                )}
                <div>
                  <strong>
                    {opsIndex.counts.index_failed
                      ? `${opsIndex.counts.index_failed} 项索引失败`
                      : opsIndex.counts.parse_failed
                        ? `存在 ${opsIndex.counts.parse_failed} 项底座解析异常，可重新解析`
                        : "当前没有索引或解析失败项"}
                  </strong>
                  <span>
                    解析失败为安全可见性统计，其中 {opsIndex.reparse_actionable_count}{" "}
                    项符合重新解析条件
                  </span>
                </div>
              </div>
              <IndexDistribution counts={opsIndex.counts} className="ao84-index-grid" />
              <p className="ao84-index-note">
                {opsIndex.last_reconcile ? (
                  <>
                    上次对账 {formatBeijingTime(opsIndex.last_reconcile.observed_at)} · 本轮处理{" "}
                    {opsIndex.last_reconcile.processed} · 更新 {opsIndex.last_reconcile.updated} ·{" "}
                    <span
                      className={opsIndex.last_reconcile.failed ? "ao84-reconcile-bad" : undefined}
                    >
                      失败 {opsIndex.last_reconcile.failed}
                    </span>
                  </>
                ) : (
                  "尚未产生对账心跳"
                )}
                ；解析状态每 5 分钟与底座对账、页面每 60 秒自动刷新，长时间不变的
                「解析处理中」多为底座侧仍在重试。
              </p>
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
            {ingestState === "ready" && failedIngestItems.length > 0 && (
              <div className="ao84-ingest-failures" aria-label="入库失败恢复建议">
                {failedIngestItems.slice(0, 10).map((item) => (
                  <div key={item.id}>
                    <span>失败入库项</span>
                    <strong>{ingestFailureLabel(item.error_type)}</strong>
                    <span>{item.error_message ?? "文件内容无法完成处理"}</span>
                    <span>恢复建议：由创建人在上传队列中重试或移除失败项。</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="ao84-ingest-overview" aria-label="近 14 天模型用量">
            <div className="ao84-subhead">
              <BarChart3 size={16} aria-hidden="true" />
              <strong>模型用量</strong>
              <span>近 14 天安全聚合</span>
            </div>
            {llmUsageState === "loading" ? (
              <p>正在读取模型用量…</p>
            ) : llmUsageState === "error" ? (
              <p className="is-error">模型用量暂时无法加载。</p>
            ) : (
              <>
                <div className="ao84-ingest-counts">
                  <span>
                    <strong>{llmUsageTotals.requests}</strong>外部请求数
                  </span>
                  <span>
                    <strong>{llmUsageTotals.tokens}</strong>总 token
                  </span>
                  <span>
                    <strong>
                      {llmUsageTotals.hits + llmUsageTotals.misses
                        ? `${Math.round((llmUsageTotals.hits / (llmUsageTotals.hits + llmUsageTotals.misses)) * 100)}%`
                        : "0%"}
                    </strong>
                    缓存命中率
                  </span>
                </div>
                {llmUsage.length > 0 && (
                  <div className="ao84-ingest-failures" aria-label="按日和调用场景的模型用量">
                    {llmUsage.map((item) => (
                      <div key={`${item.day}:${item.scenario}`}>
                        <span>{item.day}</span>
                        <strong>
                          {item.scenario === "content_generation" ? "内容生成" : "目录分类"}
                        </strong>
                        <span>
                          {item.request_count} 次外部请求 · {item.total_tokens} token
                        </span>
                        <span>缓存命中率 {Math.round(item.cache_hit_rate * 100)}%</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          <div className="ao84-actions" aria-label="索引批量操作">
            <div className="ao84-action-explanation">
              <strong>批量重试索引</strong>
              <span>处理索引失败，可选未索引或已跳过；当前最多 {retryActionableCount} 项。</span>
              <strong>重新解析</strong>
              <span>
                仅处理已索引、已有底座文档且解析失败或待解析的资产；当前最多{" "}
                {reparseActionableCount} 项。
              </span>
            </div>
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
                className="btn-small"
                disabled={actionLocked}
                onClick={() => void handleBatchRetry()}
              >
                <RotateCw size={15} aria-hidden="true" />
                {activeOperation
                  ? `正在执行：${safeJobOperation(activeOperation)}`
                  : `再次执行批量重试（${retryActionableCount} 项）`}
              </button>
              <button
                className="btn-small"
                disabled={actionLocked}
                onClick={() => void handleReparse()}
              >
                <FileSearch size={15} aria-hidden="true" />
                {activeOperation
                  ? `正在执行：${safeJobOperation(activeOperation)}`
                  : `重新解析（${reparseActionableCount} 项）`}
              </button>
            </div>
          </div>

          {opsNote && (
            <ActionFeedback
              state={opsFeedbackState}
              title={
                opsFeedbackState === "error"
                  ? "操作未发起"
                  : opsFeedbackState === "partial"
                    ? "部分完成"
                    : opsFeedbackState === "success"
                      ? "作业已完成"
                      : opsFeedbackState === "submitted"
                        ? "请求已提交"
                        : "操作提示"
              }
              description={opsNote}
            />
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
                    <button
                      type="button"
                      className="ao84-job-detail"
                      onClick={() => setSelectedJob(job)}
                    >
                      查看详情
                    </button>
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
                  <th>对象与原因</th>
                  <th>当前状态</th>
                  <th>下一步</th>
                  <th>操作</th>
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
                        <span className={`ao84-status is-${failureTone(item)}`}>索引失败</span>
                      </td>
                      <td>
                        <span>{item.retry_eligible ? "重新尝试索引" : "核查配置或内容"}</span>
                        <small>{formatBeijingTime(item.updated_at)}</small>
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

          <details className="ao85-runtime-details">
            <summary>
              <span>运行健康与近 24 小时趋势</span>
              <small>次级诊断</small>
            </summary>
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
                                <span>解析失败存量 {point.parse_failed}</span>
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
          </details>
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
        errorDescription={targetError}
        onConfirm={() => void handleTargetRetry()}
        onCancel={() => {
          setRetryTarget(null);
          setTargetError(null);
        }}
      />

      <DetailDrawer
        open={selectedJob !== null}
        title="索引维护作业"
        description="这里仅展示可公开的进度摘要；关闭后列表筛选与滚动上下文仍会保留。"
        onClose={() => setSelectedJob(null)}
        footer={
          <Button variant="secondary" onClick={() => setSelectedJob(null)}>
            返回作业列表
          </Button>
        }
      >
        {selectedJob && (
          <OperationStatusCard
            status={operationStatusFromJob(selectedJob.status)}
            title={safeJobOperation(selectedJob.operation_type)}
            description={
              selectedJob.status === "queued" || selectedJob.status === "running"
                ? "请求已被服务端接受，但尚未达到最终完成状态。"
                : "作业已到达终态，请依据下方安全计数决定是否继续处理失败项。"
            }
            counts={[
              { label: "总计", value: selectedJob.total_count },
              { label: "成功", value: selectedJob.success_count, tone: "success" },
              { label: "失败", value: selectedJob.failed_count, tone: "danger" },
              { label: "跳过", value: selectedJob.skipped_count, tone: "warning" },
            ]}
            updatedAt={
              selectedJob.finished_at || selectedJob.started_at || selectedJob.requested_at
                ? formatBeijingTime(
                    selectedJob.finished_at || selectedJob.started_at || selectedJob.requested_at,
                  )
                : undefined
            }
            nextStep={
              selectedJob.status === "queued" || selectedJob.status === "running"
                ? "系统会继续刷新作业状态，请勿把本次 HTTP 返回当作完成。"
                : selectedJob.failed_count > 0
                  ? "检查失败任务摘要，修正后再发起重试。"
                  : "无需后续操作。"
            }
            compact
          />
        )}
      </DetailDrawer>
    </ProductPage>
  );
}
