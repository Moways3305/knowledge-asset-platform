import { useState, useMemo, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/http";
import { fetchAdminIngest } from "../api/ingest";
import {
  fetchOpsIndexing,
  fetchIndexingJobs,
  triggerIndexingRetry,
  triggerIndexingReparse,
} from "../api/admin";
import type { AdminIngestItemDTO } from "../types/ingest";
import type { OpsIndexingDTO, IndexingJobSummaryDTO } from "../types/ops";
import { formatBeijingTime } from "../utils/time";
import IndexDistribution from "../components/IndexDistribution";

// 索引运维作业状态 / 类型的安全中文标签。
const jobOpLabel: Record<string, string> = {
  retry_index: "批量重试索引",
  reparse: "重新解析",
};
const jobStatusLabel: Record<string, string> = {
  queued: "已入队",
  running: "执行中",
  completed: "已完成",
  completed_with_errors: "完成（部分失败）",
  failed: "作业失败",
};

// 状态 / 来源 / 目标库 / 抽取状态的安全标签（运营元数据，非业务原文）。
const statusLabel: Record<string, string> = {
  processing: "处理中",
  pending_confirmation: "待确认",
  completed: "已完成",
  failed: "失败",
};
const statusCls: Record<string, string> = {
  processing: "ig-status-processing",
  pending_confirmation: "ig-status-pending",
  completed: "ig-status-completed",
  failed: "ig-status-failed",
};

const sourceLabel: Record<string, string> = {
  path_a_wecom: "企业微信微盘",
  path_b_upload: "本地上传",
};
const sourceCls: Record<string, string> = {
  path_a_wecom: "ig-src-wecom",
  path_b_upload: "ig-src-local",
};

const scopeLabel: Record<string, string> = {
  personal: "个人知识库",
  project: "项目知识库",
  company: "公司知识库候选",
};
const scopeCls: Record<string, string> = {
  personal: "ig-target-personal",
  project: "ig-target-project",
  company: "ig-target-company",
};

const extractionLabel: Record<string, string> = {
  extracted: "抽取成功",
  unsupported: "暂不支持",
  empty: "未抽取到文本",
  failed: "抽取失败",
};

const confidentialityLabel: Record<string, string> = {
  L1: "L1 公开级",
  L2: "L2 内部参考级",
  L3: "L3 受限级",
  L4: "L4 商业秘密级",
  L5: "L5 严格商业秘密级",
};
const aiAccessLabel: Record<string, string> = {
  A1: "A1 可直接调用",
  A2: "A2 脱敏后调用",
  A3: "A3 摘要后调用",
  A4: "A4 禁止调用",
};

const exceptionGuide = [
  {
    title: "AI 内容提取失败",
    desc: "不支持的格式或损坏文件会标记 failed（可在 /upload 人工补全后确认）。单文件上限为 25 MiB。",
    severity: "high" as const,
  },
  {
    title: "脱敏失败",
    desc: "标记 failed，通知上传人和 Admin。检查文件是否加密或受保护；尝试另存为无保护格式后重新上传。",
    severity: "high" as const,
  },
  {
    title: "检索索引失败",
    desc: "资产已保存，但暂时不会出现在语义检索结果中。可在详情页单条重试，或在下方运维面板发起批量重试 / 重新解析。",
    severity: "high" as const,
  },
  {
    title: "哈希重复",
    desc: "系统按文件内容哈希做去重软提示，命中时不阻断入库，仅提示已存在相同内容的任务。",
    severity: "low" as const,
  },
  {
    title: "AI 置信度低",
    desc: "AI 建议置信度偏低时仍可入库，但建议人工校正摘要与标签。低置信度不视为系统错误。",
    severity: "medium" as const,
  },
];
const severityCls: Record<string, string> = {
  high: "ig-severity-high",
  medium: "ig-severity-medium",
  low: "ig-severity-low",
};

const fmtTime = (iso: string | null) => formatBeijingTime(iso); // 北京时间
const fmtConfidence = (c: number | null) => (c == null ? "—" : `${Math.round(c * 100)}%`);
const fmtNaming = (n: boolean | null) => (n == null ? "—" : n ? "合规" : "命名异常");

export default function AdminIngestPage() {
  const [items, setItems] = useState<AdminIngestItemDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState("");
  const [filterSource, setFilterSource] = useState("");
  const [viewingId, setViewingId] = useState<string | null>(null);
  // 索引运维面板数据（安全计数 + 最近失败列表）。
  const [opsIndex, setOpsIndex] = useState<OpsIndexingDTO | null>(null);
  // 批量运维控件状态 + 最近作业列表。
  const [opsJobs, setOpsJobs] = useState<IndexingJobSummaryDTO[]>([]);
  const [retryIncludeSkipped, setRetryIncludeSkipped] = useState(false);
  const [retryIncludeNotIndexed, setRetryIncludeNotIndexed] = useState(false);
  const [opsLimit, setOpsLimit] = useState(50);
  const [opsBusy, setOpsBusy] = useState(false);
  const [opsNote, setOpsNote] = useState<string | null>(null);

  const loadOpsJobs = useCallback(async () => {
    try {
      setOpsJobs((await fetchIndexingJobs()).items);
    } catch {
      setOpsJobs([]); // 无权 / 未就绪：静默。
    }
  }, []);

  const loadOpsIndex = useCallback(async () => {
    try {
      setOpsIndex(await fetchOpsIndexing());
    } catch {
      setOpsIndex(null); // 无权 / 后端未就绪：面板静默隐藏，不阻断入库列表。
    }
    void loadOpsJobs();
  }, [loadOpsJobs]);

  const handleBatchRetry = useCallback(async () => {
    setOpsBusy(true);
    setOpsNote(null);
    try {
      const statuses = ["index_failed"];
      if (retryIncludeSkipped) statuses.push("skipped");
      if (retryIncludeNotIndexed) statuses.push("not_indexed");
      const job = await triggerIndexingRetry({ scope: "all", statuses, limit: opsLimit });
      setOpsNote(
        `已入队批量重试（作业 ${jobStatusLabel[job.status] ?? job.status}）：共 ${job.total_count}，成功 ${job.success_count}，失败 ${job.failed_count}，跳过 ${job.skipped_count}。`,
      );
      await loadOpsIndex();
    } catch (e) {
      setOpsNote(e instanceof ApiError ? `发起失败：${e.message}` : "发起批量重试失败");
    } finally {
      setOpsBusy(false);
    }
  }, [retryIncludeSkipped, retryIncludeNotIndexed, opsLimit, loadOpsIndex]);

  const handleReparse = useCallback(async () => {
    setOpsBusy(true);
    setOpsNote(null);
    try {
      const job = await triggerIndexingReparse({
        scope: "all",
        parse_statuses: ["failed", "pending"],
        limit: opsLimit,
      });
      setOpsNote(
        `已入队重新解析（作业 ${jobStatusLabel[job.status] ?? job.status}）：共 ${job.total_count}，成功 ${job.success_count}，失败 ${job.failed_count}。`,
      );
      await loadOpsIndex();
    } catch (e) {
      setOpsNote(e instanceof ApiError ? `发起失败：${e.message}` : "发起重新解析失败");
    } finally {
      setOpsBusy(false);
    }
  }, [opsLimit, loadOpsIndex]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAdminIngest();
      setItems(data.items);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `${e.message}（${e.deniedReason ?? e.status}）`
          : "入库运营列表暂时无法加载，请稍后重试",
      );
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    void loadOpsIndex();
  }, [load, loadOpsIndex]);

  const countByStatus = useCallback(
    (s: string) => items.filter((t) => t.status === s).length,
    [items],
  );

  const filtered = useMemo(() => {
    let result = items;
    if (filterStatus) result = result.filter((t) => t.status === filterStatus);
    if (filterSource) result = result.filter((t) => t.source === filterSource);
    return result;
  }, [items, filterStatus, filterSource]);

  const viewingTask = viewingId ? (items.find((t) => t.id === viewingId) ?? null) : null;

  return (
    <div className="ingest-page">
      {/* Header + KPI */}
      <div className="ig-header">
        <div className="ig-header-text">
          <h2>知识入库管理</h2>
          <p>查看入库任务、处理失败项，并跟踪文件进入知识库的状态。</p>
        </div>
        <div className="kl-kpis">
          <div className="kl-kpi">
            <div className="kl-kpi-value ig-kpi-processing">{countByStatus("processing")}</div>
            <div className="kl-kpi-label">处理中</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value ig-kpi-pending">
              {countByStatus("pending_confirmation")}
            </div>
            <div className="kl-kpi-label">待确认</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value kl-kpi-success">{countByStatus("completed")}</div>
            <div className="kl-kpi-label">已完成</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value kl-kpi-warning">{countByStatus("failed")}</div>
            <div className="kl-kpi-label">失败</div>
          </div>
        </div>
      </div>

      {/* 企业微信微盘配置入口 */}
      <section className="ingest-section">
        <div className="ig-alert ig-alert-info">
          <span className="ig-alert-indicator" />
          <span className="ig-alert-text">
            <strong>企业微信微盘</strong> — 扫描目录配置、启停与运行记录见{" "}
            <Link to="/admin/wecom-scan">微盘扫描</Link>
            。微盘任务与本地上传任务一并在下方队列展示；需经{" "}
            <Link to="/upload">资产化确认工作台</Link> 人工确认才进入知识库。
          </span>
        </div>
      </section>

      {/* 检索索引运维面板（安全计数 + 最近失败列表 + 重试入口在详情页） */}
      {opsIndex && (
        <section className="ingest-section">
          <div className="ig-detail-panel">
            <div className="ig-detail-head">
              <span className="ig-detail-title">检索索引运维</span>
              <button className="btn-small" onClick={() => void loadOpsIndex()}>
                刷新
              </button>
            </div>
            <div style={{ marginTop: 8 }}>
              <IndexDistribution counts={opsIndex.counts} />
            </div>
            {/* 批量运维控件（批量重试 / 重新解析）。 */}
            <div
              className="ig-ops-actions"
              style={{
                marginTop: 12,
                display: "flex",
                flexWrap: "wrap",
                gap: 12,
                alignItems: "center",
              }}
            >
              <label className="ig-ops-check">
                <input
                  type="checkbox"
                  checked={retryIncludeSkipped}
                  onChange={(e) => setRetryIncludeSkipped(e.target.checked)}
                />{" "}
                含已跳过
              </label>
              <label className="ig-ops-check">
                <input
                  type="checkbox"
                  checked={retryIncludeNotIndexed}
                  onChange={(e) => setRetryIncludeNotIndexed(e.target.checked)}
                />{" "}
                含待索引
              </label>
              <label className="ig-ops-check">
                上限
                <select
                  value={opsLimit}
                  onChange={(e) => setOpsLimit(Number(e.target.value))}
                  style={{ marginLeft: 4 }}
                >
                  {[20, 50, 100, 200].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="btn-small"
                onClick={() => void handleBatchRetry()}
                disabled={opsBusy}
              >
                {opsBusy ? "处理中…" : "批量重试索引"}
              </button>
              <button className="btn-small" onClick={() => void handleReparse()} disabled={opsBusy}>
                {opsBusy ? "处理中…" : "重新解析"}
              </button>
            </div>
            <p className="au-note" style={{ marginTop: 6 }}>
              批量重试：默认处理「索引失败」，可勾选含「已跳过 / 待索引」。重新解析：对解析失败 /
              滞留的资产，受控重传刷新解析状态，
              <strong>不改变任何权限放行</strong>
              ，不让未授权用户读到原文。批量动作进入后台作业，不在请求内逐条阻塞。
            </p>
            {opsNote && (
              <p className="au-note" style={{ marginTop: 6 }}>
                {opsNote}
              </p>
            )}
            {!opsIndex.title_visible && (
              <p className="au-note" style={{ marginTop: 8 }}>
                当前为系统管理身份，业务资产标题已隐藏；批量重试 /
                重新解析为运维动作，只回安全统计，不展示业务原文 / 标题。
              </p>
            )}
            {/* 最近运维作业列表（安全统计；无标题 / 原文 / WeKnora id / 存储引用）。 */}
            {opsJobs.length > 0 && (
              <div className="ws-table-wrap" style={{ marginTop: 8 }}>
                <table className="ws-table">
                  <thead>
                    <tr>
                      <th>类型</th>
                      <th>状态</th>
                      <th>共/成/败/跳</th>
                      <th>发起人</th>
                      <th>发起时间</th>
                      <th>诊断</th>
                    </tr>
                  </thead>
                  <tbody>
                    {opsJobs.map((j) => (
                      <tr key={j.job_id}>
                        <td>{jobOpLabel[j.operation_type] ?? j.operation_type}</td>
                        <td>
                          <span
                            className={`ws-status-pill ${j.status === "failed" ? "ws-status-off" : "ws-status-on"}`}
                          >
                            {jobStatusLabel[j.status] ?? j.status}
                          </span>
                        </td>
                        <td>
                          {j.total_count} / {j.success_count} / {j.failed_count} / {j.skipped_count}
                        </td>
                        <td>{j.requested_by_name ?? "—"}</td>
                        <td className="ws-cell-time">{fmtTime(j.requested_at)}</td>
                        <td className="ws-cell-suggestion">{j.error_message ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {opsIndex.recent_failed.length > 0 ? (
              <div className="ws-table-wrap" style={{ marginTop: 8 }}>
                <table className="ws-table">
                  <thead>
                    <tr>
                      <th>资产</th>
                      <th>范围 / 项目</th>
                      <th>负责人</th>
                      <th>诊断（运营态）</th>
                      <th>处理建议</th>
                      <th>级别</th>
                      <th>更新时间</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {opsIndex.recent_failed.map((it) => (
                      <tr key={it.asset_id}>
                        <td>{it.title}</td>
                        <td>
                          {scopeLabel[it.scope] ?? it.scope}
                          {it.project_name ? ` · ${it.project_name}` : ""}
                        </td>
                        <td>{it.owner_name ?? "—"}</td>
                        <td className="ws-cell-suggestion">
                          {it.operator_error_message || it.index_error_code || "—"}
                        </td>
                        <td className="ws-cell-suggestion">{it.remediation_hint ?? "—"}</td>
                        <td>
                          <span
                            className={`ws-status-pill ${it.severity === "critical" || it.severity === "error" ? "ws-status-off" : "ws-status-on"}`}
                          >
                            {it.severity ?? "—"}
                          </span>
                        </td>
                        <td className="ws-cell-time">{fmtTime(it.updated_at)}</td>
                        <td>
                          {opsIndex.title_visible && (
                            <Link className="btn-small" to={`/knowledge/${it.asset_id}`}>
                              详情 / 重试
                            </Link>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="au-note" style={{ marginTop: 8 }}>
                  诊断为安全运营态文案（含配置项名，不含配置值 /
                  密钥）。业务用户在资产详情页只看到「资产已保存、可重试」的用户态提示。
                </p>
              </div>
            ) : (
              <p className="au-note" style={{ marginTop: 8 }}>
                当前无索引失败资产。
              </p>
            )}
          </div>
        </section>
      )}

      {/* Queue toolbar */}
      <section className="ingest-section">
        <div className="ig-toolbar">
          <div className="ig-toolbar-filters">
            <span className="ig-toolbar-label">队列筛选</span>
            <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
              <option value="">全部状态</option>
              <option value="processing">处理中</option>
              <option value="pending_confirmation">待确认</option>
              <option value="completed">已完成</option>
              <option value="failed">失败</option>
            </select>
            <select value={filterSource} onChange={(e) => setFilterSource(e.target.value)}>
              <option value="">全部来源</option>
              <option value="path_a_wecom">企业微信微盘</option>
              <option value="path_b_upload">本地上传</option>
            </select>
          </div>
          <div className="ig-toolbar-actions">
            <span className="ig-toolbar-hint">共 {filtered.length} 条任务</span>
            <button className="btn-small" onClick={() => void load()} disabled={loading}>
              {loading ? "加载中…" : "刷新"}
            </button>
          </div>
        </div>
      </section>

      {/* Detail panel */}
      {viewingTask && (
        <section className="ingest-section">
          <div className="ig-detail-panel">
            <div className="ig-detail-head">
              <span className="ig-detail-title">任务详情（运营元数据）</span>
              <button className="btn-small" onClick={() => setViewingId(null)}>
                关闭
              </button>
            </div>
            <div className="ig-detail-grid">
              <div className="ig-detail-item">
                <span className="ig-detail-label">文件名</span>
                <span className="ig-detail-value ig-detail-mono">
                  {viewingTask.source_file_name}
                </span>
              </div>
              <div className="ig-detail-item">
                <span className="ig-detail-label">来源渠道</span>
                <span className="ig-detail-value">
                  <span className={`ig-src-badge ${sourceCls[viewingTask.source] ?? ""}`}>
                    {sourceLabel[viewingTask.source] ?? viewingTask.source}
                  </span>
                </span>
              </div>
              <div className="ig-detail-item">
                <span className="ig-detail-label">状态</span>
                <span className="ig-detail-value">
                  <span className={`status-pill ${statusCls[viewingTask.status] ?? ""}`}>
                    {statusLabel[viewingTask.status] ?? viewingTask.status}
                  </span>
                </span>
              </div>
              <div className="ig-detail-item">
                <span className="ig-detail-label">目标知识库</span>
                <span className="ig-detail-value">
                  {viewingTask.target_scope ? (
                    <>
                      <span
                        className={`ig-target-badge ${scopeCls[viewingTask.target_scope] ?? ""}`}
                      >
                        {scopeLabel[viewingTask.target_scope] ?? viewingTask.target_scope}
                      </span>
                      {viewingTask.target_scope === "project" && (
                        <span className="ig-zone-hint">zone = material</span>
                      )}
                    </>
                  ) : (
                    "—"
                  )}
                </span>
              </div>
              <div className="ig-detail-item">
                <span className="ig-detail-label">命名状态</span>
                <span className="ig-detail-value">{fmtNaming(viewingTask.naming_compliant)}</span>
              </div>
              <div className="ig-detail-item">
                <span className="ig-detail-label">抽取状态</span>
                <span className="ig-detail-value">
                  {viewingTask.extraction_status
                    ? (extractionLabel[viewingTask.extraction_status] ??
                      viewingTask.extraction_status)
                    : "—"}
                </span>
              </div>
              <div className="ig-detail-item">
                <span className="ig-detail-label">保密级别</span>
                <span className="ig-detail-value">
                  {viewingTask.confidentiality_level ? (
                    <span
                      className={`confidentiality-badge confidentiality-${viewingTask.confidentiality_level}`}
                    >
                      {confidentialityLabel[viewingTask.confidentiality_level] ??
                        viewingTask.confidentiality_level}
                    </span>
                  ) : (
                    "—"
                  )}
                </span>
              </div>
              <div className="ig-detail-item">
                <span className="ig-detail-label">自动处理级别</span>
                <span className="ig-detail-value">
                  {viewingTask.ai_access_level ? (
                    <span className={`ai-access-badge ai-access-${viewingTask.ai_access_level}`}>
                      {aiAccessLabel[viewingTask.ai_access_level] ?? viewingTask.ai_access_level}
                    </span>
                  ) : (
                    "—"
                  )}
                </span>
              </div>
              <div className="ig-detail-item">
                <span className="ig-detail-label">置信度</span>
                <span className="ig-detail-value">{fmtConfidence(viewingTask.confidence)}</span>
              </div>
              <div className="ig-detail-item">
                <span className="ig-detail-label">创建时间</span>
                <span className="ig-detail-value">{fmtTime(viewingTask.created_at)}</span>
              </div>
              <div className="ig-detail-item">
                <span className="ig-detail-label">入库资产</span>
                <span className="ig-detail-value">
                  {viewingTask.result_asset_id ? (
                    <Link to={`/knowledge/${viewingTask.result_asset_id}`}>查看资产 →</Link>
                  ) : (
                    "—"
                  )}
                </span>
              </div>
              {(viewingTask.confidentiality_level === "L4" ||
                viewingTask.confidentiality_level === "L5") && (
                <div className="ig-detail-item ig-detail-full">
                  <span className="ig-detail-label">保密边界提示</span>
                  <span className="ig-detail-value confidentiality-l45-detail">
                    高保密级别内容仅在授权范围内查看和处理。
                  </span>
                </div>
              )}
              {(viewingTask.error_type || viewingTask.error_message) && (
                <div className="ig-detail-item ig-detail-full">
                  <span className="ig-detail-label">错误</span>
                  <span className="ig-detail-value">
                    {viewingTask.error_type ?? ""} {viewingTask.error_message ?? ""}
                  </span>
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {/* Task list */}
      <section className="ingest-section">
        <h3>入库任务列表</h3>
        {error ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">加载失败</div>
            <p className="ig-empty-desc">{error}</p>
            <button className="btn-small" onClick={() => void load()}>
              重试
            </button>
          </div>
        ) : loading ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">加载中…</div>
            <p className="ig-empty-desc">正在加载入库运营队列。</p>
          </div>
        ) : filtered.length > 0 ? (
          <div className="ingest-table-wrap">
            <table className="ingest-table">
              <thead>
                <tr>
                  <th>文件名</th>
                  <th>来源</th>
                  <th>目标库</th>
                  <th>命名</th>
                  <th>保密</th>
                  <th>AI</th>
                  <th>抽取</th>
                  <th>置信度</th>
                  <th>状态</th>
                  <th>创建时间</th>
                  <th>备注</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t) => (
                  <tr key={t.id} className={`ig-row ${statusCls[t.status] ?? ""}`}>
                    <td className="cell-filename">{t.source_file_name}</td>
                    <td>
                      <span className={`ig-src-badge ${sourceCls[t.source] ?? ""}`}>
                        {sourceLabel[t.source] ?? t.source}
                      </span>
                    </td>
                    <td>
                      {t.target_scope ? (
                        <>
                          <span className={`ig-target-badge ${scopeCls[t.target_scope] ?? ""}`}>
                            {scopeLabel[t.target_scope] ?? t.target_scope}
                          </span>
                          {t.target_scope === "project" && (
                            <span className="ig-zone-hint">zone = material</span>
                          )}
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>{fmtNaming(t.naming_compliant)}</td>
                    <td>
                      {t.confidentiality_level ? (
                        <span
                          className={`confidentiality-badge confidentiality-${t.confidentiality_level}`}
                        >
                          {t.confidentiality_level}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {t.ai_access_level ? (
                        <span className={`ai-access-badge ai-access-${t.ai_access_level}`}>
                          {t.ai_access_level}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {t.extraction_status
                        ? (extractionLabel[t.extraction_status] ?? t.extraction_status)
                        : "—"}
                    </td>
                    <td>{fmtConfidence(t.confidence)}</td>
                    <td>
                      <span className={`status-pill ${statusCls[t.status] ?? ""}`}>
                        {statusLabel[t.status] ?? t.status}
                      </span>
                    </td>
                    <td className="cell-time">{fmtTime(t.created_at)}</td>
                    <td className="cell-reason">{t.error_message || t.error_type || "—"}</td>
                    <td className="cell-actions">
                      <button className="btn-small" onClick={() => setViewingId(t.id)}>
                        查看
                      </button>
                      {t.result_asset_id && (
                        <Link className="btn-small" to={`/knowledge/${t.result_asset_id}`}>
                          资产
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="ig-empty-state">
            <div className="ig-empty-title">暂无入库任务</div>
            <p className="ig-empty-desc">
              {items.length === 0
                ? "入库队列为空。可前往资产化确认工作台上传文件，或触发微盘扫描后再查看。"
                : "当前筛选条件下没有任务。尝试调整状态或来源筛选。"}
            </p>
          </div>
        )}
      </section>

      {/* Exception guide */}
      <section className="ingest-section">
        <h3>异常处理指南</h3>
        <div className="ig-exception-grid">
          {exceptionGuide.map((e) => (
            <div key={e.title} className={`ig-exception-card ${severityCls[e.severity]}`}>
              <div className="ig-exception-head">
                <span className="ig-exception-title">{e.title}</span>
                <span className={`ig-severity-badge ${severityCls[e.severity]}`}>
                  {e.severity === "high" ? "高" : e.severity === "medium" ? "中" : "低"}
                </span>
              </div>
              <p className="ig-exception-desc">{e.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <p className="page-help-line">
        本页仅运营队列监控，不承担业务确认（业务确认在资产化确认工作台完成），仅展示安全运营元数据。目标库
        / 分区规则与职责边界见{" "}
        <Link to="/help#ingest" className="page-help-link">
          使用说明 →
        </Link>
      </p>
    </div>
  );
}
