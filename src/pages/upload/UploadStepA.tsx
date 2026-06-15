import { Link } from "react-router-dom";
import { formatBeijingTime } from "../../utils/time";
import { pendingStatusLabel } from "./uploadConstants";
import type { UploadFlow } from "./useUploadFlow";

// 路径 A：企微微盘待确认文件列表（真实后端，按权限只返回可确认任务）。
export default function UploadStepA({ flow }: { flow: UploadFlow }) {
  const {
    pendingTasks, pendingLoading, pendingError, loadPending,
    handleSelectPendingTask, taskId, flowState,
  } = flow;

  return (
    <section className="upload-section">
      <div className="up-agent-head">
        <h3>企微微盘待确认文件</h3>
        <button className="btn-secondary" onClick={() => void loadPending()} disabled={pendingLoading}>
          {pendingLoading ? "刷新中…" : "刷新"}
        </button>
      </div>
      <p className="correction-hint">
        以下文件由企微微盘扫描自动检测并完成 AI 抽取与内容处理，请选择一项进行人工校正与确认入库。仅显示你有权确认的任务。
      </p>

      {pendingLoading ? (
        <div className="up-agent-state up-agent-loading">正在加载企微微盘待确认任务…</div>
      ) : pendingError ? (
        <div className="up-agent-state up-agent-error">
          <span>{pendingError}</span>
          <button className="btn-secondary" onClick={() => void loadPending()}>重试</button>
        </div>
      ) : pendingTasks.length === 0 ? (
        <div className="up-agent-state up-agent-empty">
          <div className="up-agent-empty-title">暂无待确认的企微微盘文件</div>
          <p>企微微盘扫描尚未产出待确认任务，或你对现有任务没有确认权限。</p>
          <Link to="/admin/wecom-scan" className="up-path-a-queue-link">前往企微微盘扫描配置 / 手动扫描 →</Link>
        </div>
      ) : (
        <div className="up-agent-file-list">
          {pendingTasks.map((t) => {
            const selected = taskId === t.id;
            const loadingThis = selected && flowState === "processing";
            return (
              <button
                key={t.id}
                className={`up-agent-file-item ${selected ? "active" : ""} ${t.status === "failed" ? "failed" : ""}`}
                onClick={() => { if (!loadingThis) void handleSelectPendingTask(t); }}
                disabled={loadingThis}
              >
                <div className="up-agent-file-main">
                  <span className="up-agent-file-name">{t.source_file_name}</span>
                  <span className="ig-src-badge ig-src-wecom">企微微盘</span>
                  <span className={`up-agent-status up-agent-status-${t.status}`}>
                    {pendingStatusLabel[t.status] ?? t.status}
                  </span>
                </div>
                {t.suggested_title && (
                  <div className="up-agent-file-suggest">建议标题：{t.suggested_title}</div>
                )}
                <div className="up-agent-file-meta">
                  {t.confidence != null && <span>置信度 {Math.round(t.confidence * 100)}%</span>}
                  {t.created_at && <span>检测时间：{formatBeijingTime(t.created_at)}</span>}
                  {loadingThis && <span>正在加载 AI 建议…</span>}
                </div>
                {t.error_message && (
                  <div className="up-agent-file-error">处理异常：{t.error_message}</div>
                )}
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
