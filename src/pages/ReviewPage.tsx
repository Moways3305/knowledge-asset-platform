import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/http";
import {
  approveReview,
  fetchReviews,
  rejectReview,
  withdrawReviewConfirmation,
} from "../api/review";
import ConfirmDialog from "../components/ConfirmDialog";
import DataTable, { type Column } from "../components/DataTable";
import GovernanceWorkspace from "../components/GovernanceWorkspace";
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
  { token: "3", apiValue: "approved", label: "已通过" },
  { token: "4", apiValue: "rejected", label: "已拒绝" },
  { token: "5", apiValue: "approval_failed", label: "处理失败" },
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
  const requestRef = useRef(0);
  const status = statusFilters.find((item) => item.token === statusToken)?.apiValue ?? "";
  const reviewType =
    reviewTypeFilters.find((item) => item.token === reviewTypeToken)?.apiValue ?? "";

  const load = useCallback(async () => {
    const requestId = ++requestRef.current;
    setLoading(true);
    setForbidden(false);
    setLoadFailed(false);
    setFeedback(null);
    setItems([]);
    try {
      const next = await fetchReviews({
        status: status || undefined,
        reviewType: reviewType || undefined,
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
  }, [reviewType, status]);

  useEffect(() => {
    void load();
    return () => {
      requestRef.current += 1;
    };
  }, [load]);

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
      render: (item) =>
        item.review_type === "project_ingest_approval"
          ? "无需证据"
          : `${item.evidence_count} 项证据`,
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
          {!decidePending(item) && !retryFailed(item) && !item.can_withdraw && (
            <span className="gw-muted">—</span>
          )}
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
        </div>
      </div>

      {feedback && (
        <div className={`gw-feedback is-${feedback.tone}`} role="status">
          {feedback.text}
        </div>
      )}

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
    </GovernanceWorkspace>
  );
}
