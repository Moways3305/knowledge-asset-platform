import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ControlledBulkRequestError } from "../api/bulk";
import { ApiError } from "../api/http";
import {
  approveOriginalAccess,
  bulkOriginalAccessAction,
  fetchOriginalAccessRequests,
  rejectOriginalAccess,
} from "../api/knowledge";
import DataTable, { type Column } from "../components/DataTable";
import ConfirmDialog from "../components/ConfirmDialog";
import { BulkSelectionRail, SelectionCheckbox } from "../components/BulkSelection";
import GovernanceWorkspace from "../components/GovernanceWorkspace";
import type { OriginalAccessRequestDTO } from "../types/originalAccess";
import { formatBeijingTime } from "../utils/time";

const SAFE_FALLBACK = "信息待确认";

const statusLabel: Record<string, string> = {
  pending: "待审批",
  approved: "已通过",
  rejected: "已拒绝",
  cancelled: "已取消",
};
const grantLabel: Record<string, string> = {
  active: "授权有效",
  expired: "授权已到期",
  revoked: "授权已撤销",
};

const statusTone: Record<string, string> = {
  pending: "is-pending",
  approved: "is-success",
  rejected: "is-danger",
  cancelled: "is-neutral",
};

const scopeLabel: Record<string, string> = {
  personal: "个人知识",
  project: "项目知识",
  company: "公司知识",
};

type Box = "inbox" | "mine";
type Feedback = { tone: "success" | "error"; text: string } | null;

function isForbidden(error: unknown) {
  return error instanceof ApiError && error.status === 403;
}

function safeTitle(item: OriginalAccessRequestDTO) {
  return item.asset_title?.trim() || "待确认资产";
}

export default function OriginalAccessPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [box, setBox] = useState<Box>(searchParams.get("box") === "inbox" ? "inbox" : "mine");
  const [items, setItems] = useState<OriginalAccessRequestDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkAction, setBulkAction] = useState<"approve" | "reject" | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const requestRef = useRef(0);
  const bulkRunRef = useRef(false);

  useEffect(() => {
    const requested = searchParams.get("box");
    if (requested === "mine" || requested === "inbox") setBox(requested);
  }, [searchParams]);

  const load = useCallback(async () => {
    const requestId = ++requestRef.current;
    setLoading(true);
    setForbidden(false);
    setLoadFailed(false);
    setFeedback(null);
    setSelectedIds([]);
    setItems([]);
    try {
      const next = await fetchOriginalAccessRequests(box);
      if (requestId !== requestRef.current) return;
      setItems(next.items);
    } catch (error) {
      if (requestId !== requestRef.current) return;
      setForbidden(isForbidden(error));
      setLoadFailed(!isForbidden(error));
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, [box]);

  useEffect(() => {
    void load();
    return () => {
      requestRef.current += 1;
    };
  }, [load]);

  const act = async (item: OriginalAccessRequestDTO, kind: "approve" | "reject") => {
    if (box !== "inbox" || item.status !== "pending") return;
    setBusyId(item.request_id);
    setFeedback(null);
    try {
      if (kind === "approve") {
        await approveOriginalAccess(item.request_id);
      } else {
        await rejectOriginalAccess(item.request_id);
      }
      await load();
      setFeedback({
        tone: "success",
        text: kind === "approve" ? "原文访问申请已通过。" : "原文访问申请已拒绝。",
      });
    } catch {
      setFeedback({ tone: "error", text: "操作未完成，请稍后重试。" });
    } finally {
      setBusyId(null);
    }
  };

  const eligibleItems = items.filter((item) => box === "inbox" && item.status === "pending");
  const selectedEligible = eligibleItems.filter((item) => selectedIds.includes(item.request_id));
  const pageAllSelected =
    eligibleItems.length > 0 && selectedEligible.length === eligibleItems.length;
  const pageIndeterminate = selectedEligible.length > 0 && !pageAllSelected;

  const runBulk = async () => {
    if (!bulkAction || selectedEligible.length === 0 || bulkRunRef.current) return;
    const selectionSnapshot = selectedEligible.map((item) => item.request_id);
    const selectionRequest = requestRef.current;
    bulkRunRef.current = true;
    setBulkBusy(true);
    try {
      const result = await bulkOriginalAccessAction({
        itemIds: selectionSnapshot,
        action: bulkAction,
      });
      setBulkAction(null);
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

  const columns: Column<OriginalAccessRequestDTO>[] = [
    {
      key: "select",
      header: (
        <SelectionCheckbox
          checked={pageAllSelected}
          indeterminate={pageIndeterminate}
          disabled={eligibleItems.length === 0 || bulkBusy}
          label="全选当前页可审批申请"
          onChange={() =>
            setSelectedIds(pageAllSelected ? [] : eligibleItems.map((item) => item.request_id))
          }
        />
      ),
      headerClassName: "gw-col-access-select",
      className: "gw-col-access-select",
      render: (item) => (
        <SelectionCheckbox
          checked={selectedIds.includes(item.request_id)}
          disabled={box !== "inbox" || item.status !== "pending" || bulkBusy}
          label={`选择原文访问申请 ${safeTitle(item)}`}
          onChange={() =>
            setSelectedIds((current) =>
              current.includes(item.request_id)
                ? current.filter((id) => id !== item.request_id)
                : [...current, item.request_id],
            )
          }
        />
      ),
    },
    {
      key: "asset",
      header: "资产标题",
      className: "gw-title-cell",
      headerClassName: "gw-col-access-title",
      render: safeTitle,
    },
    {
      key: "scope",
      header: "范围",
      headerClassName: "gw-col-access-scope",
      render: (item) => (
        <span className="gw-scope-tag">{scopeLabel[item.scope ?? ""] ?? SAFE_FALLBACK}</span>
      ),
    },
    {
      key: "requester",
      header: "申请人",
      headerClassName: "gw-col-access-requester",
      render: (item) => item.requester_name?.trim() || "未提供",
    },
    {
      key: "reason",
      header: "申请理由",
      className: "gw-reason",
      headerClassName: "gw-col-access-reason",
      render: (item) => item.reason?.trim() || "未填写",
    },
    {
      key: "status",
      header: "状态",
      headerClassName: "gw-col-access-status",
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
      headerClassName: "gw-col-access-time",
      render: (item) => formatBeijingTime(item.created_at),
    },
    box === "inbox"
      ? {
          key: "actions",
          header: "操作",
          headerClassName: "gw-col-access-actions",
          render: (item) => (
            <div className="gw-actions">
              {item.status === "pending" ? (
                <>
                  <button
                    className="gw-action is-primary"
                    type="button"
                    disabled={Boolean(busyId)}
                    onClick={() => void act(item, "approve")}
                  >
                    通过
                  </button>
                  <button
                    className="gw-action is-danger"
                    type="button"
                    disabled={Boolean(busyId)}
                    onClick={() => void act(item, "reject")}
                  >
                    拒绝
                  </button>
                </>
              ) : (
                <span className="gw-muted">—</span>
              )}
            </div>
          ),
        }
      : {
          key: "reviewed",
          header: "处理结果与授权",
          headerClassName: "gw-col-access-reviewed",
          render: (item) => (
            <div className="gw-request-result">
              <span className="gw-muted">
                {item.reviewer_name?.trim()
                  ? `${item.reviewer_name} · ${formatBeijingTime(item.reviewed_at)}`
                  : item.status === "pending"
                    ? "等待审批"
                    : "未提供审批人"}
              </span>
              {item.review_note?.trim() && <small>审批意见：{item.review_note}</small>}
              {item.grant_status && (
                <small>
                  {grantLabel[item.grant_status] ?? "授权状态已变化"}
                  {item.grant_status === "active" && item.grant_expires_at
                    ? ` · 至 ${formatBeijingTime(item.grant_expires_at)}`
                    : ""}
                </small>
              )}
              {item.can_reapply && (
                <Link
                  className="gw-reapply-note"
                  to={`/knowledge/${encodeURIComponent(item.asset_id)}`}
                >
                  返回资料重新申请
                </Link>
              )}
            </div>
          ),
        },
  ];

  const state = forbidden
    ? { title: "无原文访问权限", description: "当前账号无法查看原文访问申请。" }
    : loadFailed
      ? { title: "原文访问申请加载失败", description: "请稍后重试。" }
      : box === "inbox"
        ? { title: "暂无待审批申请", description: "当前没有需要处理的原文访问申请。" }
        : { title: "暂无申请记录", description: "当前没有原文访问申请记录。" };

  return (
    <GovernanceWorkspace active="original-access" loading={loading} onRefresh={() => void load()}>
      <div className="gw-toolbar" aria-label="原文访问队列">
        <div className="gw-box-switch" role="group" aria-label="申请范围">
          <button
            className={box === "inbox" ? "is-active" : ""}
            type="button"
            disabled={loading || Boolean(busyId)}
            aria-pressed={box === "inbox"}
            onClick={() => {
              setBox("inbox");
              setSearchParams({ box: "inbox" }, { replace: true });
            }}
          >
            待我审批
          </button>
          <button
            className={box === "mine" ? "is-active" : ""}
            type="button"
            disabled={loading || Boolean(busyId)}
            aria-pressed={box === "mine"}
            onClick={() => {
              setBox("mine");
              setSearchParams({ box: "mine" }, { replace: true });
            }}
          >
            我的申请
          </button>
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
          批量批准（{selectedEligible.length}）
        </button>
        <button
          className="gw-action is-danger"
          disabled={bulkBusy}
          onClick={() => setBulkAction("reject")}
          type="button"
        >
          批量拒绝（{selectedEligible.length}）
        </button>
      </BulkSelectionRail>

      <DataTable
        columns={columns}
        rows={items}
        rowKey={(item) => item.request_id}
        loading={loading}
        loadingText="正在加载原文访问申请…"
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
        tableClassName="gw-table gw-access-table"
        ariaLabel={box === "inbox" ? "待我审批的原文访问申请" : "我的原文访问申请"}
      />
      <ConfirmDialog
        open={bulkAction !== null}
        title={bulkAction === "approve" ? "批量批准原文访问" : "批量拒绝原文访问"}
        description={`将处理选中的 ${selectedEligible.length} 项申请；状态或权限已变化的申请会被安全跳过。`}
        confirmText={bulkAction === "approve" ? "确认批量批准" : "确认批量拒绝"}
        busy={bulkBusy}
        danger={bulkAction === "reject"}
        onConfirm={() => void runBulk()}
        onCancel={() => {
          if (!bulkBusy) setBulkAction(null);
        }}
      />
    </GovernanceWorkspace>
  );
}
