import { AlertTriangle, CheckCircle2 } from "lucide-react";
import type { AdminIngestController } from "./useAdminIngest";
export function IngestRecoverySummary({ controller }: { controller: AdminIngestController }) {
  const {
    opsState,
    opsIndex,
    displayedNeedsRecovery,
    recoverySummary,
    submissionInterrupted,
    parseInterrupted,
    submissionProcessing,
    parseInProgress,
    showRuntimeDetails,
  } = controller;
  return (
    <section
      id="ingest-overview"
      tabIndex={-1}
      className="irc-recovery-overview"
      aria-label="索引恢复概览"
    >
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
          {displayedNeedsRecovery > 0 && (
            <section
              className={`irc-risk${displayedNeedsRecovery ? " is-warning" : " is-clear"}`}
              aria-label={displayedNeedsRecovery ? "索引恢复风险" : "索引恢复状态"}
            >
              {displayedNeedsRecovery ? (
                <AlertTriangle size={18} aria-hidden="true" />
              ) : (
                <CheckCircle2 size={18} aria-hidden="true" />
              )}
              <div>
                <strong>
                  {recoverySummary.interrupted
                    ? submissionInterrupted
                      ? `${submissionInterrupted} 项索引提交中断${parseInterrupted ? `，另有 ${parseInterrupted} 项解析中断` : ""}，等待恢复`
                      : `${parseInterrupted || recoverySummary.interrupted} 项解析中断，等待恢复`
                    : displayedNeedsRecovery
                      ? `${displayedNeedsRecovery} 项索引未完成，需要检查与恢复`
                      : "当前没有待恢复索引"}
                </strong>
                <span>
                  {opsIndex.last_reconcile?.failed
                    ? "最近索引核对存在异常，请先在运行诊断检查服务状态。"
                    : opsIndex.counts.parse_failed
                      ? "另有解析异常，可在运行诊断查看处理建议。"
                      : !opsIndex.last_reconcile
                        ? "暂无索引核对记录；恢复前会校验连接与嵌入模型。"
                        : "最近索引核对正常；恢复前仍会检查服务是否可用。"}
                </span>
              </div>
            </section>
          )}
          <section className="ingest-state-summary" aria-label="索引当前状态">
            <dl>
              <div>
                <dt>索引提交</dt>
                <dd>{submissionProcessing}</dd>
              </div>
              <div>
                <dt>索引提交中断</dt>
                <dd>{submissionInterrupted}</dd>
              </div>
              <div>
                <dt>解析中</dt>
                <dd>{parseInProgress}</dd>
              </div>
              <div>
                <dt>解析中断</dt>
                <dd>{parseInterrupted}</dd>
              </div>
              <div>
                <dt>已可检索</dt>
                <dd>{recoverySummary.searchable}</dd>
              </div>
            </dl>
            <p>
              <span>统计为当前索引状态，不代表全部入库资料总量。</span>
              <button type="button" className="ao84-text-action" onClick={showRuntimeDetails}>
                查看运行诊断
              </button>
            </p>
          </section>
        </>
      )}
    </section>
  );
}
