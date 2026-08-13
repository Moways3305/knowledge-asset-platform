import { CheckCircle2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ControlledBulkRequestError } from "../api/bulk";
import { ApiError } from "../api/http";
import {
  approveReview,
  bulkRegisterReviewEvidence,
  bulkReviewAction,
  fetchReviews,
  rejectReview,
  withdrawReviewConfirmation,
} from "../api/review";
import ConfirmDialog from "../components/ConfirmDialog";
import { BulkSelectionRail, SelectionCheckbox } from "../components/BulkSelection";
import DataTable, { type Column } from "../components/DataTable";
import GovernanceWorkspace from "../components/GovernanceWorkspace";
import DetailDrawer from "../components/DetailDrawer";
import type { ReviewItemDTO } from "../types/review";
import { formatBeijingTime } from "../utils/time";

const SAFE_FALLBACK = "信息待确认";

const reviewTypeLabel: Record<string, string> = {
  material_to_asset: "资料资产化",
  personal_to_project: "个人知识升级",
  project_to_company: "公司资产升级",
  lifecycle_change: "生命周期变更",
  project_ingest_approval: "项目知识入库",
};

const statusLabel: Record<string, string> = {
  pending_evidence: "待补充证据",
  pending_reviewer: "待审核",
  approved: "已通过",
  rejected: "已拒绝",
  approving: "处理中",
  approval_failed: "处理失败",
};

const statusTone: Record<string, string> = {
  pending_evidence: "is-pending",
  pending_reviewer: "is-pending",
  approved: "is-success",
  rejected: "is-danger",
  approving: "is-neutral",
  approval_failed: "is-danger",
};

const statusFilters = [
  { token: "0", apiValue: "", label: "全部状态" },
  { token: "1", apiValue: "pending_evidence", label: "待补充证据" },
  { token: "2", apiValue: "pending_reviewer", label: "待审核" },
  { token: "3", apiValue: "approving", label: "处理中" },
  { token: "4", apiValue: "approval_failed", label: "处理失败" },
];

const reviewTypeFilters = [
  { token: "0", apiValue: "", label: "全部类型" },
  { token: "1", apiValue: "project_ingest_approval", label: "项目知识入库" },
  { token: "2", apiValue: "material_to_asset", label: "资料资产化" },
  { token: "3", apiValue: "personal_to_project", label: "个人知识升级" },
  { token: "4", apiValue: "project_to_company", label: "公司资产升级" },
  { token: "5", apiValue: "lifecycle_change", label: "生命周期变更" },
];

type Feedback = { tone: "success" | "error"; text: string } | null;

function safeTitle(item: ReviewItemDTO) {
  return item.asset_title?.trim() || "待确认知识";
}

function isForbidden(error: unknown) {
  return error instanceof ApiError && error.status === 403;
}

export default function ReviewPage() {
  const [statusToken, setStatusToken] = useState("0");
  const [reviewTypeToken, setReviewTypeToken] = useState("0");
  const [items, setItems] = useState<ReviewItemDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejectTarget, setRejectTarget] = useState<ReviewItemDTO | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectError, setRejectError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkAction, setBulkAction] = useState<"approve" | "reject" | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [evidenceTarget, setEvidenceTarget] = useState<ReviewItemDTO | null>(null);
  const [evidenceReviewIds, setEvidenceReviewIds] = useState<string[]>([]);
  const [evidenceDescription, setEvidenceDescription] = useState("");
  const [evidenceType, setEvidenceType] = useState<"internal_sharing" | "client_validation">(
    "internal_sharing",
  );
  const [evidenceCategory, setEvidenceCategory] = useState<
    "meeting_minutes" | "wecom_record" | "client_email" | "acceptance_doc" | "delivery_adoption"
  >("meeting_minutes");
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const requestRef = useRef(0);
  const bulkRunRef = useRef(false);
  const filtersRef = useRef({ status: "", reviewType: "" });
  const status = statusFilters.find((item) => item.token === statusToken)?.apiValue ?? "";
  const reviewType =
    reviewTypeFilters.find((item) => item.token === reviewTypeToken)?.apiValue ?? "";
  filtersRef.current = { status, reviewType };

  const load = useCallback(async () => {
    const requestId = ++requestRef.current;
    const filters = filtersRef.current;
    setLoading(true);
    setForbidden(false);
    setLoadFailed(false);
    setFeedback(null);
    setSelectedIds([]);
    setItems([]);
    try {
      const next = await fetchReviews({
        queue: "open",
        status: filters.status || undefined,
        reviewType: filters.reviewType || undefined,
      });
      if (requestId !== requestRef.current) return;
      setItems(next);
    } catch (error) {
      if (requestId !== requestRef.current) return;
      setForbidden(isForbidden(error));
      setLoadFailed(!isForbidden(error));
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      requestRef.current += 1;
    };
  }, [load, reviewType, status]);

  const runAction = async (
    item: ReviewItemDTO,
    action: () => Promise<void>,
    successText: string,
  ) => {
    setBusyId(item.id);
    setFeedback(null);
    try {
      await action();
      await load();
      setFeedback({ tone: "success", text: successText });
      return true;
    } catch {
      setFeedback({ tone: "error", text: "操作未完成，请稍后重试。" });
      return false;
    } finally {
      setBusyId(null);
    }
  };

  const decidePending = (item: ReviewItemDTO) =>
    item.can_decide && item.status === "pending_reviewer";
  const retryFailed = (item: ReviewItemDTO) => item.can_decide && item.status === "approval_failed";
  const eligibleItems = items.filter(decidePending);
  const selectedEligible = eligibleItems.filter((item) => selectedIds.includes(item.id));
  const selectedEvidence = items.filter(
    (item) => item.status === "pending_evidence" && selectedIds.includes(item.id),
  );
  const pageAllSelected =
    eligibleItems.length > 0 && selectedEligible.length === eligibleItems.length;
  const pageIndeterminate = selectedEligible.length > 0 && !pageAllSelected;

  const runBulkAction = async () => {
    if (!bulkAction || selectedEligible.length === 0 || bulkRunRef.current) return;
    const selectionSnapshot = selectedEligible.map((item) => item.id);
    const selectionRequest = requestRef.current;
    const reason = rejectReason.trim();
    if (bulkAction === "reject" && !reason) {
      setRejectError("请填写拒绝原因。");
      return;
    }
    bulkRunRef.current = true;
    setBulkBusy(true);
    setRejectError(null);
    try {
      const result = await bulkReviewAction({
        itemIds: selectionSnapshot,
        action: bulkAction,
        comment: bulkAction === "reject" ? reason : "批量确认通过",
      });
      setBulkAction(null);
      setRejectReason("");
      await load();
      setFeedback({
        tone: result.failed > 0 || result.skipped > 0 ? "error" : "success",
        text: `已提交 ${result.submitted} 项：成功 ${result.succeeded}，跳过 ${result.skipped}，失败 ${result.failed}。`,
      });
    } catch (error) {
      const retryIds =
        error instanceof ControlledBulkRequestError
          ? (error.retryItems as string[])
          : selectionSnapshot;
      const partial = error instanceof ControlledBulkRequestError ? error.partialResult : null;
      const selectionScopeUnchanged = requestRef.current === selectionRequest;
      await load();
      if (selectionScopeUnchanged && requestRef.current === selectionRequest + 1) {
        setSelectedIds(retryIds);
      }
      setBulkAction(null);
      setFeedback({
        tone: "error",
        text: partial
          ? `批量操作中断：已完成提交 ${partial.submitted} 项（成功 ${partial.succeeded}，跳过 ${partial.skipped}，失败 ${partial.failed}），剩余 ${retryIds.length} 项可重试。`
          : `批量操作未开始，${retryIds.length} 项仍保留选择，可重试。`,
      });
    } finally {
      bulkRunRef.current = false;
      setBulkBusy(false);
    }
  };

  const submitReject = async () => {
    if (!rejectTarget) return;
    const reason = rejectReason.trim();
    if (!reason) {
      setRejectError("请填写拒绝原因。");
      return;
    }
    setRejectError(null);
    const completed = await runAction(
      rejectTarget,
      () => rejectReview(rejectTarget.id, reason),
      "审核已拒绝。",
    );
    if (completed) {
      setRejectTarget(null);
      setRejectReason("");
    }
  };

  const columns: Column<ReviewItemDTO>[] = [
    {
      key: "select",
      header: (
        <SelectionCheckbox
          checked={pageAllSelected}
          indeterminate={pageIndeterminate}
          disabled={eligibleItems.length === 0 || bulkBusy}
          label="全选当前页可审核项"
          onChange={() =>
            setSelectedIds(pageAllSelected ? [] : eligibleItems.map((item) => item.id))
          }
        />
      ),
      headerClassName: "gw-col-review-select",
      className: "gw-col-review-select",
      render: (item) => (
        <SelectionCheckbox
          checked={selectedIds.includes(item.id)}
          disabled={(!decidePending(item) && item.status !== "pending_evidence") || bulkBusy}
          label={`选择审核项 ${safeTitle(item)}`}
          onChange={() =>
            setSelectedIds((current) =>
              current.includes(item.id)
                ? current.filter((id) => id !== item.id)
                : [...current, item.id],
            )
          }
        />
      ),
    },
    {
      key: "title",
      header: "知识标题",
      className: "gw-title-cell",
      headerClassName: "gw-col-review-title",
      render: safeTitle,
    },
    {
      key: "type",
      header: "审核类型",
      headerClassName: "gw-col-review-type",
      render: (item) => (
        <span className="gw-type-tag">{reviewTypeLabel[item.review_type] ?? SAFE_FALLBACK}</span>
      ),
    },
    {
      key: "project",
      header: "来源项目",
      headerClassName: "gw-col-review-project",
      render: (item) => <span className="gw-muted">{item.project_name?.trim() || "—"}</span>,
    },
    {
      key: "evidence",
      header: "适用内容",
      headerClassName: "gw-col-review-evidence",
      render: (item) => (
        <span title={item.blocking_reason || undefined}>
          {item.review_type === "project_ingest_approval"
            ? "无需证据"
            : `${item.evidence_count} 项证据`}
          {item.status === "pending_evidence" && (
            <small className="gw-blocking-reason">
              {item.blocking_reason || "缺少资产化验证证据"}
            </small>
          )}
        </span>
      ),
    },
    {
      key: "status",
      header: "状态",
      headerClassName: "gw-col-review-status",
      render: (item) => (
        <span className={`gw-status ${statusTone[item.status] ?? "is-neutral"}`}>
          {statusLabel[item.status] ?? SAFE_FALLBACK}
        </span>
      ),
    },
    {
      key: "created",
      header: "提交时间",
      className: "gw-time",
      headerClassName: "gw-col-review-time",
      render: (item) => formatBeijingTime(item.created_at),
    },
    {
      key: "actions",
      header: "操作",
      headerClassName: "gw-col-review-actions",
      render: (item) => (
        <div className="gw-actions">
          {item.status === "pending_evidence" && item.review_type === "material_to_asset" && (
            <button
              className="gw-action is-primary"
              type="button"
              onClick={() => {
                setEvidenceTarget(item);
                setEvidenceReviewIds([item.id]);
                setEvidenceDescription("");
              }}
            >
              补充证据 / 查看要求
            </button>
          )}
          {decidePending(item) && (
            <>
              <button
                className="gw-action is-primary"
                type="button"
                disabled={busyId === item.id}
                onClick={() =>
                  void runAction(item, () => approveReview(item.id, "确认通过"), "审核已通过。")
                }
              >
                确认
              </button>
              <button
                className="gw-action is-danger"
                type="button"
                disabled={busyId === item.id}
                onClick={() => {
                  setFeedback(null);
                  setRejectTarget(item);
                  setRejectReason("");
                  setRejectError(null);
                }}
              >
                拒绝
              </button>
            </>
          )}
          {retryFailed(item) && (
            <button
              className="gw-action is-primary"
              type="button"
              disabled={busyId === item.id}
              onClick={() =>
                void runAction(item, () => approveReview(item.id, "重试入库"), "已重新提交处理。")
              }
            >
              重试
            </button>
          )}
          {item.can_withdraw && (
            <button
              className="gw-action"
              type="button"
              disabled={busyId === item.id}
              onClick={() =>
                void runAction(
                  item,
                  () => withdrawReviewConfirmation(item.id, "撤回本人确认"),
                  "确认已撤回。",
                )
              }
            >
              撤回
            </button>
          )}
          {item.status !== "pending_evidence" &&
            !decidePending(item) &&
            !retryFailed(item) &&
            !item.can_withdraw && <span className="gw-muted">—</span>}
        </div>
      ),
    },
  ];

  const state = forbidden
    ? { title: "无审核权限", description: "当前账号无法查看审核队列。" }
    : loadFailed
      ? { title: "审核队列加载失败", description: "请稍后重试。" }
      : { title: "暂无审核事项", description: "当前筛选条件下没有需要处理的审核事项。" };

  return (
    <GovernanceWorkspace active="review" loading={loading} onRefresh={() => void load()}>
      <h2>审核待办</h2>
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
          <button
            className="gw-action is-primary gw-bulk-quick"
            disabled={eligibleItems.length === 0 || bulkBusy}
            onClick={() => {
              setSelectedIds(eligibleItems.map((item) => item.id));
              setBulkAction("approve");
            }}
            title={
              eligibleItems.length === 0
                ? "当前没有可一键通过的待审核项"
                : `一键全选 ${eligibleItems.length} 项并进入确认`
            }
            type="button"
          >
            <CheckCircle2 size={13} aria-hidden="true" />
            一键全选确认
          </button>
          {eligibleItems.length === 0 && <span className="gw-muted">当前没有可确认的待审核项</span>}
        </div>
      </div>

      {feedback && (
        <div className={`gw-feedback is-${feedback.tone}`} role="status">
          {feedback.text}
        </div>
      )}

      <BulkSelectionRail
        selectedCount={selectedEligible.length}
        pageSelectedCount={selectedEligible.length}
        matchingCount={eligibleItems.length}
        allMatchingSelected={pageAllSelected}
        busy={bulkBusy}
        onClear={() => setSelectedIds([])}
      >
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
      </BulkSelectionRail>
      <BulkSelectionRail
        selectedCount={selectedEvidence.length}
        pageSelectedCount={selectedEvidence.length}
        matchingCount={items.filter((item) => item.status === "pending_evidence").length}
        allMatchingSelected={false}
        busy={evidenceBusy}
        onClear={() =>
          setSelectedIds((current) =>
            current.filter((id) => !selectedEvidence.some((item) => item.id === id)),
          )
        }
      >
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
                  .then(async () => {
                    setEvidenceTarget(null);
                    setEvidenceReviewIds([]);
                    await load();
                    setFeedback({ tone: "success", text: "证据已登记，任务已进入待审核。" });
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
