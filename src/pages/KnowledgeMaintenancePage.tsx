import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/http";
import { fetchMaintenance, type MaintenancePage } from "../api/knowledgeTrust";
import { formatBeijingTime } from "../utils/time";
import "./KnowledgeMaintenancePage.css";

export default function KnowledgeMaintenancePage() {
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [data, setData] = useState<MaintenancePage | null>(null);
  const [error, setError] = useState("");
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
    <main className="product-page knowledge-maintenance-page">
      <header>
        <h1>知识维护</h1>
        <p>你负责的待安排、待复核和待纠错资料，以及等待你验证的处理结果。</p>
      </header>
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
          {data.items.length ? (
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
                  {data.items.map((item) => (
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
                        <Link to={`/knowledge/${item.asset_id}`}>查看并处理</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>暂无待办。资料更新、到期或收到纠错时会出现在这里。</p>
          )}
          <nav aria-label="维护待办分页">
            <button type="button" disabled={page <= 1} onClick={() => setPage((n) => n - 1)}>
              上一页
            </button>
            <span> 第 {page} 页 </span>
            <button
              type="button"
              disabled={page * data.page_size >= data.total}
              onClick={() => setPage((n) => n + 1)}
            >
              下一页
            </button>
          </nav>
        </>
      )}
    </main>
  );
}
