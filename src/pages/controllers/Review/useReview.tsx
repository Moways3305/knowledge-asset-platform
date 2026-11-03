import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { ControlledBulkRequestError } from "../../../api/bulk";
import {
  approveReview,
  bulkReviewAction,
  fetchReviews,
  fetchReview,
  rejectReview,
  withdrawReviewConfirmation,
} from "../../../api/review";
import { SelectionCheckbox } from "../../../components/BulkSelection";
import { type Column } from "../../../components/DataTable";
import type { ReviewActionResponseDTO, ReviewItemDTO } from "../../../types/review";
import { reviewActionFeedback, type ReviewAction } from "../../../utils/reviewActionFeedback";
import { formatBeijingTime } from "../../../utils/time";
import {
  Feedback,
  SAFE_FALLBACK,
  companyConfirmationLabel,
  isForbidden,
  reviewTypeFilters,
  reviewTypeLabel,
  safeTitle,
  statusFilters,
  statusLabel,
  statusTone,
} from "./model";

export function useReview() {
  const [statusToken, setStatusToken] = useState("0");
  const [reviewTypeToken, setReviewTypeToken] = useState("0");
  const [params, setParams] = useSearchParams();
  const noticeTargetId = params.get("target_id");
  const focusReviewId = params.get("review_id") ?? noticeTargetId;
  const completedTarget = Boolean(noticeTargetId && params.get("queue") === "completed");
  const focusProjectId = params.get("project_id");
  const [detailId, setDetailId] = useState<string | null>(null);
  const locationKey = useLocation().key;
  useEffect(() => setDetailId(noticeTargetId), [noticeTargetId, locationKey]);
  const [availableItems, setItems] = useState<ReviewItemDTO[]>([]);
  const items = availableItems.filter(
    (item) =>
      (!focusReviewId || item.id === focusReviewId) &&
      (!focusProjectId || item.target_project_id === focusProjectId),
  );
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejectTarget, setRejectTarget] = useState<ReviewItemDTO | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectError, setRejectError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  useEffect(() => setSelectedIds([]), [focusReviewId, focusProjectId]);
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
      const next = focusReviewId
        ? [await fetchReview(focusReviewId)]
        : await fetchReviews({
            queue: completedTarget ? "completed" : "open",
            status: filters.status || undefined,
            reviewType: filters.reviewType || undefined,
          });
      if (requestId !== requestRef.current) return;
      setItems(
        focusReviewId
          ? next.filter(
              (item) =>
                (!filters.status || item.status === filters.status) &&
                (!filters.reviewType || item.review_type === filters.reviewType),
            )
          : next,
      );
      return true;
    } catch (error) {
      if (requestId !== requestRef.current) return;
      setForbidden(isForbidden(error));
      setLoadFailed(!isForbidden(error));
      return false;
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, [completedTarget, focusReviewId]);

  useEffect(() => {
    void load();
    return () => {
      requestRef.current += 1;
    };
  }, [load, reviewType, status]);

  const runAction = async (
    item: ReviewItemDTO,
    action: () => Promise<ReviewActionResponseDTO>,
    kind: ReviewAction,
  ) => {
    setBusyId(item.id);
    setFeedback(null);
    try {
      const result = await action();
      const refreshed = await load();
      if (refreshed === undefined) return false;
      const outcome = reviewActionFeedback(result, kind);
      setFeedback(
        refreshed
          ? outcome
          : {
              tone: "info",
              text: `${outcome.text}列表刷新失败，请刷新列表核对，无需重复提交。`,
            },
      );
      return outcome.tone !== "error";
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
      "reject",
    );
    if (completed) {
      setRejectTarget(null);
      setRejectReason("");
    }
  };

  const renderReviewActions = (item: ReviewItemDTO) => (
    <div className="gw-actions">
      {item.status === "pending_evidence" && item.review_type === "material_to_asset" && (
        <button
          className="gw-action is-primary"
          type="button"
          onClick={() => {
            setDetailId(null);
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
              void runAction(item, () => approveReview(item.id, "确认通过"), "approve")
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
              setDetailId(null);
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
          onClick={() => void runAction(item, () => approveReview(item.id, "重试入库"), "approve")}
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
              "withdraw",
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
  );

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
      render: (item) => (
        <button
          type="button"
          className="workspace-object-link"
          onClick={() => setDetailId(item.id)}
        >
          {safeTitle(item)}
        </button>
      ),
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
        <div>
          <span className={`gw-status ${statusTone[item.status] ?? "is-neutral"}`}>
            {statusLabel[item.status] ?? SAFE_FALLBACK}
          </span>
          {item.review_type === "project_to_company" && (
            <small className="gw-blocking-reason">
              <span>
                总经理：{companyConfirmationLabel(item.general_manager_confirmation_status)}
              </span>
              <br />
              <span>
                咨询总监：{companyConfirmationLabel(item.consulting_director_confirmation_status)}
              </span>
            </small>
          )}
        </div>
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
      render: renderReviewActions,
    },
  ];

  const detail = items.find((item) => item.id === detailId);

  const state = forbidden
    ? { title: "无审核权限", description: "当前账号无法查看审核队列。" }
    : loadFailed
      ? { title: "审核队列加载失败", description: "请稍后重试。" }
      : { title: "暂无审核事项", description: "当前筛选条件下没有需要处理的审核事项。" };
  return {
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
  };
}
export type ReviewController = ReturnType<typeof useReview>;
