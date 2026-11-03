import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FileSearch,
  ListFilter,
  RotateCw,
} from "lucide-react";
import {
  DEFAULT_VISIBLE_RECOVERY_ITEMS,
  diagnosticLabels,
  FailureFilter,
  failureTone,
  recoveryStateLabel,
  recoveryWaitLabel,
  safeFailureMessage,
  safeJobOperation,
} from "./model";
import type { AdminIngestController } from "./useAdminIngest";
export function IngestRecoveryQueue({ controller }: { controller: AdminIngestController }) {
  const {
    refreshAll,
    opsBusy,
    opsState,
    displayedNeedsRecovery,
    showRuntimeDetails,
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
  } = controller;
  return (
    <>
      <section
        id="ingest-failures"
        tabIndex={-1}
        className="ao84-panel ao84-failures"
        aria-labelledby="ao84-failures-title"
      >
        <header className="irc-task-head">
          <div>
            <h2 id="ao84-failures-title">待恢复任务</h2>
          </div>
          <div className="irc-task-controls">
            <span className="irc-candidate-count">待恢复 {displayedNeedsRecovery} 项</span>
            {displayedNeedsRecovery > DEFAULT_VISIBLE_RECOVERY_ITEMS && (
              <button
                type="button"
                className="btn-small"
                onClick={() => void toggleAllRecoveryItems()}
                disabled={recoveryListBusy}
              >
                {recoveryListBusy
                  ? "正在读取全部候选…"
                  : showAllRecoveryItems
                    ? "收起为优先项"
                    : `查看全部 ${displayedNeedsRecovery} 项`}
              </button>
            )}
            <label className="ao84-failure-filter">
              <ListFilter size={15} aria-hidden="true" />
              <span className="sr-only">诊断类别筛选</span>
              <select
                value={failureFilter}
                onChange={(event) => {
                  setFailureFilter(event.target.value as FailureFilter);
                  showAllRecoveryItemsRef.current = false;
                  setShowAllRecoveryItems(false);
                }}
              >
                <option value="all">全部类别</option>
                {Object.entries(diagnosticLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </header>

        {(displayedNeedsRecovery > 0 || reparseActionableCount > 0) && (
          <div className="ingest-recovery-actions" aria-label="索引恢复操作">
            <details className="ingest-disclosure">
              <summary>恢复范围与处理上限</summary>
              <div className="ao84-action-explanation">
                <strong>恢复索引</strong>
                <span>
                  处理索引提交中断或索引失败，可选未索引或已跳过；当前最多 {retryActionableCount}{" "}
                  项。
                </span>
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
            </details>
            <div className="ao84-action-buttons">
              <button
                type="button"
                className="btn-small-primary"
                aria-label={
                  activeOperation
                    ? `正在执行：${safeJobOperation(activeOperation)}`
                    : `恢复索引（${retryActionableCount} 项）`
                }
                onClick={() => void handleBatchRetry()}
                disabled={actionLocked || retryActionableCount === 0}
              >
                <RotateCw size={15} aria-hidden="true" />
                {activeOperation
                  ? `正在执行：${safeJobOperation(activeOperation)}`
                  : `恢复索引（${retryActionableCount} 项）`}
              </button>
              <button
                className="btn-small"
                disabled={actionLocked || reparseActionableCount === 0}
                onClick={() => void handleReparse()}
              >
                <FileSearch size={15} aria-hidden="true" />
                {activeOperation
                  ? `正在执行：${safeJobOperation(activeOperation)}`
                  : `重新解析（${reparseActionableCount} 项）`}
              </button>
            </div>
            <p className="ingest-batch-scope">
              批量操作覆盖全部范围，不受类别筛选影响；处理单份资料请使用下方任务详情。
            </p>
          </div>
        )}
        <div className="irc-task-list-wrap">
          {opsState === "loading" && (
            <div className="ao84-table-state" role="status">
              正在读取恢复任务…
            </div>
          )}
          {opsState === "error" && (
            <div className="ao84-table-state is-error" role="alert">
              <AlertTriangle size={21} aria-hidden="true" />
              <strong>恢复任务暂时无法加载</strong>
              <button
                type="button"
                className="btn-small"
                onClick={() => void refreshAll(false)}
                disabled={opsBusy}
              >
                <RotateCw size={14} aria-hidden="true" />
                刷新
              </button>
            </div>
          )}
          {opsState === "ready" && filteredRecoveryItems.length === 0 && (
            <div className="ao84-table-state irc-empty-state">
              <CheckCircle2 size={22} aria-hidden="true" />
              <strong>
                {failureFilter === "all" ? "当前没有待恢复索引" : "当前筛选下没有任务"}
              </strong>
              <span>
                当前没有符合条件的恢复任务。可在作业记录查看处理结果，在运行诊断检查服务状态。
              </span>
              <button
                type="button"
                className="btn-small"
                onClick={() =>
                  failureFilter === "all" ? showRuntimeDetails() : setFailureFilter("all")
                }
                disabled={opsBusy}
              >
                {failureFilter === "all" ? (
                  <Clock3 size={14} aria-hidden="true" />
                ) : (
                  <ListFilter size={14} aria-hidden="true" />
                )}
                {failureFilter === "all" ? "查看运行详情" : "查看全部类别"}
              </button>
            </div>
          )}
          {opsState === "ready" && failedItems.length > 0 && (
            <ul className="irc-task-list" aria-label="待恢复任务列表">
              {failedItems.map((item) => (
                <li key={item.retry_target ?? `${item.scope}-${item.updated_at}`}>
                  <div className="irc-task-object">
                    <AlertTriangle size={17} aria-hidden="true" />
                    <div>
                      <strong>{item.title}</strong>
                      <span>{safeFailureMessage(item)}</span>
                    </div>
                  </div>
                  <div className="irc-task-fact">
                    <span>当前状态</span>
                    <strong className={`ao84-status is-${failureTone(item)}`}>
                      {recoveryStateLabel(item)}
                    </strong>
                  </div>
                  <div className="irc-task-fact">
                    <span>等待时长</span>
                    <strong>{recoveryWaitLabel(item.wait_seconds)}</strong>
                  </div>
                  <div className="irc-task-fact">
                    <span>下一步</span>
                    <strong>{item.retry_eligible ? "恢复索引" : "核查配置或内容"}</strong>
                  </div>
                  <button
                    type="button"
                    className="btn-small ao85-target-retry"
                    onClick={() => {
                      setTargetError(null);
                      setRetryTarget(item);
                    }}
                  >
                    查看详情
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </>
  );
}
