import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/http";
import { fetchReviewPage } from "../api/review";
import DataTable, { type Column } from "../components/DataTable";
import GovernanceWorkspace from "../components/GovernanceWorkspace";
import type { ReviewItemDTO } from "../types/review";
import { formatBeijingTime } from "../utils/time";

const PAGE_SIZE = 20;
const SAFE_FALLBACK = "信息待确认";

const reviewTypeLabel: Record<string, string> = {
  material_to_asset: "资料资产化",
  personal_to_project: "个人知识升级",
  project_to_company: "公司资产升级",
  lifecycle_change: "生命周期变更",
  project_ingest_approval: "项目知识入库",
};

const statusLabel: Record<string, string> = {
  approved: "已通过",
  rejected: "已拒绝",
};

const reviewTypeFilters = [
  { value: "", label: "全部类型" },
  { value: "project_ingest_approval", label: "项目知识入库" },
  { value: "material_to_asset", label: "资料资产化" },
  { value: "personal_to_project", label: "个人知识升级" },
  { value: "project_to_company", label: "公司资产升级" },
  { value: "lifecycle_change", label: "生命周期变更" },
];

const statusFilters = [
  { value: "", label: "全部状态" },
  { value: "approved", label: "已通过" },
  { value: "rejected", label: "已拒绝" },
];

function safeTitle(item: ReviewItemDTO) {
  return item.asset_title?.trim() || "待确认知识";
}

function isForbidden(error: unknown) {
  return error instanceof ApiError && error.status === 403;
}

export default function ReviewCompletedPage() {
  const [reviewType, setReviewType] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<ReviewItemDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const requestRef = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++requestRef.current;
    setLoading(true);
    setForbidden(false);
    setLoadFailed(false);
    setItems([]);
    try {
      const response = await fetchReviewPage({
        queue: "completed",
        reviewType: reviewType || undefined,
        status: status || undefined,
        page,
        pageSize: PAGE_SIZE,
      });
      if (requestId !== requestRef.current) return;
      setItems(response.items);
      setTotal(response.total);
    } catch (error) {
      if (requestId !== requestRef.current) return;
      setForbidden(isForbidden(error));
      setLoadFailed(!isForbidden(error));
      setTotal(0);
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, [page, reviewType, status]);

  useEffect(() => {
    void load();
    return () => {
      requestRef.current += 1;
    };
  }, [load]);

  const columns: Column<ReviewItemDTO>[] = [
    { key: "title", header: "知识标题", className: "gw-title-cell", render: safeTitle },
    {
      key: "type",
      header: "审核类型",
      render: (item) => (
        <span className="gw-type-tag">{reviewTypeLabel[item.review_type] ?? SAFE_FALLBACK}</span>
      ),
    },
    {
      key: "project",
      header: "来源项目",
      render: (item) => <span className="gw-muted">{item.project_name?.trim() || "—"}</span>,
    },
    {
      key: "status",
      header: "状态",
      render: (item) => (
        <span className={`gw-status ${item.status === "approved" ? "is-success" : "is-danger"}`}>
          {statusLabel[item.status] ?? SAFE_FALLBACK}
        </span>
      ),
    },
    {
      key: "created",
      header: "提交时间",
      className: "gw-time",
      render: (item) => formatBeijingTime(item.created_at),
    },
    {
      key: "reviewed",
      header: "完成时间",
      className: "gw-time",
      render: (item) => formatBeijingTime(item.reviewed_at),
    },
  ];

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const state = forbidden
    ? { title: "无审核查看权限", description: "当前账号无法查看已完成审核任务。" }
    : loadFailed
      ? { title: "已完成任务加载失败", description: "请稍后重试。" }
      : { title: "暂无已完成任务", description: "当前筛选条件下没有已完成的审核任务。" };

  return (
    <GovernanceWorkspace active="review-completed" loading={loading} onRefresh={() => void load()}>
      <h2>已完成审核任务</h2>
      <div className="gw-toolbar" role="search" aria-label="已完成审核筛选">
        <div className="gw-toolbar-fields">
          <label className="gw-filter-label">
            <span>审核状态</span>
            <select
              aria-label="审核状态"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(1);
              }}
            >
              {statusFilters.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="gw-filter-label">
            <span>审核类型</span>
            <select
              aria-label="审核类型"
              value={reviewType}
              onChange={(event) => {
                setReviewType(event.target.value);
                setPage(1);
              }}
            >
              {reviewTypeFilters.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <span className="gw-total">共 {total} 条</span>
      </div>

      <DataTable
        columns={columns}
        rows={items}
        rowKey={(item) => item.id}
        loading={loading}
        loadingText="正在加载已完成审核任务…"
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
        ariaLabel="已完成审核任务列表"
      />

      <div className="pk-pagination" aria-label="已完成审核分页">
        <button
          className="product-button is-secondary is-small"
          type="button"
          disabled={loading || page <= 1}
          onClick={() => setPage((current) => Math.max(1, current - 1))}
        >
          上一页
        </button>
        <span>
          第 {page} / {totalPages} 页
        </span>
        <button
          className="product-button is-secondary is-small"
          type="button"
          disabled={loading || page >= totalPages}
          onClick={() => setPage((current) => current + 1)}
        >
          下一页
        </button>
      </div>
    </GovernanceWorkspace>
  );
}
