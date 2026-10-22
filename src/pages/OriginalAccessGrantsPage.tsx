import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/http";
import { fetchOriginalAccessGrants, revokeOriginalAccessGrant } from "../api/knowledge";
import ConfirmDialog from "../components/ConfirmDialog";
import DataTable, { type Column } from "../components/DataTable";
import GovernanceWorkspace from "../components/GovernanceWorkspace";
import TaskModal from "../components/TaskModal";
import type { AccessGrantHistoryDTO } from "../types/originalAccess";
import { formatBeijingTime } from "../utils/time";

type Status = "" | "active" | "expired" | "revoked";
const statusLabels: Record<string, string> = {
  active: "授权有效",
  expired: "授权已到期",
  revoked: "授权已撤销",
};
const scopes: Record<string, string> = {
  personal: "个人知识",
  project: "项目知识",
  company: "公司知识",
};

export default function OriginalAccessGrantsPage() {
  const [status, setStatus] = useState<Status>("");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<AccessGrantHistoryDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [target, setTarget] = useState<AccessGrantHistoryDTO | null>(null);
  const [historyTarget, setHistoryTarget] = useState<AccessGrantHistoryDTO | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const sequence = useRef(0);
  const submitting = useRef(false);

  const load = useCallback(async () => {
    const id = ++sequence.current;
    setLoading(true);
    setRows([]);
    setTotal(0);
    setLoadError("");
    setTarget(null);
    setHistoryTarget(null);
    try {
      const result = await fetchOriginalAccessGrants(status, offset);
      if (id !== sequence.current) return;
      setRows(result.items);
      setTotal(result.total);
    } catch (error) {
      if (id !== sequence.current) return;
      setLoadError(
        error instanceof ApiError && error.status === 403
          ? "当前身份不能查看原文授权记录。"
          : "授权记录加载失败，请刷新重试。",
      );
    } finally {
      if (id === sequence.current) setLoading(false);
    }
  }, [status, offset]);

  useEffect(() => {
    setFeedback("");
    void load();
    return () => {
      sequence.current += 1;
    };
  }, [load]);

  const revoke = async () => {
    if (!target || !reason.trim() || !target.can_revoke || submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setActionError("");
    try {
      await revokeOriginalAccessGrant(target.grant_id, reason.trim());
      await load();
      setFeedback("原文授权已撤销；已加载或缓存的内容无法收回，后续访问按实时权限重新校验。");
    } catch (error) {
      if (error instanceof ApiError && [403, 404, 409].includes(error.status)) {
        await load();
        setFeedback("授权状态或操作权限已变化，请核对刷新后的记录。");
      } else {
        setActionError("未能确认撤销结果，请先取消并刷新记录，再决定是否重试。");
      }
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };

  const columns: Column<AccessGrantHistoryDTO>[] = [
    {
      key: "asset",
      header: "资料",
      render: (item) => (
        <Link to={`/knowledge/${encodeURIComponent(item.asset_id)}`}>
          {item.asset_title || "待确认资料"}
        </Link>
      ),
    },
    { key: "scope", header: "范围", render: (item) => scopes[item.scope] ?? "信息待确认" },
    { key: "grantee", header: "被授权人", render: (item) => item.grantee_name || "未提供" },
    { key: "issuer", header: "授权人", render: (item) => item.granted_by_name || "未提供" },
    { key: "status", header: "状态", render: (item) => statusLabels[item.status] ?? "状态待确认" },
    {
      key: "time",
      header: "授权与到期时间",
      render: (item) => (
        <div className="gw-request-result">
          <span>{formatBeijingTime(item.created_at)}</span>
          <small>
            {item.expires_at ? `至 ${formatBeijingTime(item.expires_at)}` : "未设置到期时间"}
          </small>
        </div>
      ),
    },
    {
      key: "revoked",
      header: "撤销记录",
      render: (item) =>
        item.status === "revoked" ? (
          <button
            className="gw-action"
            type="button"
            disabled={busy || loading}
            onClick={() => setHistoryTarget(item)}
          >
            查看撤销记录
          </button>
        ) : (
          "—"
        ),
    },
    {
      key: "action",
      header: "操作",
      render: (item) =>
        item.can_revoke && item.status === "active" ? (
          <button
            className="gw-action is-danger"
            type="button"
            disabled={busy || loading}
            onClick={() => {
              setTarget(item);
              setReason("");
              setActionError("");
            }}
          >
            撤销授权
          </button>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <GovernanceWorkspace
      active="original-grants"
      loading={loading || busy}
      onRefresh={() => {
        setFeedback("");
        void load();
      }}
    >
      <div className="gw-toolbar">
        <label className="gw-filter-label">
          授权状态
          <select
            value={status}
            disabled={busy}
            onChange={(event) => {
              setStatus(event.target.value as Status);
              setOffset(0);
            }}
          >
            <option value="">全部状态</option>
            <option value="active">授权有效</option>
            <option value="expired">授权已到期</option>
            <option value="revoked">授权已撤销</option>
          </select>
        </label>
        <span className="gw-total">共 {total} 条</span>
      </div>
      <p>仅显示当前身份可查看的本人授权及可管理授权。撤销不改变人员角色或资料归属。</p>
      {feedback && (
        <div className="gw-feedback" role="status">
          {feedback}
        </div>
      )}
      {loadError && (
        <div className="gw-feedback is-error" role="alert">
          {loadError}
        </div>
      )}
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(item) => item.grant_id}
        loading={loading}
        ariaLabel="原文授权记录"
        wrapClassName="gw-table-wrap"
        tableClassName="gw-table"
        emptyText={loadError || "暂无当前身份可查看的授权记录。"}
      />
      <div className="gw-toolbar" aria-label="授权记录分页">
        <button
          className="product-button is-secondary is-small"
          type="button"
          disabled={loading || busy || offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 20))}
        >
          上一页
        </button>
        <span>第 {Math.floor(offset / 20) + 1} 页</span>
        <button
          className="product-button is-secondary is-small"
          type="button"
          disabled={loading || busy || offset + 20 >= total}
          onClick={() => setOffset(offset + 20)}
        >
          下一页
        </button>
      </div>
      <ConfirmDialog
        open={target !== null}
        title="撤销原文授权"
        danger
        busy={busy}
        confirmText="确认撤销授权"
        confirmDisabled={!reason.trim()}
        onConfirm={() => void revoke()}
        onCancel={() => {
          if (!busy) setTarget(null);
        }}
        error={actionError || null}
        errorDescription={actionError}
        description={
          target
            ? `撤销 ${target.grantee_name || "该用户"} 对「${target.asset_title}」的这条原文授权。此操作不改变其他授权；如仍有其他访问依据，原文可能仍可访问。`
            : ""
        }
      >
        <label className="gw-grant-reason">
          撤销理由
          <textarea
            value={reason}
            maxLength={1000}
            disabled={busy}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
      </ConfirmDialog>
      <TaskModal
        open={historyTarget !== null}
        title="撤销记录"
        size="small"
        onClose={() => setHistoryTarget(null)}
      >
        {historyTarget && (
          <dl className="gw-grant-history">
            <dt>资料</dt>
            <dd>{historyTarget.asset_title}</dd>
            <dt>被授权人</dt>
            <dd>{historyTarget.grantee_name || "未提供"}</dd>
            <dt>撤销人</dt>
            <dd>{historyTarget.revoked_by_name || "未提供"}</dd>
            <dt>撤销时间</dt>
            <dd>{formatBeijingTime(historyTarget.revoked_at)}</dd>
            <dt>撤销理由</dt>
            <dd>{historyTarget.revoke_reason || "未填写"}</dd>
          </dl>
        )}
      </TaskModal>
    </GovernanceWorkspace>
  );
}
