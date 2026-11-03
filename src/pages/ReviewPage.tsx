import { Link } from "react-router-dom";
import { bulkRegisterReviewEvidence } from "../api/review";
import { BulkSelectionRail } from "../components/BulkSelection";
import ConfirmDialog from "../components/ConfirmDialog";
import DataTable from "../components/DataTable";
import DetailDrawer from "../components/DetailDrawer";
import GovernanceWorkspace from "../components/GovernanceWorkspace";
import { formatBeijingTime } from "../utils/time";
import {
  SAFE_FALLBACK,
  companyConfirmationLabel,
  reviewTypeFilters,
  reviewTypeLabel,
  safeTitle,
  statusFilters,
  statusLabel,
  statusTone,
} from "./controllers/Review/model";
import { useReview } from "./controllers/Review/useReview";

export default function ReviewPage() {
  const {
    completedTarget,
    loading,
    load,
    focusReviewId,
    focusProjectId,
    forbidden,
    loadFailed,
    items,
    params,
    setParams,
    statusToken,
    setStatusToken,
    reviewTypeToken,
    setReviewTypeToken,
    eligibleItems,
    feedback,
    selectedEligible,
    selectedEvidence,
    bulkBusy,
    evidenceBusy,
    setSelectedIds,
    setBulkAction,
    setRejectReason,
    setRejectError,
    setFeedback,
    setEvidenceTarget,
    setEvidenceReviewIds,
    setEvidenceDescription,
    columns,
    state,
    rejectTarget,
    busyId,
    rejectError,
    submitReject,
    setRejectTarget,
    rejectReason,
    detail,
    setDetailId,
    renderReviewActions,
    evidenceTarget,
    evidenceReviewIds,
    evidenceDescription,
    setEvidenceBusy,
    evidenceType,
    evidenceCategory,
    setEvidenceType,
    setEvidenceCategory,
    bulkAction,
    runBulkAction,
  } = useReview();

  return (
    <GovernanceWorkspace
      active={completedTarget ? "review-completed" : "review"}
      loading={loading}
      onRefresh={() => void load()}
    >
      {(focusReviewId || focusProjectId) && (
        <div className="gw-feedback is-info" role="status">
          {!loading && !forbidden && !loadFailed && items.length === 0
            ? "当前可见审核记录中未找到该事项，可能已处理或不在当前身份的可见范围。"
            : "正在查看指定的审核事项。"}
          <button
            className="btn-small"
            onClick={() => {
              const next = new URLSearchParams(params);
              next.delete("review_id");
              next.delete("target_id");
              next.delete("queue");
              next.delete("project_id");
              setParams(next);
            }}
          >
            查看全部待办
          </button>
        </div>
      )}
      <div className="gw-toolbar" role="search" aria-label="审核筛选">
        <div className="gw-toolbar-fields">
          <label className="gw-filter-label">
            <span>审核状态</span>
            <select value={statusToken} onChange={(event) => setStatusToken(event.target.value)}>
              {statusFilters.map((item) => (
                <option key={item.token} value={item.token}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="gw-filter-label">
            <span>审核类型</span>
            <select
              value={reviewTypeToken}
              onChange={(event) => setReviewTypeToken(event.target.value)}
            >
              {reviewTypeFilters.map((item) => (
                <option key={item.token} value={item.token}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="gw-toolbar-actions">
          <span className="gw-total">共 {items.length} 条</span>
          {eligibleItems.length === 0 && <span className="gw-muted">当前没有可确认的待审核项</span>}
        </div>
      </div>

      {feedback && (
        <div className={`gw-feedback is-${feedback.tone}`} role="status">
          {feedback.text}
        </div>
      )}

      <BulkSelectionRail
        selectedCount={selectedEligible.length + selectedEvidence.length}
        pageSelectedCount={selectedEligible.length + selectedEvidence.length}
        matchingCount={
          eligibleItems.length + items.filter((item) => item.status === "pending_evidence").length
        }
        allMatchingSelected={
          selectedEligible.length + selectedEvidence.length ===
          eligibleItems.length + items.filter((item) => item.status === "pending_evidence").length
        }
        busy={bulkBusy || evidenceBusy}
        onClear={() => setSelectedIds([])}
      >
        {selectedEligible.length > 0 && (
          <>
            {" "}
            <button
              className="gw-action is-primary"
              disabled={bulkBusy}
              onClick={() => setBulkAction("approve")}
              type="button"
            >
              批量通过（{selectedEligible.length}）
            </button>
            <button
              className="gw-action is-danger"
              disabled={bulkBusy}
              onClick={() => {
                setRejectReason("");
                setRejectError(null);
                setBulkAction("reject");
              }}
              type="button"
            >
              批量驳回（{selectedEligible.length}）
            </button>
          </>
        )}
        {selectedEvidence.length > 0 && (
          <>
            {" "}
            <button
              className="gw-action is-primary"
              type="button"
              disabled={evidenceBusy || selectedEvidence.length === 0}
              onClick={() => {
                const projects = new Set(selectedEvidence.map((item) => item.target_project_id));
                if (projects.size !== 1) {
                  setFeedback({ tone: "error", text: "批量补证据只能选择同一项目的任务。" });
                  return;
                }
                setEvidenceTarget(selectedEvidence[0]);
                setEvidenceReviewIds(selectedEvidence.map((item) => item.id));
                setEvidenceDescription("");
              }}
            >
              批量补充证据（{selectedEvidence.length}）
            </button>
          </>
        )}
      </BulkSelectionRail>

      <DataTable
        columns={columns}
        rows={items}
        rowKey={(item) => item.id}
        loading={loading}
        loadingText="正在加载审核队列…"
        emptyText={
          <div className="gw-state">
            <strong>{state.title}</strong>
            <p>{state.description}</p>
            {loadFailed && (
              <button className="gw-action" type="button" onClick={() => void load()}>
                重试
              </button>
            )}
          </div>
        }
        wrapClassName="gw-table-wrap"
        tableClassName="gw-table gw-review-table"
        ariaLabel="知识审核队列"
      />

      <ConfirmDialog
        open={Boolean(rejectTarget)}
        title="拒绝审核"
        description="填写原因后提交，便于申请人补充或修正内容。"
        confirmText="确认拒绝"
        busy={Boolean(rejectTarget && busyId === rejectTarget.id)}
        busyText="正在提交…"
        danger
        error={rejectError}
        errorDescription={rejectError}
        onConfirm={() => void submitReject()}
        onCancel={() => {
          setRejectTarget(null);
          setRejectReason("");
          setRejectError(null);
        }}
      >
        <label className="gw-reject-field">
          <span>拒绝原因</span>
          <textarea
            value={rejectReason}
            maxLength={500}
            placeholder="说明需要补充或修正的内容"
            onChange={(event) => setRejectReason(event.target.value)}
          />
        </label>
      </ConfirmDialog>
      <DetailDrawer
        portal
        open={Boolean(detail)}
        title={detail ? safeTitle(detail) : "审核详情"}
        description={detail ? (reviewTypeLabel[detail.review_type] ?? SAFE_FALLBACK) : undefined}
        className="approval-detail-drawer"
        onClose={() => setDetailId(null)}
        busy={Boolean(detail && busyId === detail.id)}
        footer={detail && renderReviewActions(detail)}
      >
        {detail && (
          <div className="approval-detail-layout">
            <section className="approval-detail-material">
              <h3>审核资料</h3>
              <dl>
                <div>
                  <dt>来源项目</dt>
                  <dd>{detail.project_name?.trim() || "未提供"}</dd>
                </div>
                <div>
                  <dt>提交时间</dt>
                  <dd>{formatBeijingTime(detail.created_at)}</dd>
                </div>
                <div>
                  <dt>适用证据</dt>
                  <dd>
                    {detail.review_type === "project_ingest_approval"
                      ? "无需证据"
                      : `${detail.evidence_count} 项证据`}
                  </dd>
                </div>
              </dl>
              {detail.target_asset_id && (
                <Link
                  className="product-button is-secondary"
                  to={`/knowledge/${encodeURIComponent(detail.target_asset_id)}`}
                  state={{
                    backTo: `/review${params.size ? `?${params}` : ""}`,
                    backLabel: "返回审核待办",
                    source: "review",
                  }}
                >
                  查看资料与摘要
                </Link>
              )}
              {detail.blocking_reason && (
                <p className="approval-detail-note">{detail.blocking_reason}</p>
              )}
              {detail.review_comment && (
                <>
                  <h3>审核意见</h3>
                  <p>{detail.review_comment}</p>
                </>
              )}
            </section>
            <aside className="approval-detail-progress">
              <h3>审批进度</h3>
              <span className={`gw-status ${statusTone[detail.status] ?? "is-neutral"}`}>
                {statusLabel[detail.status] ?? SAFE_FALLBACK}
              </span>
              {detail.review_type === "project_to_company" && (
                <ol>
                  <li>
                    <strong>总经理确认</strong>
                    <span>
                      {companyConfirmationLabel(detail.general_manager_confirmation_status)}
                    </span>
                  </li>
                  <li>
                    <strong>咨询总监确认</strong>
                    <span>
                      {companyConfirmationLabel(detail.consulting_director_confirmation_status)}
                    </span>
                  </li>
                </ol>
              )}
              {detail.reviewed_at && <p>处理于 {formatBeijingTime(detail.reviewed_at)}</p>}
            </aside>
            {feedback && (
              <p className={`gw-feedback is-${feedback.tone}`} role="status">
                {feedback.text}
              </p>
            )}
          </div>
        )}
      </DetailDrawer>
      <DetailDrawer
        open={Boolean(evidenceTarget)}
        title="补充资产化验证证据"
        description={
          evidenceTarget
            ? `${evidenceReviewIds.length > 1 ? `${evidenceReviewIds.length} 项资料` : safeTitle(evidenceTarget)} · ${evidenceTarget.project_name || "当前项目"}`
            : undefined
        }
        busy={evidenceBusy}
        onClose={() => setEvidenceTarget(null)}
        footer={
          <>
            <button
              className="gw-action"
              type="button"
              disabled={evidenceBusy}
              onClick={() => setEvidenceTarget(null)}
            >
              取消
            </button>
            <button
              className="gw-action is-primary"
              type="button"
              disabled={evidenceBusy || !evidenceDescription.trim()}
              onClick={() => {
                if (!evidenceTarget) return;
                setEvidenceBusy(true);
                void bulkRegisterReviewEvidence(evidenceReviewIds, {
                  evidence_type: evidenceType,
                  evidence_category: evidenceCategory,
                  description: evidenceDescription.trim(),
                  idempotency_key: crypto.randomUUID(),
                })
                  .then(async (result) => {
                    setEvidenceTarget(null);
                    setEvidenceReviewIds([]);
                    await load();
                    setFeedback({
                      tone: result.failed > 0 || result.skipped > 0 ? "error" : "success",
                      text: `补充证据处理完成：转待审核 ${result.transitioned} 项，重复证据 ${result.existing} 项，跳过 ${result.skipped} 项，失败 ${result.failed} 项。`,
                    });
                  })
                  .catch(() => setFeedback({ tone: "error", text: "证据未提交，请稍后重试。" }))
                  .finally(() => setEvidenceBusy(false));
              }}
            >
              {evidenceBusy ? "正在提交…" : "登记并转待审核"}
            </button>
          </>
        }
      >
        <div className="gw-evidence-drawer">
          <div className="gw-evidence-requirement">
            <strong>阻塞原因</strong>
            <p>{evidenceTarget?.blocking_reason || "资料资产化至少需要一项验证证据。"}</p>
            <small>证据是治理线索，不表示平台已经验证其真实性。</small>
          </div>
          <label>
            <span>证据类型</span>
            <select
              value={evidenceType}
              onChange={(event) => setEvidenceType(event.target.value as typeof evidenceType)}
            >
              <option value="internal_sharing">内部分享</option>
              <option value="client_validation">客户验证</option>
            </select>
          </label>
          <label>
            <span>证据类别</span>
            <select
              value={evidenceCategory}
              onChange={(event) =>
                setEvidenceCategory(event.target.value as typeof evidenceCategory)
              }
            >
              <option value="meeting_minutes">会议纪要</option>
              <option value="wecom_record">企业沟通记录</option>
              <option value="client_email">客户邮件</option>
              <option value="acceptance_doc">验收文件</option>
              <option value="delivery_adoption">交付采纳记录</option>
            </select>
          </label>
          <label>
            <span>适用说明（必填）</span>
            <textarea
              value={evidenceDescription}
              onChange={(event) => setEvidenceDescription(event.target.value)}
              placeholder="说明发生场景、适用范围与资料关系"
            />
          </label>
        </div>
      </DetailDrawer>
      <ConfirmDialog
        open={bulkAction !== null}
        title={bulkAction === "approve" ? "批量通过审核" : "批量驳回审核"}
        description={`将处理选中的 ${selectedEligible.length} 项；服务端会逐项重新核验状态和权限，变化项将安全跳过。`}
        confirmText={bulkAction === "approve" ? "确认批量通过" : "确认批量驳回"}
        busy={bulkBusy}
        danger={bulkAction === "reject"}
        error={rejectError}
        errorDescription={rejectError}
        onConfirm={() => void runBulkAction()}
        onCancel={() => {
          if (!bulkBusy) {
            setBulkAction(null);
            setRejectError(null);
          }
        }}
      >
        {bulkAction === "reject" && (
          <label className="gw-reject-field">
            <span>同批驳回原因</span>
            <textarea
              value={rejectReason}
              maxLength={500}
              placeholder="说明需要补充或修正的内容"
              onChange={(event) => setRejectReason(event.target.value)}
            />
          </label>
        )}
      </ConfirmDialog>
    </GovernanceWorkspace>
  );
}
