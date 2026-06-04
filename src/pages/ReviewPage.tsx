import { useState, useMemo, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  approveReview,
  fetchAuthMe,
  fetchReviews,
  rejectReview,
} from "../api/client";
import type { ReviewItemDTO } from "../types/review";

// 审核状态展示（IMPLEMENT-06 状态机：pending_evidence / pending_reviewer / approved / rejected）
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
  const [items, setItems] = useState<ReviewItemDTO[]>([]);
  const [currentUserId, setCurrentUserId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [filterStatus, setFilterStatus] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    setForbidden(false);
    Promise.all([fetchAuthMe(), fetchReviews()])
      .then(([me, reviews]) => {
        setCurrentUserId(me.userId);
        setItems(reviews);
        setLoading(false);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 403) setForbidden(true);
        else setError(e?.message ?? "加载失败");
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(
    () => (filterStatus ? items.filter((i) => i.status === filterStatus) : items),
    [items, filterStatus]
  );

  const countByStatus = (s: string) => items.filter((i) => i.status === s).length;

  const canAct = (it: ReviewItemDTO) =>
    it.status === "pending_reviewer" && it.reviewer_user_id === currentUserId;

  const handleApprove = useCallback(async (id: string) => {
    setActionError(null);
    try {
      await approveReview(id, "确认通过");
      load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "操作失败");
    }
  }, [load]);

  const handleReject = useCallback(async (id: string) => {
    setActionError(null);
    try {
      await rejectReview(id, "审核未通过：需补充材料");
      load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "操作失败");
    }
  }, [load]);

  return (
    <div className="review-page">
      <div className="rv-header">
        <div className="rv-header-text">
          <h2>知识升级审核</h2>
          <p>项目资料 → 项目资产的审核闭环：登记验证证据后，由项目经理确认进入资产区（zone: material → asset）</p>
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
        审核队列来自真实后端 `/api/v1/reviews`。仅被分配为审核人（项目经理）且任务处于「待审核人确认」时，才能通过/拒绝。
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
            <button className="btn-small" onClick={load}>刷新</button>
          </div>
        </div>
        {actionError && <div className="rv-empty-desc" style={{ color: "var(--color-danger-fg, #b00)" }}>{actionError}</div>}
      </section>

      <section className="review-section">
        <h3>审核队列</h3>
        {loading ? (
          <div className="rv-empty-state"><div className="rv-empty-title">加载中…</div></div>
        ) : forbidden ? (
          <div className="rv-empty-state">
            <div className="rv-empty-title">无审核权限</div>
            <p className="rv-empty-desc">当前身份（纯 admin）不是业务用户，无法查看业务审核队列。</p>
          </div>
        ) : error ? (
          <div className="rv-empty-state">
            <div className="rv-empty-title">加载失败</div>
            <p className="rv-empty-desc">{error}（请确认后端服务已启动）</p>
          </div>
        ) : filtered.length > 0 ? (
          <div className="ingest-table-wrap">
            <table className="ingest-table">
              <thead>
                <tr>
                  <th>知识标题</th>
                  <th>审核类型</th>
                  <th>来源项目</th>
                  <th>证据数</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
                  <tr key={c.id}>
                    <td className="cell-review-title">{c.asset_title ?? c.target_asset_id}</td>
                    <td><span className="path-badge">{reviewTypeLabel[c.review_type] ?? c.review_type}</span></td>
                    <td className="cell-source">{c.project_name ?? "—"}</td>
                    <td className="cell-center">{c.evidence_count}</td>
                    <td><span className={`status-pill ${statusCls[c.status] ?? ""}`}>{statusLabel[c.status] ?? c.status}</span></td>
                    <td className="cell-actions">
                      {canAct(c) ? (
                        <>
                          <button className="btn-small btn-small-primary" onClick={() => handleApprove(c.id)}>通过</button>
                          <button className="btn-small btn-small-danger" onClick={() => handleReject(c.id)}>拒绝</button>
                        </>
                      ) : (
                        <span className="rv-evidence-summary">
                          {c.status === "pending_evidence" ? "待补充证据" : c.status === "pending_reviewer" ? "待指定审核人处理" : "—"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="rv-empty-state">
            <div className="rv-empty-title">无审核任务</div>
            <p className="rv-empty-desc">当前没有与你相关的审核任务。</p>
          </div>
        )}
      </section>

      <p className="page-help-line">
        material → asset 须先登记验证证据再由项目经理确认；审核职责与升级治理机制见 <Link to="/help#review" className="page-help-link">使用说明 →</Link>
      </p>
    </div>
  );
}
