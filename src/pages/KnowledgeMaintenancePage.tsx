import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/http";
import { fetchMaintenance, type MaintenancePage } from "../api/knowledgeTrust";
import { formatBeijingTime } from "../utils/time";
import { PageHeader, FilterBar, ProductPage } from "../components/ProductLayout";
import PagePagination from "../components/PagePagination";
import "./KnowledgeMaintenancePage.css";

export default function KnowledgeMaintenancePage() {
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [data, setData] = useState<MaintenancePage | null>(null);
  const [error, setError] = useState("");
  const [kind, setKind] = useState("");
  const [scope, setScope] = useState("");
  const taskKind = (item: MaintenancePage["items"][number]) =>
    item.awaiting_my_verification ? "verify" : item.needs_correction ? "corrections" : "review";
  const labels: Record<string, string> = {
    verify: "验证处理结果",
    corrections: "处理纠错",
    review: "安排或完成复核",
  };
  const items =
    data?.items.filter(
      (item) => (!kind || taskKind(item) === kind) && (!scope || item.scope === scope),
    ) ?? [];
  useEffect(() => {
    let current = true;
    setData(null);
    setError("");
    void fetchMaintenance(page)
      .then((result) => {
        if (current) setData(result);
      })
      .catch((e: unknown) => {
        if (current) setError(e instanceof ApiError ? e.message : "维护待办加载失败，请重试。");
      });
    return () => {
      current = false;
    };
  }, [page, retry]);
  return (
    <ProductPage className="knowledge-maintenance-page">
      <PageHeader
        title="知识维护"
        description="你负责的待安排、待复核和待纠错资料，以及等待你验证的处理结果。"
      />
      {error && (
        <p role="alert">
          {error}{" "}
          <button type="button" onClick={() => setRetry((n) => n + 1)}>
            重试
          </button>
        </p>
      )}
      {!data && !error && <p role="status">正在加载维护待办…</p>}
      {data && (
        <>
          <p>共 {data.total} 项待办。到期不会自动归档，旧版需人工确认处理。</p>
          <FilterBar ariaLabel="维护待办本页筛选">
            <label>
              本页待办类型
              <select value={kind} onChange={(event) => setKind(event.target.value)}>
                <option value="">全部类型</option>
                {Object.entries(labels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              本页范围
              <select value={scope} onChange={(event) => setScope(event.target.value)}>
                <option value="">全部范围</option>
                <option value="personal">个人</option>
                <option value="project">项目</option>
                <option value="company">公司</option>
              </select>
            </label>
          </FilterBar>
          {items.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>资料</th>
                    <th>范围</th>
                    <th>复核日期</th>
                    <th>待办</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.asset_id}>
                      <td data-label="资料">{item.title}</td>
                      <td data-label="范围">
                        {{ personal: "个人", project: "项目", company: "公司" }[item.scope] ??
                          item.scope}
                      </td>
                      <td data-label="复核日期">
                        {item.review_due_at ? formatBeijingTime(item.review_due_at) : "尚未安排"}
                      </td>
                      <td data-label="待办">
                        {item.awaiting_my_verification
                          ? "验证处理结果"
                          : item.needs_correction
                            ? "处理纠错"
                            : "安排或完成复核"}
                      </td>
                      <td data-label="操作">
                        <Link
                          to={`/knowledge/${encodeURIComponent(item.asset_id)}?maintenance=${taskKind(item)}`}
                        >
                          {labels[taskKind(item)]}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>
              {data.items.length
                ? "本页没有符合筛选的待办，可调整条件或查看其他页。"
                : "暂无待办。资料更新、到期或收到纠错时会出现在这里。"}
            </p>
          )}
          <PagePagination
            ariaLabel="维护待办分页"
            page={page}
            totalPages={Math.max(1, Math.ceil(data.total / data.page_size))}
            onPageChange={setPage}
            summary={`第 ${page} 页，本页显示 ${items.length} 项`}
          />
        </>
      )}
    </ProductPage>
  );
}
