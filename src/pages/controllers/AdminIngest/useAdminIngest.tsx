import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  detectIndexSubmissionInterruptions,
  fetchIndexingHealth,
  fetchIndexingJobs,
  fetchLLMUsage,
  fetchOpsIndexing,
  recoverProcessingTimeouts,
  triggerIndexingReparse,
  triggerIndexingRetry,
  triggerTargetedIndexingRetry,
} from "../../../api/admin";
import { ApiError } from "../../../api/http";
import { fetchAdminIngest } from "../../../api/ingest";
import { type ActionFeedbackState } from "../../../components/ActionFeedback";
import type { AdminIngestItemDTO } from "../../../types/ingest";
import type {
  IndexingHealthDTO,
  IndexingJobSummaryDTO,
  LLMUsageAggregateItemDTO,
  OpsIndexingDTO,
  OpsIndexingFailedItemDTO,
  ProcessingTimeoutRecoveryDTO,
} from "../../../types/ops";
import { formatBeijingTime } from "../../../utils/time";
import {
  DEFAULT_VISIBLE_RECOVERY_ITEMS,
  FailureFilter,
  healthLabels,
  JOB_POLL_INTERVAL_MS,
  JOB_POLL_MAX_ATTEMPTS,
  LoadState,
  OPS_AUTO_REFRESH_MS,
  recoveryStatePriority,
  safeJobOperation,
  trendTickIndexes,
} from "./model";

export function useAdminIngest() {
  const [ingestItems, setIngestItems] = useState<AdminIngestItemDTO[]>([]);
  const [ingestState, setIngestState] = useState<LoadState>("loading");
  const [opsIndex, setOpsIndex] = useState<OpsIndexingDTO | null>(null);
  const [opsState, setOpsState] = useState<LoadState>("loading");
  const [opsJobs, setOpsJobs] = useState<IndexingJobSummaryDTO[]>([]);
  const [jobsState, setJobsState] = useState<LoadState>("loading");
  const [jobTypeFilter, setJobTypeFilter] = useState("all");
  const [jobStatusFilter, setJobStatusFilter] = useState("all");
  const [jobDateFilter, setJobDateFilter] = useState("");
  const [jobPage, setJobPage] = useState(1);
  const [jobFiltersOpen, setJobFiltersOpen] = useState(false);
  const [showAllIngestFailures, setShowAllIngestFailures] = useState(false);
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
  const [selectedJobSnapshot, setSelectedJob] = useState<IndexingJobSummaryDTO | null>(null);
  const selectedJob =
    opsJobs.find((job) => job.job_id === selectedJobSnapshot?.job_id) ?? selectedJobSnapshot;
  const [showAllRecoveryItems, setShowAllRecoveryItems] = useState(false);
  const [timeoutRecovery, setTimeoutRecovery] = useState<ProcessingTimeoutRecoveryDTO | null>(null);
  const [timeoutRecoveryBusy, setTimeoutRecoveryBusy] = useState(false);
  const [timeoutRecoveryError, setTimeoutRecoveryError] = useState<string | null>(null);
  const [recoveryListBusy, setRecoveryListBusy] = useState(false);
  const [workspace, setWorkspace] = useState<"recovery" | "jobs" | "runtime">("recovery");
  const showAllRecoveryItemsRef = useRef(false);
  const ingestRequestRef = useRef(0);
  const opsRequestRef = useRef(0);
  const jobsRequestRef = useRef(0);
  const jobsFetchInFlightRef = useRef<Promise<IndexingJobSummaryDTO[]> | null>(null);
  const autoRefreshInFlightRef = useRef(false);
  const healthRequestRef = useRef(0);
  const llmUsageRequestRef = useRef(0);

  const loadIngest = useCallback(async () => {
    const requestId = ++ingestRequestRef.current;
    setIngestState((current) => (current === "ready" ? current : "loading"));
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

  const loadOpsIndex = useCallback(async (includeAll = showAllRecoveryItemsRef.current) => {
    const requestId = ++opsRequestRef.current;
    setOpsState((current) => (current === "ready" ? current : "loading"));
    try {
      const index = await fetchOpsIndexing(includeAll);
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

  const toggleAllRecoveryItems = async () => {
    if (showAllRecoveryItems) {
      showAllRecoveryItemsRef.current = false;
      setShowAllRecoveryItems(false);
      return;
    }
    setRecoveryListBusy(true);
    const requestId = ++opsRequestRef.current;
    try {
      const index = await fetchOpsIndexing(true);
      if (opsRequestRef.current !== requestId) return;
      setOpsIndex(index);
      setOpsState("ready");
      showAllRecoveryItemsRef.current = true;
      setShowAllRecoveryItems(true);
    } catch {
      if (opsRequestRef.current !== requestId) return;
      setOpsFeedbackState("error");
      setOpsNote("全部恢复候选暂时无法加载，请稍后重试。");
    } finally {
      setRecoveryListBusy(false);
    }
  };

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
    setJobsState((current) => (current === "ready" ? current : "loading"));
    try {
      const items = await fetchJobsSerialized();
      if (jobsRequestRef.current !== requestId) return null;
      setOpsJobs(items);
      setJobsState("ready");
      return items;
    } catch {
      if (jobsRequestRef.current !== requestId) return null;
      setJobsState("error");
      return null;
    }
  }, [fetchJobsSerialized]);

  const loadHealth = useCallback(async () => {
    const requestId = ++healthRequestRef.current;
    setHealthState((current) => (current === "ready" ? current : "loading"));
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
    setLLMUsageState((current) => (current === "ready" ? current : "loading"));
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

  const handleDetectInterruptions = async () => {
    if (opsBusy) return;
    setOpsBusy(true);
    setOpsFeedbackState("submitted");
    setOpsNote("正在识别超过安全阈值且没有新鲜作业的索引提交…");
    try {
      const result = await detectIndexSubmissionInterruptions();
      await refreshAll(false);
      setOpsFeedbackState(result.exceptions ? "partial" : "success");
      setOpsNote(
        `中断识别完成：扫描 ${result.scanned} 项，识别 ${result.identified} 项，跳过新鲜作业 ${result.skipped_fresh_jobs} 项${result.exceptions ? `，异常 ${result.exceptions} 项` : ""}。`,
      );
    } catch {
      setOpsFeedbackState("error");
      setOpsNote("中断识别未完成，请稍后重试；现有资产与索引状态未被改写。");
    } finally {
      setOpsBusy(false);
    }
  };

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
    const isTerminal = [
      "submitted_pending_index",
      "completed",
      "completed_with_errors",
      "failed",
      "no_action",
    ].includes(job.status);
    const pending = job.pending_count ?? 0;
    setOpsFeedbackState(
      !isTerminal || job.status === "submitted_pending_index"
        ? "submitted"
        : job.status === "completed"
          ? "success"
          : job.status === "completed_with_errors"
            ? "partial"
            : "error",
    );
    setOpsNote(
      isTerminal && pending > 0
        ? `${label}提交处理已结束：共 ${job.total_count} 项，已完成 ${job.success_count} 项，提交时待索引 ${pending} 项，失败 ${job.failed_count} 项，跳过 ${job.skipped_count} 项。是否可检索以资产当前索引状态为准，请等待自动对账，勿重复提交。`
        : isTerminal
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
      const job = await triggerIndexingRetry({ scope: "all", statuses, limit: opsLimit });
      recordJob(job, "恢复索引");
      await refreshAll(false);
    } catch (error) {
      setOpsFeedbackState("error");
      setOpsNote(
        error instanceof ApiError && error.deniedReason === "index_recovery_foundation_unavailable"
          ? "知识底座暂不可用，恢复未发起。请先恢复底座连接后重试。"
          : "索引恢复未能发起，请稍后重试。",
      );
    } finally {
      setOpsBusy(false);
      setOpsBusyOperation(null);
    }
  }, [actionLocked, opsLimit, recordJob, refreshAll, retryIncludeNotIndexed, retryIncludeSkipped]);

  const handleReparse = useCallback(async () => {
    if (actionLocked || !opsIndex?.reparse_actionable_count) return;
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
  }, [actionLocked, opsIndex?.reparse_actionable_count, opsLimit, recordJob, refreshAll]);

  const handleTargetRetry = useCallback(async () => {
    if (!retryTarget || targetBusy) return;
    setTargetBusy(true);
    setTargetError(null);
    try {
      if (!retryTarget.retry_target) return;
      recordJob(await triggerTargetedIndexingRetry(retryTarget.retry_target), "单条索引恢复");
      setRetryTarget(null);
      await refreshAll(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        setTargetError("当前身份无权执行此操作。");
      } else if (error instanceof ApiError && error.status === 409) {
        setTargetError(
          error.deniedReason === "index_recovery_foundation_unavailable"
            ? "知识底座暂不可用，恢复未发起。请先恢复底座连接后重试。"
            : "任务状态已变化或正在执行，请刷新后重试。",
        );
      } else {
        setTargetError("单项恢复未能发起，请稍后重试。");
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

  const recoveryItems = useMemo(() => {
    const items = [...(opsIndex?.recovery_items ?? opsIndex?.recent_failed ?? [])];
    return items.sort((left, right) => {
      const stateDifference =
        (recoveryStatePriority[left.recovery_state ?? ""] ?? 9) -
        (recoveryStatePriority[right.recovery_state ?? ""] ?? 9);
      if (stateDifference !== 0) return stateDifference;
      const severityDifference =
        (left.severity === "critical" ? 0 : left.severity === "warning" ? 1 : 2) -
        (right.severity === "critical" ? 0 : right.severity === "warning" ? 1 : 2);
      if (severityDifference !== 0) return severityDifference;
      return (right.wait_seconds ?? 0) - (left.wait_seconds ?? 0);
    });
  }, [opsIndex]);
  const filteredRecoveryItems = useMemo(
    () =>
      failureFilter === "all"
        ? recoveryItems
        : recoveryItems.filter((item) => item.diagnostic_category === failureFilter),
    [failureFilter, recoveryItems],
  );
  const failedItems = showAllRecoveryItems
    ? filteredRecoveryItems
    : filteredRecoveryItems.slice(0, DEFAULT_VISIBLE_RECOVERY_ITEMS);
  const retryActionableCount = Math.min(
    opsLimit,
    (opsIndex?.counts.index_failed ?? 0) +
      (retryIncludeSkipped ? (opsIndex?.counts.skipped ?? 0) : 0) +
      (retryIncludeNotIndexed ? (opsIndex?.counts.not_indexed ?? 0) : 0),
  );
  const reparseActionableCount = Math.min(opsLimit, opsIndex?.reparse_actionable_count ?? 0);
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
          detail: health.worker.message,
        },
        {
          label: "定时调度",
          status: health.beat.status,
          lastHeartbeat: health.beat.last_heartbeat_at,
          detail: health.beat.message,
        },
        {
          label: "作业队列",
          status: health.queue.status,
          lastHeartbeat: null,
          detail: `等待 ${health.queue.queued_count} 项。${health.queue.message}`,
        },
      ]
    : [];
  const recoverySummary = opsIndex?.recovery_summary ?? {
    interrupted: opsIndex?.counts.parse_stalled ?? 0,
    needs_recovery:
      (opsIndex?.counts.index_failed ?? 0) +
      (opsIndex?.counts.not_indexed ?? 0) +
      (opsIndex?.counts.skipped ?? 0),
    processing: opsIndex?.counts.indexing ?? 0,
    searchable: 0,
  };
  const displayedNeedsRecovery = recoverySummary.needs_recovery;
  const displayedProcessing = recoverySummary.processing;
  const submissionProcessing = opsIndex?.counts.submission_processing ?? displayedProcessing;
  const parseInProgress =
    opsIndex?.counts.parse_in_progress ??
    (opsIndex?.counts.parse_pending ?? 0) + (opsIndex?.counts.parse_processing ?? 0);
  const submissionInterrupted = recoverySummary.submission_interrupted ?? 0;
  const parseInterrupted =
    recoverySummary.parse_interrupted ??
    Math.max(0, recoverySummary.interrupted - submissionInterrupted);
  const runtimeAttentionCount =
    failedIngestItems.length +
    (opsIndex?.counts.parse_failed ?? 0) +
    (opsIndex?.counts.kb_init_failed ?? 0);
  const foundationStatus = opsIndex?.last_reconcile
    ? opsIndex.last_reconcile.failed > 0
      ? "索引核对存在异常"
      : "最近索引核对正常"
    : "暂无索引核对记录";
  const foundationUpdatedAt = opsIndex?.last_reconcile?.observed_at
    ? formatBeijingTime(opsIndex.last_reconcile.observed_at)
    : "—";

  const filteredJobs = opsJobs.filter(
    (job) =>
      (jobTypeFilter === "all" || job.operation_type === jobTypeFilter) &&
      (jobStatusFilter === "all" || job.status === jobStatusFilter) &&
      (!jobDateFilter ||
        (job.requested_at && formatBeijingTime(job.requested_at).slice(0, 10) === jobDateFilter)),
  );
  const jobPageCount = Math.max(1, Math.ceil(filteredJobs.length / 10));
  const currentJobPage = Math.min(jobPage, jobPageCount);

  const showRuntimeDetails = () => setWorkspace("runtime");

  const inspectProcessingTimeouts = async () => {
    setTimeoutRecoveryBusy(true);
    setTimeoutRecoveryError(null);
    setTimeoutRecovery(null);
    try {
      setTimeoutRecovery(await recoverProcessingTimeouts());
    } catch (error) {
      setTimeoutRecoveryError(error instanceof ApiError ? error.message : "超时任务预检失败");
    } finally {
      setTimeoutRecoveryBusy(false);
    }
  };

  const confirmProcessingTimeoutRecovery = async () => {
    if (
      timeoutRecoveryBusy ||
      !timeoutRecovery?.dry_run ||
      !timeoutRecovery.preflight.ready ||
      timeoutRecovery.candidates === 0
    )
      return;
    if (!window.confirm("确认恢复最多 3 条已通过物理源文件与运行环境预检的超时任务？")) return;
    setTimeoutRecoveryBusy(true);
    setTimeoutRecoveryError(null);
    try {
      setTimeoutRecovery(
        await recoverProcessingTimeouts({
          dry_run: false,
          confirm: true,
          limit: 3,
          expected_oom_kill_count: timeoutRecovery.preflight.oom_kill_count,
        }),
      );
      await loadIngest();
    } catch (error) {
      setTimeoutRecovery(null);
      setTimeoutRecoveryError(
        error instanceof ApiError
          ? error.message
          : "未能确认恢复结果，请重新检查任务状态后再操作。",
      );
    } finally {
      setTimeoutRecoveryBusy(false);
    }
  };
  return {
    refreshAll,
    opsBusy,
    workspace,
    setWorkspace,
    runtimeAttentionCount,
    opsNote,
    opsFeedbackState,
    opsState,
    opsIndex,
    displayedNeedsRecovery,
    recoverySummary,
    submissionInterrupted,
    parseInterrupted,
    submissionProcessing,
    parseInProgress,
    showRuntimeDetails,
    jobFiltersOpen,
    setJobFiltersOpen,
    jobTypeFilter,
    jobStatusFilter,
    jobDateFilter,
    setJobTypeFilter,
    setJobPage,
    setJobStatusFilter,
    setJobDateFilter,
    opsJobs,
    jobsState,
    loadOpsJobs,
    filteredJobs,
    currentJobPage,
    setSelectedJob,
    jobPageCount,
    health,
    healthState,
    healthCards,
    trendMax,
    visibleTrendTicks,
    foundationStatus,
    foundationUpdatedAt,
    handleDetectInterruptions,
    ingestState,
    ingestItems,
    ingestCounts,
    failedIngestItems,
    showAllIngestFailures,
    setShowAllIngestFailures,
    timeoutRecovery,
    timeoutRecoveryError,
    inspectProcessingTimeouts,
    timeoutRecoveryBusy,
    confirmProcessingTimeoutRecovery,
    llmUsageState,
    llmUsageTotals,
    llmUsage,
    toggleAllRecoveryItems,
    recoveryListBusy,
    showAllRecoveryItems,
    failureFilter,
    setFailureFilter,
    showAllRecoveryItemsRef,
    setShowAllRecoveryItems,
    reparseActionableCount,
    retryActionableCount,
    retryIncludeSkipped,
    setRetryIncludeSkipped,
    retryIncludeNotIndexed,
    setRetryIncludeNotIndexed,
    opsLimit,
    setOpsLimit,
    activeOperation,
    handleBatchRetry,
    actionLocked,
    handleReparse,
    filteredRecoveryItems,
    failedItems,
    setTargetError,
    setRetryTarget,
    retryTarget,
    targetBusy,
    handleTargetRetry,
    targetError,
    selectedJob,
  };
}
export type AdminIngestController = ReturnType<typeof useAdminIngest>;
