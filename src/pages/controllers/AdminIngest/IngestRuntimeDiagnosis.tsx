import { IngestTools } from "../../../components/operations/IngestTools";
import { formatBeijingTime } from "../../../utils/time";
import { BarChart3, FileSearch, HeartPulse } from "lucide-react";
import {
  healthLabels,
  ingestFailureLabel,
  ingestStatusLabel,
  timeoutRecoveryStopLabel,
  trendPointLabel,
  trendTickLabel,
} from "./model";
import type { AdminIngestController } from "./useAdminIngest";
export function IngestRuntimeDiagnosis({ controller }: { controller: AdminIngestController }) {
  const {
    opsBusy,
    opsState,
    opsIndex,
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
  } = controller;
  return (
    <section
      id="ingest-runtime"
      tabIndex={-1}
      className="irc-runtime-details"
      aria-label="运行诊断"
    >
      <IngestTools onJobCreated={() => void controller.loadOpsJobs()} />
      <section className="ao85-runtime-details">
        <section className="ao85-runtime" aria-labelledby="ao85-runtime-title">
          <div className="ao85-runtime-head">
            <div>
              <HeartPulse size={17} aria-hidden="true" />
              <h3 id="ao85-runtime-title">运行健康</h3>
            </div>
            <span>
              {health ? `更新于 ${formatBeijingTime(health.generated_at)}` : "等待检查结果"}
            </span>
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
              <details className="ingest-disclosure">
                <summary>近 24 小时运行趋势</summary>
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
              </details>
            </>
          )}
        </section>
      </section>
      <section className="ingest-diagnostic-checks" aria-label="索引检查">
        <div>
          <h3>索引检查</h3>
          <p>
            {opsState === "error" ? "索引检查记录暂时无法加载" : foundationStatus}
            {opsIndex?.last_reconcile && ` · ${foundationUpdatedAt}`}
          </p>
        </div>
        <button
          className="btn-small"
          type="button"
          onClick={() => void handleDetectInterruptions()}
          disabled={opsBusy}
        >
          <FileSearch size={15} aria-hidden="true" />
          识别中断索引
        </button>
        <p>识别超过安全等待时间的中断任务，将符合条件的资料加入待恢复列表；不会直接恢复索引。</p>
      </section>
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
            {failedIngestItems.slice(0, showAllIngestFailures ? undefined : 10).map((item) => (
              <div key={item.id}>
                <span>
                  失败入库项 · 创建于{" "}
                  {item.created_at ? formatBeijingTime(item.created_at) : "未记录"}
                </span>
                <strong>{ingestFailureLabel(item.error_type)}</strong>
                <span>{item.error_message ?? "文件内容无法完成处理"}</span>
                <span>恢复建议：由创建人在上传队列中重试或移除失败项。</span>
              </div>
            ))}
            {failedIngestItems.length > 10 && (
              <button
                className="btn-small"
                onClick={() => setShowAllIngestFailures(!showAllIngestFailures)}
              >
                {showAllIngestFailures
                  ? "收起失败项"
                  : `查看已加载的全部 ${failedIngestItems.length} 项失败`}
              </button>
            )}
            <p>
              此处仅展示错误摘要和创建时间，不提供原文或文件名。请由创建人在上传队列中定位并处理。
            </p>
          </div>
        )}
        <details className="ingest-disclosure">
          <summary>历史处理超时恢复</summary>
          <div className="ao84-subhead">
            <span>默认仅预检；每批最多 3 条，批次间隔至少 15 秒</span>
          </div>
          <div className="ao84-ingest-counts" aria-live="polite">
            <span>
              <strong>{timeoutRecovery?.candidates ?? "—"}</strong>源文件完整候选
            </span>
            <span>
              <strong>{timeoutRecovery?.source_unavailable ?? "—"}</strong>需重新上传
            </span>
            <span>
              <strong>
                {timeoutRecovery ? (timeoutRecovery.preflight.ready ? "通过" : "未通过") : "未检查"}
              </strong>
              运行预检
            </span>
          </div>
          {timeoutRecovery && (
            <div className="ingest-preflight" aria-label="超时恢复检查结果" role="status">
              <ul>
                <li>任务队列连接：{timeoutRecovery.preflight.redis_ready ? "正常" : "不可用"}</li>
                <li>
                  文档处理进程：
                  {timeoutRecovery.preflight.ocr_worker_ready ? "正常" : "不可用"}
                </li>
                <li>
                  队列容量：
                  {timeoutRecovery.preflight.queue_within_budget ? "可接收任务" : "已达上限"}
                </li>
              </ul>
              {!timeoutRecovery.preflight.ready && (
                <p>
                  暂不可恢复：{timeoutRecoveryStopLabel(timeoutRecovery.preflight.reason)}
                  。请处理后重新检查。
                </p>
              )}
              {!timeoutRecovery.dry_run && (
                <p>
                  本批已入队 {timeoutRecovery.enqueued} 条，冲突 {timeoutRecovery.conflicts}{" "}
                  条。入队不代表处理完成，请在入库运行概览查看后续状态。
                </p>
              )}
              {timeoutRecovery.source_unavailable > 0 && (
                <p>{timeoutRecovery.source_unavailable} 条源文件不可用，需由创建人重新上传。</p>
              )}
              {timeoutRecovery.next_batch_not_before && (
                <p>
                  下一批最早可检查时间：
                  {formatBeijingTime(timeoutRecovery.next_batch_not_before)}
                  。到时请重新检查，确认可恢复数量。
                </p>
              )}
            </div>
          )}
          {timeoutRecoveryError && <p className="is-error">{timeoutRecoveryError}</p>}
          {timeoutRecovery?.preflight.ready && timeoutRecovery.candidates === 0 && (
            <p>检查已通过，当前没有符合条件的超时任务，无需恢复。</p>
          )}
          {timeoutRecovery?.stopped && (
            <p className="is-error">
              恢复已停止：{timeoutRecoveryStopLabel(timeoutRecovery.stop_reason)}
            </p>
          )}
          <div className="ao84-refresh-actions">
            <button
              className="btn-small"
              type="button"
              onClick={() => void inspectProcessingTimeouts()}
              disabled={timeoutRecoveryBusy}
            >
              {timeoutRecoveryBusy ? "检查中…" : "检查超时任务"}
            </button>
            <button
              className="btn-small-primary"
              type="button"
              onClick={() => void confirmProcessingTimeoutRecovery()}
              disabled={
                timeoutRecoveryBusy ||
                !timeoutRecovery?.dry_run ||
                !timeoutRecovery.preflight.ready ||
                timeoutRecovery.candidates === 0
              }
            >
              二次确认并恢复最多 3 条
            </button>
          </div>
        </details>
      </div>

      <details className="ao84-ingest-overview ingest-disclosure" aria-label="近 14 天模型用量">
        <summary>模型用量 · 近 14 天</summary>
        <div className="ao84-subhead">
          <span>按天与调用场景汇总</span>
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
                    : "暂无数据"}
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
                    <span>
                      缓存命中率{" "}
                      {item.cache_hits + item.cache_misses
                        ? `${Math.round(item.cache_hit_rate * 100)}%`
                        : "暂无数据"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </details>
    </section>
  );
}
