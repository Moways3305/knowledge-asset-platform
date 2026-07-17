import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/http";
import {
  approveOriginalAccess,
  fetchOriginalAccessRequests,
  rejectOriginalAccess,
} from "../api/knowledge";
import DataTable, { type Column } from "../components/DataTable";
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
  const [box, setBox] = useState<Box>("inbox");
  const [items, setItems] = useState<OriginalAccessRequestDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const requestRef = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++requestRef.current;
    setLoading(true);
    setForbidden(false);
    setLoadFailed(false);
    setFeedback(null);
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

  const columns: Column<OriginalAccessRequestDTO>[] = [
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
          header: "审批记录",
          headerClassName: "gw-col-access-reviewed",
          render: (item) => (
            <span className="gw-muted">
              {item.reviewer_name?.trim()
                ? `${item.reviewer_name} · ${formatBeijingTime(item.reviewed_at)}`
                : "—"}
            </span>
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
            onClick={() => setBox("inbox")}
          >
            待我审批
          </button>
          <button
            className={box === "mine" ? "is-active" : ""}
            type="button"
            disabled={loading || Boolean(busyId)}
            aria-pressed={box === "mine"}
            onClick={() => setBox("mine")}
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
    </GovernanceWorkspace>
  );
}
