import { useState, useMemo, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import { ApiError, fetchAdminIngest } from "../api/client";
import type { AdminIngestItemDTO } from "../types/ingest";
import { formatBeijingTime } from "../utils/time";

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
  path_a_wecom: "企微微盘 Agent",
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
  { title: "AI 内容提取失败", desc: "不支持的格式或损坏文件会标记 failed（可在 /upload 人工补全后确认）。单文件上限为 25 MiB。", severity: "high" as const },
  { title: "脱敏失败", desc: "标记 failed，通知上传人和 Admin。检查文件是否加密或受保护；尝试另存为无保护格式后重新上传。", severity: "high" as const },
  { title: "WeKnora 写入失败", desc: "知识底座写入失败时回滚业务数据库写入，标记任务 failed 并触发告警。需检查底座可用性后由业务侧重新确认入库。", severity: "high" as const },
  { title: "哈希重复", desc: "系统按文件内容哈希做去重软提示，命中时不阻断入库，仅提示已存在相同内容的任务。", severity: "low" as const },
  { title: "AI 置信度低", desc: "AI 建议置信度偏低时仍可入库，但建议人工校正摘要与标签。低置信度不视为系统错误。", severity: "medium" as const },
];
const severityCls: Record<string, string> = {
  high: "ig-severity-high",
  medium: "ig-severity-medium",
  low: "ig-severity-low",
};

const fmtTime = (iso: string | null) => formatBeijingTime(iso); // 北京时间（PBC-10C）
const fmtConfidence = (c: number | null) => (c == null ? "—" : `${Math.round(c * 100)}%`);
const fmtNaming = (n: boolean | null) => (n == null ? "—" : n ? "合规" : "命名异常");

export default function AdminIngestPage() {
  const [items, setItems] = useState<AdminIngestItemDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState("");
  const [filterSource, setFilterSource] = useState("");
  const [viewingId, setViewingId] = useState<string | null>(null);

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
          : "加载入库运营列表失败（请确认后端已启动）"
      );
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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

  const viewingTask = viewingId ? items.find((t) => t.id === viewingId) ?? null : null;

  return (
    <div className="ingest-page">
      {/* Header + KPI */}
      <div className="ig-header">
        <div className="ig-header-text">
          <h2>知识入库管理</h2>
          <p>路径A（企微微盘 Agent）与路径B（本地上传）的资产化任务统一在此监控。本页展示后端安全运营元数据，不展示业务原文、抽取全文、存储引用或外部系统内部 id。</p>
        </div>
        <div className="kl-kpis">
          <div className="kl-kpi">
            <div className="kl-kpi-value ig-kpi-processing">{countByStatus("processing")}</div>
            <div className="kl-kpi-label">处理中</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value ig-kpi-pending">{countByStatus("pending_confirmation")}</div>
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

      {/* Path A note → real config lives in /admin/wecom-scan */}
      <section className="ingest-section">
        <div className="ig-alert ig-alert-info">
          <span className="ig-alert-indicator" />
          <span className="ig-alert-text">
            <strong>路径A（企微微盘）</strong> — 扫描目录配置、启停与运行记录见 <Link to="/admin/wecom-scan">微盘扫描</Link>。Path A 产生的入库任务（来源 = 企微微盘 Agent）与本地上传任务一并在下方队列展示；需经 <Link to="/upload">资产化确认工作台</Link> 人工确认才成资产。
          </span>
        </div>
      </section>

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
              <option value="path_a_wecom">企微微盘 Agent</option>
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
              <button className="btn-small" onClick={() => setViewingId(null)}>关闭</button>
            </div>
            <div className="ig-detail-grid">
              <div className="ig-detail-item">
                <span className="ig-detail-label">文件名</span>
                <span className="ig-detail-value ig-detail-mono">{viewingTask.source_file_name}</span>
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
                      <span className={`ig-target-badge ${scopeCls[viewingTask.target_scope] ?? ""}`}>
                        {scopeLabel[viewingTask.target_scope] ?? viewingTask.target_scope}
                      </span>
                      {viewingTask.target_scope === "project" && <span className="ig-zone-hint">zone = material</span>}
                    </>
                  ) : "—"}
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
                    ? (extractionLabel[viewingTask.extraction_status] ?? viewingTask.extraction_status)
                    : "—"}
                </span>
              </div>
              <div className="ig-detail-item">
                <span className="ig-detail-label">保密级别</span>
                <span className="ig-detail-value">
                  {viewingTask.confidentiality_level ? (
                    <span className={`confidentiality-badge confidentiality-${viewingTask.confidentiality_level}`}>
                      {confidentialityLabel[viewingTask.confidentiality_level] ?? viewingTask.confidentiality_level}
                    </span>
                  ) : "—"}
                </span>
              </div>
              <div className="ig-detail-item">
                <span className="ig-detail-label">AI 调用级别</span>
                <span className="ig-detail-value">
                  {viewingTask.ai_access_level ? (
                    <span className={`ai-access-badge ai-access-${viewingTask.ai_access_level}`}>
                      {aiAccessLabel[viewingTask.ai_access_level] ?? viewingTask.ai_access_level}
                    </span>
                  ) : "—"}
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
                  {viewingTask.result_asset_id
                    ? <Link to={`/knowledge/${viewingTask.result_asset_id}`}>查看资产 →</Link>
                    : "—"}
                </span>
              </div>
              {(viewingTask.confidentiality_level === "L4" || viewingTask.confidentiality_level === "L5") && (
                <div className="ig-detail-item ig-detail-full">
                  <span className="ig-detail-label">保密边界提示</span>
                  <span className="ig-detail-value confidentiality-l45-detail">L4/L5 文件不得进入开放式 AI 调用；仅可按脱敏/摘要策略处理。</span>
                </div>
              )}
              {(viewingTask.error_type || viewingTask.error_message) && (
                <div className="ig-detail-item ig-detail-full">
                  <span className="ig-detail-label">错误</span>
                  <span className="ig-detail-value">{viewingTask.error_type ?? ""} {viewingTask.error_message ?? ""}</span>
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
            <button className="btn-small" onClick={() => void load()}>重试</button>
          </div>
        ) : loading ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">加载中…</div>
            <p className="ig-empty-desc">正在从后端读取入库运营队列。</p>
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
                          {t.target_scope === "project" && <span className="ig-zone-hint">zone = material</span>}
                        </>
                      ) : "—"}
                    </td>
                    <td>{fmtNaming(t.naming_compliant)}</td>
                    <td>
                      {t.confidentiality_level ? (
                        <span className={`confidentiality-badge confidentiality-${t.confidentiality_level}`}>
                          {t.confidentiality_level}
                        </span>
                      ) : "—"}
                    </td>
                    <td>
                      {t.ai_access_level ? (
                        <span className={`ai-access-badge ai-access-${t.ai_access_level}`}>
                          {t.ai_access_level}
                        </span>
                      ) : "—"}
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
                      <button className="btn-small" onClick={() => setViewingId(t.id)}>查看</button>
                      {t.result_asset_id && (
                        <Link className="btn-small" to={`/knowledge/${t.result_asset_id}`}>资产</Link>
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
                ? "后端入库队列为空。可在 /upload 上传文件或在 /admin/wecom-scan 触发微盘扫描后再查看。"
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
        本页仅运营队列监控，不承担业务确认（业务确认在资产化确认工作台完成），仅展示安全运营元数据。目标库 / 分区规则与职责边界见 <Link to="/help#ingest" className="page-help-link">使用说明 →</Link>
      </p>
    </div>
  );
}
