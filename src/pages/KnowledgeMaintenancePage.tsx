import { KnowledgeInsightsButton } from "../components/operations/ReadTools";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/http";
import { fetchMaintenance, type MaintenancePage } from "../api/knowledgeTrust";
import { formatBeijingTime } from "../utils/time";
import { PageHeader, FilterBar, ProductPage } from "../components/ProductLayout";
import ListWorkspace from "../components/ListWorkspace";
import KnowledgeModuleFrame from "../components/KnowledgeModuleFrame";
import DataTable from "../components/DataTable";
import FormField from "../components/FormField";
import PagePagination from "../components/PagePagination";
import "./KnowledgeMaintenancePage.css";

export default function KnowledgeMaintenancePage() {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page")) || 1);
  const kind = params.get("kind") ?? "";
  const scope = params.get("scope") ?? "";
  const updateFilter = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };
  const setPage = (value: number) => updateFilter("page", String(value));
  const [retry, setRetry] = useState(0);
  const [data, setData] = useState<MaintenancePage | null>(null);
  const [error, setError] = useState("");
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
    <KnowledgeModuleFrame>
      <ProductPage className="knowledge-maintenance-page">
        <PageHeader
          title="知识维护"
          actions={<KnowledgeInsightsButton />}
          description="你负责的待安排、待复核和待纠错资料，以及等待你验证的处理结果。"
        />
        <ListWorkspace className="maintenance-workspace" label="维护待办">
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
              <FilterBar ariaLabel="维护待办本页筛选" actions={<span>共 {data.total} 项待办</span>}>
                <FormField label="本页待办类型">
                  <select
                    value={kind}
                    onChange={(event) => updateFilter("kind", event.target.value)}
                  >
                    <option value="">全部类型</option>
                    {Object.entries(labels).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </FormField>
                <FormField label="本页范围">
                  <select
                    value={scope}
                    onChange={(event) => updateFilter("scope", event.target.value)}
                  >
                    <option value="">全部范围</option>
                    <option value="personal">个人</option>
                    <option value="project">项目</option>
                    <option value="company">公司</option>
                  </select>
                </FormField>
              </FilterBar>
              <p className="list-workspace-note">到期不会自动归档，旧版需人工确认处理。</p>
              <DataTable
                ariaLabel="知识维护待办"
                rows={items}
                rowKey={(item) => item.asset_id}
                columns={[
                  { key: "title", header: "资料", render: (item) => item.title },
                  {
                    key: "scope",
                    header: "范围",
                    render: (item) =>
                      ({ personal: "个人", project: "项目", company: "公司" })[item.scope] ??
                      item.scope,
                  },
                  {
                    key: "due",
                    header: "复核日期",
                    render: (item) =>
                      item.review_due_at ? formatBeijingTime(item.review_due_at) : "尚未安排",
                  },
                  { key: "task", header: "待办", render: (item) => labels[taskKind(item)] },
                  {
                    key: "action",
                    header: "操作",
                    className: "maintenance-actions",
                    headerClassName: "maintenance-actions",
                    render: (item) => (
                      <Link
                        className="list-row-action"
                        to={`/knowledge/${encodeURIComponent(item.asset_id)}?maintenance=${taskKind(item)}`}
                        state={{
                          backTo: `/knowledge-maintenance${params.size ? `?${params}` : ""}`,
                          backLabel: "返回知识维护",
                          source: "task",
                        }}
                      >
                        {labels[taskKind(item)]}
                      </Link>
                    ),
                  },
                ]}
                emptyText={
                  data.items.length
                    ? "本页没有符合筛选的待办，可调整条件或查看其他页。"
                    : "暂无待办。资料更新、到期或收到纠错时会出现在这里。"
                }
              />
              <PagePagination
                ariaLabel="维护待办分页"
                page={page}
                totalPages={Math.max(1, Math.ceil(data.total / data.page_size))}
                onPageChange={setPage}
                summary={`第 ${page} 页，本页显示 ${items.length} 项`}
              />
            </>
          )}
        </ListWorkspace>
      </ProductPage>
    </KnowledgeModuleFrame>
  );
}
