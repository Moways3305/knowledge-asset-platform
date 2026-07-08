import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/http";
import {
  fetchOriginalAccessRequests,
  approveOriginalAccess,
  rejectOriginalAccess,
} from "../api/knowledge";
import type { OriginalAccessRequestDTO } from "../types/originalAccess";
import { formatBeijingTime } from "../utils/time";

const statusLabel: Record<string, string> = {
  pending: "待审批",
  approved: "已通过",
  rejected: "已拒绝",
  cancelled: "已取消",
};
const statusCls: Record<string, string> = {
  pending: "oa-st-pending",
  approved: "oa-st-approved",
  rejected: "oa-st-rejected",
  cancelled: "oa-st-cancelled",
};

// 用户可见时间统一北京时间。
const fmt = (iso: string | null): string => formatBeijingTime(iso);

export default function OriginalAccessPage() {
  const [box, setBox] = useState<"inbox" | "mine">("inbox");
  const [items, setItems] = useState<OriginalAccessRequestDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const describeError = (e: unknown, fallback: string) =>
    e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : fallback;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setActionError(null);
    setActionNote(null);
    try {
      const data = await fetchOriginalAccessRequests(box);
      setItems(data.items);
    } catch (e) {
      setError(describeError(e, "加载原文访问申请失败"));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [box]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = useCallback(
    async (id: string, kind: "approve" | "reject") => {
      setBusyId(id);
      setActionError(null);
      setActionNote(null);
      try {
        const r =
          kind === "approve" ? await approveOriginalAccess(id) : await rejectOriginalAccess(id);
        setActionNote(
          kind === "approve" ? "已审批通过并生成原文访问授权。" : "已拒绝该原文访问申请。",
        );
        void r;
        await load();
      } catch (e) {
        setActionError(describeError(e, "操作失败"));
      } finally {
        setBusyId(null);
      }
    },
    [load],
  );

  return (
    <div className="oa-page">
      <div className="kl-header">
        <div className="kl-header-text">
          <h2>原文访问申请与授权</h2>
          <p>申请或审批原文查看权限。授权可撤销，也可设置有效期。</p>
        </div>
      </div>

      <section className="oa-section">
        <div className="oa-tabs">
          <button
            className={`oa-tab ${box === "inbox" ? "oa-tab-active" : ""}`}
            onClick={() => setBox("inbox")}
          >
            待我审批
          </button>
          <button
            className={`oa-tab ${box === "mine" ? "oa-tab-active" : ""}`}
            onClick={() => setBox("mine")}
          >
            我的申请
          </button>
          <button className="btn-small" onClick={() => void load()} disabled={loading}>
            {loading ? "加载中…" : "刷新"}
          </button>
        </div>

        {actionError && (
          <div className="au-error-banner">
            <p>{actionError}</p>
          </div>
        )}
        {actionNote && (
          <div className="up-submit-notice" style={{ color: "var(--color-success-fg, #176)" }}>
            {actionNote}
          </div>
        )}

        {error ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">无法加载</div>
            <p className="ig-empty-desc">{error}</p>
            <p className="ig-empty-desc">「待我审批」需项目经理、辅导老师、Boss 或咨询总监身份。</p>
            <button className="btn-small" onClick={() => void load()}>
              重试
            </button>
          </div>
        ) : loading ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">加载中…</div>
          </div>
        ) : items.length === 0 ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">
              {box === "inbox" ? "暂无待审批申请" : "你还没有原文访问申请"}
            </div>
            <p className="ig-empty-desc">
              {box === "inbox"
                ? "当前没有需要你处理的原文访问申请。"
                : "在知识详情页对无原文权限的资产可发起申请。"}
            </p>
          </div>
        ) : (
          <div className="perm-table-wrap">
            <table className="perm-table">
              <thead>
                <tr>
                  <th>资产</th>
                  <th>范围</th>
                  <th>申请人</th>
                  <th>理由</th>
                  <th>状态</th>
                  <th>提交时间</th>
                  {box === "inbox" && <th>操作</th>}
                  {box === "mine" && <th>审批人 / 时间</th>}
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.request_id}>
                    <td className="perm-cell-name">
                      <Link to={`/knowledge/${r.asset_id}`}>
                        {r.asset_title ?? r.asset_id.slice(0, 8)}
                      </Link>
                    </td>
                    <td>{r.scope ?? "—"}</td>
                    <td>{r.requester_name ?? "—"}</td>
                    <td className="oa-cell-reason">{r.reason || "—"}</td>
                    <td>
                      <span className={`oa-status-pill ${statusCls[r.status] ?? ""}`}>
                        {statusLabel[r.status] ?? r.status}
                      </span>
                    </td>
                    <td className="cell-time">{fmt(r.created_at)}</td>
                    {box === "inbox" && (
                      <td>
                        <button
                          className="btn-small-primary"
                          disabled={busyId === r.request_id}
                          onClick={() => void act(r.request_id, "approve")}
                        >
                          通过
                        </button>
                        <button
                          className="btn-small"
                          disabled={busyId === r.request_id}
                          onClick={() => void act(r.request_id, "reject")}
                        >
                          拒绝
                        </button>
                      </td>
                    )}
                    {box === "mine" && (
                      <td>
                        {r.reviewer_name ? `${r.reviewer_name} · ${fmt(r.reviewed_at)}` : "—"}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <p className="page-help-line">
        审批通过后可在有效期内查看原文，详细规则见{" "}
        <Link to="/help#review" className="page-help-link">
          使用说明 →
        </Link>
      </p>
    </div>
  );
}
