import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchAuthMe } from "../api/auth";
import { approveReview, fetchReviews, rejectReview } from "../api/review";
import type { ReviewItemDTO } from "../types/review";
import { useAsyncData } from "../hooks/useAsyncData";
import { useActionFeedback } from "../hooks/useActionFeedback";
import DataTable, { type Column } from "../components/DataTable";
import StatusBadge from "../components/StatusBadge";
import LoadingError from "../components/LoadingError";

// 审核状态展示
const statusLabel: Record<string, string> = {
  pending_evidence: "待补充证据",
  pending_reviewer: "待审核人确认",
  approved: "已通过",
  rejected: "已拒绝",
};
const statusCls: Record<string, string> = {
  pending_evidence: "rv-status-consultant",
  pending_reviewer: "rv-status-manager",
  approved: "rv-status-approved",
  rejected: "rv-status-rejected",
};

const reviewTypeLabel: Record<string, string> = {
  material_to_asset: "资料 → 资产",
  personal_to_project: "个人 → 项目",
  project_to_company: "项目 → 公司",
  lifecycle_change: "生命周期变更",
};

export default function ReviewPage() {
  const { data, loading, error, forbidden, reload } = useAsyncData(() =>
    Promise.all([fetchAuthMe(), fetchReviews()]).then(([me, reviews]) => ({
      currentUserId: me.userId,
      items: reviews,
    })),
  );
  const items = useMemo(() => data?.items ?? [], [data]);
  const currentUserId = data?.currentUserId ?? "";

  const [filterStatus, setFilterStatus] = useState("");
  const action = useActionFeedback();

  const filtered = useMemo(
    () => (filterStatus ? items.filter((i) => i.status === filterStatus) : items),
    [items, filterStatus],
  );

  const countByStatus = (s: string) => items.filter((i) => i.status === s).length;

  const canAct = (it: ReviewItemDTO) =>
    it.status === "pending_reviewer" && it.reviewer_user_id === currentUserId;

  const handleApprove = (id: string) =>
    void action.run(async () => {
      await approveReview(id, "确认通过");
      reload();
    });

  const handleReject = (id: string) =>
    void action.run(async () => {
      await rejectReview(id, "审核未通过：需补充材料");
      reload();
    });

  const columns: Column<ReviewItemDTO>[] = [
    {
      key: "title",
      header: "知识标题",
      className: "cell-review-title",
      render: (c) => c.asset_title ?? c.target_asset_id,
    },
    {
      key: "type",
      header: "审核类型",
      render: (c) => (
        <span className="path-badge">{reviewTypeLabel[c.review_type] ?? c.review_type}</span>
      ),
    },
    {
      key: "project",
      header: "来源项目",
      className: "cell-source",
      render: (c) => c.project_name ?? "—",
    },
    {
      key: "evidence",
      header: "证据数",
      className: "cell-center",
      render: (c) => c.evidence_count,
    },
    {
      key: "status",
      header: "状态",
      render: (c) => (
        <StatusBadge variant={statusCls[c.status]} label={statusLabel[c.status] ?? c.status} />
      ),
    },
    {
      key: "actions",
      header: "操作",
      className: "cell-actions",
      render: (c) =>
        canAct(c) ? (
          <>
            <button className="btn-small btn-small-primary" onClick={() => handleApprove(c.id)}>
              通过
            </button>
            <button className="btn-small btn-small-danger" onClick={() => handleReject(c.id)}>
              拒绝
            </button>
          </>
        ) : (
          <span className="rv-evidence-summary">
            {c.status === "pending_evidence"
              ? "待补充证据"
              : c.status === "pending_reviewer"
                ? "待指定审核人处理"
                : "—"}
          </span>
        ),
    },
  ];

  return (
    <div className="review-page">
      <div className="rv-header">
        <div className="rv-header-text">
          <h2>知识升级审核</h2>
          <p>处理分配给你的审核任务。</p>
        </div>
        <div className="kl-kpis">
          <div className="kl-kpi">
            <div className="kl-kpi-value kl-kpi-warning">{countByStatus("pending_evidence")}</div>
            <div className="kl-kpi-label">待补充证据</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value rv-kpi-manager">{countByStatus("pending_reviewer")}</div>
            <div className="kl-kpi-label">待审核人确认</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value kl-kpi-success">{countByStatus("approved")}</div>
            <div className="kl-kpi-label">已通过</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value rv-kpi-rejected">{countByStatus("rejected")}</div>
            <div className="kl-kpi-label">已拒绝</div>
          </div>
        </div>
      </div>

      <div className="role-context-hint">
        <div className="role-context-hint-title">审核视角说明</div>
        仅被分配为审核人（项目经理）且任务处于「待审核人确认」时，才能通过或拒绝。
      </div>

      <section className="review-section">
        <div className="rv-toolbar">
          <div className="rv-toolbar-filters">
            <span className="rv-toolbar-label">状态筛选</span>
            <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
              <option value="">全部状态</option>
              <option value="pending_evidence">待补充证据</option>
              <option value="pending_reviewer">待审核人确认</option>
              <option value="approved">已通过</option>
              <option value="rejected">已拒绝</option>
            </select>
          </div>
          <div className="rv-toolbar-actions">
            <span className="rv-toolbar-hint">共 {filtered.length} 条</span>
            <button className="btn-small" onClick={reload}>
              刷新
            </button>
          </div>
        </div>
        {action.error && (
          <div className="rv-empty-desc" style={{ color: "var(--color-danger-fg, #b00)" }}>
            {action.error}
          </div>
        )}
      </section>

      <section className="review-section">
        <h3>审核队列</h3>
        <LoadingError
          loading={loading}
          forbidden={forbidden}
          error={error ? "审核队列暂时无法加载，请稍后重试" : null}
          empty={filtered.length === 0}
          loadingTitle="加载中…"
          forbiddenTitle="无审核权限"
          forbiddenDesc="当前身份（纯 admin）不是业务用户，无法查看业务审核队列。"
          emptyTitle="无审核任务"
          emptyDesc="当前没有与你相关的审核任务。"
          wrapperClassName="rv-empty-state"
          titleClassName="rv-empty-title"
          descClassName="rv-empty-desc"
        />
        {!loading && !forbidden && !error && filtered.length > 0 && (
          <DataTable columns={columns} rows={filtered} rowKey={(c) => c.id} />
        )}
      </section>

      <p className="page-help-line">
        资料进入资产区须先登记验证证据再由项目经理确认；审核职责与升级治理机制见{" "}
        <Link to="/help#review" className="page-help-link">
          使用说明 →
        </Link>
      </p>
    </div>
  );
}
