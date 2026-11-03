import DataTable from "../../../components/DataTable";
import PagePagination from "../../../components/PagePagination";
import { formatBeijingTime } from "../../../utils/time";
import { ListFilter } from "lucide-react";
import { jobOpLabel, jobStatusLabel, jobTone, safeJobOperation, safeJobStatus } from "./model";
import type { AdminIngestController } from "./useAdminIngest";
export function IngestJobRecords({ controller }: { controller: AdminIngestController }) {
  const {
    jobFiltersOpen,
    setJobFiltersOpen,
    jobTypeFilter,
    jobStatusFilter,
    jobDateFilter,
    setJobTypeFilter,
    setJobPage,
    setJobStatusFilter,
    setJobDateFilter,
    opsJobs,
    jobsState,
    loadOpsJobs,
    filteredJobs,
    currentJobPage,
    setSelectedJob,
    jobPageCount,
  } = controller;
  return (
    <section id="ingest-jobs" tabIndex={-1} className="ao84-jobs" aria-label="作业记录">
      <div className="ingest-record-toolbar">
        <button
          className="btn-small ingest-mobile-filter-toggle"
          aria-expanded={jobFiltersOpen}
          aria-controls="ingest-record-filters"
          onClick={() => setJobFiltersOpen(!jobFiltersOpen)}
        >
          <ListFilter size={15} aria-hidden="true" />
          {jobFiltersOpen ? "收起筛选" : "筛选记录"}
          {jobTypeFilter !== "all" || jobStatusFilter !== "all" || jobDateFilter
            ? "（已筛选）"
            : ""}
        </button>
        <div
          id="ingest-record-filters"
          className={`ingest-record-filters${jobFiltersOpen ? " is-open" : ""}`}
        >
          <label>
            操作类型
            <select
              value={jobTypeFilter}
              onChange={(event) => {
                setJobTypeFilter(event.target.value);
                setJobPage(1);
              }}
            >
              <option value="all">全部类型</option>
              {Object.entries(jobOpLabel).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            作业状态
            <select
              value={jobStatusFilter}
              onChange={(event) => {
                setJobStatusFilter(event.target.value);
                setJobPage(1);
              }}
            >
              <option value="all">全部状态</option>
              {Object.entries(jobStatusLabel).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            发起日期
            <input
              type="date"
              value={jobDateFilter}
              onChange={(event) => {
                setJobDateFilter(event.target.value);
                setJobPage(1);
              }}
            />
          </label>
          {(jobTypeFilter !== "all" || jobStatusFilter !== "all" || jobDateFilter) && (
            <button
              className="btn-small"
              onClick={() => {
                setJobTypeFilter("all");
                setJobStatusFilter("all");
                setJobDateFilter("");
                setJobPage(1);
              }}
            >
              清除筛选
            </button>
          )}
        </div>
        <p className="ingest-record-hint">
          仅展示最近 20 条作业；筛选在已加载的 {opsJobs.length} 条内生效。
        </p>
      </div>
      {jobsState === "error" && (
        <p role="alert" className="is-error">
          最近作业暂时无法加载。{opsJobs.length > 0 && "以下保留上次结果，状态可能已变化。"}
          <button className="btn-small" onClick={() => void loadOpsJobs()}>
            重试加载作业
          </button>
        </p>
      )}
      <DataTable
        ariaLabel="最近作业记录"
        rows={filteredJobs.slice((currentJobPage - 1) * 10, currentJobPage * 10)}
        rowKey={(job) => job.job_id}
        loading={jobsState === "loading" && opsJobs.length === 0}
        loadingText="正在读取作业状态…"
        emptyText={
          jobsState === "error"
            ? "暂无可显示的作业记录"
            : opsJobs.length
              ? "当前筛选下没有作业，请调整筛选条件。"
              : "当前没有索引维护作业。"
        }
        tableClassName="product-data-table ingest-job-table"
        columns={[
          {
            key: "operation",
            header: "操作类型",
            render: (job) => <strong>{safeJobOperation(job.operation_type)}</strong>,
          },
          {
            key: "requested",
            header: "发起时间",
            render: (job) => (
              <time>{job.requested_at ? formatBeijingTime(job.requested_at) : "未记录"}</time>
            ),
          },
          {
            key: "status",
            header: "状态",
            render: (job) => (
              <span className={`ao84-status is-${jobTone(job.status)}`}>
                {safeJobStatus(job.status)}
              </span>
            ),
          },
          {
            key: "result",
            header: "处理结果",
            render: (job) => (
              <span className="ingest-job-result">
                共 {job.total_count} · 成功 {job.success_count} · 失败 {job.failed_count} · 跳过{" "}
                {job.skipped_count}
                {(job.pending_count ?? 0) > 0 && <small>提交时待索引 {job.pending_count}</small>}
              </span>
            ),
          },
          {
            key: "action",
            header: "操作",
            render: (job) => (
              <button type="button" className="btn-small" onClick={() => setSelectedJob(job)}>
                查看详情
              </button>
            ),
          },
        ]}
      />
      <PagePagination
        className="ingest-record-pagination"
        ariaLabel="作业记录分页"
        page={currentJobPage}
        totalPages={jobPageCount}
        onPageChange={setJobPage}
        summary={`匹配 ${filteredJobs.length} 条 · 第 ${currentJobPage} / ${jobPageCount} 页`}
      />
    </section>
  );
}
