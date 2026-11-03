import { RotateCw } from "lucide-react";
import ActionFeedback from "../components/ActionFeedback";
import Button from "../components/Button";
import DetailDrawer from "../components/DetailDrawer";
import OperationStatusCard from "../components/OperationStatusCard";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import { operationStatusFromJob } from "../components/operationStatus";
import { formatBeijingTime } from "../utils/time";
import "./AdminIngestPage.css";
import "./AdminIngestWorkspace.css";
import { IngestJobRecords } from "./controllers/AdminIngest/IngestJobRecords";
import { IngestRecoveryQueue } from "./controllers/AdminIngest/IngestRecoveryQueue";
import { IngestRecoverySummary } from "./controllers/AdminIngest/IngestRecoverySummary";
import { IngestRuntimeDiagnosis } from "./controllers/AdminIngest/IngestRuntimeDiagnosis";
import {
  recoveryStateLabel,
  safeFailureMessage,
  safeJobOperation,
  safeJobStatus,
} from "./controllers/AdminIngest/model";
import { useAdminIngest } from "./controllers/AdminIngest/useAdminIngest";

export default function AdminIngestPage() {
  const controller = useAdminIngest();
  const {
    refreshAll,
    opsBusy,
    workspace,
    setWorkspace,
    runtimeAttentionCount,
    opsNote,
    opsFeedbackState,
    jobsState,
    setSelectedJob,
    setFailureFilter,
    setTargetError,
    setRetryTarget,
    retryTarget,
    targetBusy,
    handleTargetRetry,
    targetError,
    selectedJob,
  } = controller;

  return (
    <ProductPage className="ao84-page admin-control-page ingest-workspace">
      <PageHeader
        title="入库管理"
        description="处理入库异常，跟踪恢复结果，检查运行状态。"
        actions={
          <div className="ao84-refresh-actions">
            <button
              className="btn-small"
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
      <div className="ao84-console">
        <div className="irc-workspace-tabs" role="group" aria-label="索引恢复工作区">
          {(
            [
              ["recovery", "待恢复任务"],
              ["jobs", "作业记录"],
              ["runtime", "运行诊断"],
            ] as const
          ).map(([key, label]) => (
            <button
              className="btn-small"
              type="button"
              aria-pressed={workspace === key}
              key={key}
              onClick={() => setWorkspace(key)}
            >
              {label}
              {key === "runtime" && runtimeAttentionCount > 0 ? `（${runtimeAttentionCount}）` : ""}
            </button>
          ))}
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
        {workspace === "recovery" && <IngestRecoverySummary controller={controller} />}

        {workspace === "jobs" && <IngestJobRecords controller={controller} />}

        {workspace === "runtime" && <IngestRuntimeDiagnosis controller={controller} />}

        {workspace === "recovery" && <IngestRecoveryQueue controller={controller} />}
      </div>

      <DetailDrawer
        open={retryTarget !== null}
        title="索引恢复详情"
        description="此操作仅重新发起索引恢复，不查看、不下载、不修改原文。"
        busy={targetBusy}
        onClose={() => {
          setRetryTarget(null);
          setTargetError(null);
        }}
        footer={
          <>
            <Button
              variant="secondary"
              disabled={targetBusy}
              onClick={() => {
                setRetryTarget(null);
                setTargetError(null);
              }}
            >
              取消
            </Button>
            <Button
              disabled={targetBusy || !retryTarget?.retry_eligible || !retryTarget.retry_target}
              onClick={() => void handleTargetRetry()}
            >
              {targetBusy ? "提交中…" : "确认恢复"}
            </Button>
          </>
        }
      >
        {retryTarget && (
          <div className="irc-drawer">
            <StatusBadge tone="danger" label={recoveryStateLabel(retryTarget)} />
            <h3>{retryTarget.title}</h3>
            <ol aria-label="该资产索引轨迹">
              <li className="is-complete">
                <span>1</span>
                <div>
                  <strong>资产已入库</strong>
                  <small>业务资产与原文均已保留</small>
                </div>
              </li>
              <li className="is-complete">
                <span>2</span>
                <div>
                  <strong>
                    {retryTarget.recovery_state === "submission_interrupted"
                      ? "索引提交未完成"
                      : "已提交索引"}
                  </strong>
                  <small>
                    {retryTarget.recovery_state === "submission_interrupted"
                      ? "尚未进入解析，可恢复重试"
                      : "曾进入知识底座处理链"}
                  </small>
                </div>
              </li>
              <li className="is-error">
                <span>3</span>
                <div>
                  <strong>{recoveryStateLabel(retryTarget)}</strong>
                  <small>{safeFailureMessage(retryTarget)}</small>
                </div>
              </li>
              <li>
                <span>4</span>
                <div>
                  <strong>恢复为可检索</strong>
                  <small>恢复作业成功后完成</small>
                </div>
              </li>
            </ol>
            <section>
              <h4>安全原因</h4>
              <p>{retryTarget.index_error_message || "索引未完成，资产仍安全保留。"}</p>
              <h4>下一步</h4>
              <p>{retryTarget.remediation_hint || "确认知识底座可用后发起恢复。"}</p>
              <h4>最近恢复作业</h4>
              <p>
                {retryTarget.latest_job
                  ? `${safeJobStatus(retryTarget.latest_job.status)} · 成功 ${retryTarget.latest_job.success_count} · 提交时待索引 ${retryTarget.latest_job.pending_count ?? 0} · 失败 ${retryTarget.latest_job.failed_count}`
                  : "尚未发起过单条恢复作业"}
              </p>
              <small>进入当前状态：{formatBeijingTime(retryTarget.updated_at)}</small>
            </section>
            {targetError && (
              <p className="irc-drawer-error" role="alert">
                {targetError}
              </p>
            )}
          </div>
        )}
      </DetailDrawer>

      <DetailDrawer
        open={selectedJob !== null}
        title="索引维护作业"
        description="查看本次操作的处理结果。此记录不包含逐条资料明细。"
        onClose={() => setSelectedJob(null)}
        footer={
          <Button variant="secondary" onClick={() => setSelectedJob(null)}>
            返回作业列表
          </Button>
        }
      >
        {selectedJob && (
          <>
            {jobsState === "error" && <p role="alert">状态更新失败，以下为上次读取的结果。</p>}
            <dl className="ingest-job-times">
              <div>
                <dt>发起时间</dt>
                <dd>
                  {selectedJob.requested_at
                    ? formatBeijingTime(selectedJob.requested_at)
                    : "未记录"}
                </dd>
              </div>
              <div>
                <dt>开始时间</dt>
                <dd>
                  {selectedJob.started_at ? formatBeijingTime(selectedJob.started_at) : "尚未开始"}
                </dd>
              </div>
              <div>
                <dt>结束时间</dt>
                <dd>
                  {selectedJob.finished_at
                    ? formatBeijingTime(selectedJob.finished_at)
                    : "尚未结束"}
                </dd>
              </div>
            </dl>
            <OperationStatusCard
              status={operationStatusFromJob(selectedJob.status)}
              title={safeJobOperation(selectedJob.operation_type)}
              description={
                selectedJob.status === "queued" || selectedJob.status === "running"
                  ? "操作已提交，正在等待处理结果。"
                  : (selectedJob.pending_count ?? 0) > 0
                    ? "本次提交处理已结束，下方待索引数是提交时快照；是否可检索以资产当前索引状态为准。"
                    : "本次操作已结束，处理结果如下。"
              }
              counts={[
                { label: "总计", value: selectedJob.total_count },
                { label: "成功", value: selectedJob.success_count, tone: "success" },
                { label: "提交时待索引", value: selectedJob.pending_count ?? 0, tone: "warning" },
                { label: "失败", value: selectedJob.failed_count, tone: "danger" },
                { label: "跳过", value: selectedJob.skipped_count, tone: "warning" },
              ]}
              nextStep={
                selectedJob.status === "queued" || selectedJob.status === "running"
                  ? "系统会继续更新进度，请等待处理结果，无需重复提交。"
                  : (selectedJob.pending_count ?? 0) > 0
                    ? "等待自动对账并查看资产当前索引状态；待索引项勿重复提交，失败项修正后再重试。"
                    : selectedJob.failed_count > 0
                      ? "前往当前待恢复任务核查仍存在的异常，修正后再重试。"
                      : "作业处理已结束，是否可检索请查看资产当前索引状态。"
              }
              compact
            />
            {selectedJob.failed_count > 0 && (
              <button
                className="btn-small"
                onClick={() => {
                  setSelectedJob(null);
                  setWorkspace("recovery");
                  setFailureFilter("all");
                }}
              >
                查看当前待恢复任务
              </button>
            )}
            {selectedJob.failed_count > 0 && (
              <p className="ingest-record-hint">
                待恢复列表展示当前异常，并非本次作业专属明细；已处理的异常可能不再出现。
              </p>
            )}
          </>
        )}
      </DetailDrawer>
    </ProductPage>
  );
}
