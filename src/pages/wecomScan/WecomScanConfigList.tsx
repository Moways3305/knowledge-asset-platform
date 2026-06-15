import type { WecomScanConfigDTO } from "../../types/wecom";
import { formatBeijingTime } from "../../utils/time";
import { scopeLabel } from "./labels";

// 扫描目录配置列表：工具栏（新增 / 刷新）+ 三态 + 配置表格。写动作由父级处理。
interface WecomScanConfigListProps {
  configs: WecomScanConfigDTO[];
  loading: boolean;
  error: string | null;
  busyId: string | null;
  onReload: () => void;
  onCreate: () => void;
  onSelect: (id: string) => void;
  onEdit: (cfg: WecomScanConfigDTO) => void;
  onToggle: (cfg: WecomScanConfigDTO) => void;
  onScan: (cfg: WecomScanConfigDTO) => void;
}

export default function WecomScanConfigList({
  configs, loading, error, busyId,
  onReload, onCreate, onSelect, onEdit, onToggle, onScan,
}: WecomScanConfigListProps) {
  return (
    <section className="ws-section">
      <div className="ig-toolbar">
        <h3 style={{ margin: 0 }}>扫描目录配置</h3>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn-small-primary" onClick={onCreate}>新增扫描配置</button>
          <button className="btn-small" onClick={onReload} disabled={loading}>
            {loading ? "加载中…" : "刷新"}
          </button>
        </div>
      </div>
      {error ? (
        <div className="ig-empty-state">
          <div className="ig-empty-title">加载失败</div>
          <p className="ig-empty-desc">{error}</p>
          <button className="btn-small" onClick={onReload}>重试</button>
        </div>
      ) : loading ? (
        <div className="ig-empty-state"><div className="ig-empty-title">加载中…</div></div>
      ) : configs.length === 0 ? (
        <div className="ig-empty-state">
          <div className="ig-empty-title">尚未配置微盘扫描目录</div>
          <p className="ig-empty-desc">还没有任何企微微盘扫描目录。点击下方按钮创建第一个扫描配置（需要 admin 权限）。</p>
          <button className="btn-small-primary" onClick={onCreate}>新增扫描配置</button>
        </div>
      ) : (
        <div className="ws-table-wrap">
          <table className="ws-table">
            <thead>
              <tr>
                <th>名称</th>
                <th>类型 / 目标</th>
                <th>业务归属人</th>
                <th>服务端目录配置标识</th>
                <th>状态</th>
                <th>最近扫描</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {configs.map((cfg) => (
                <tr key={cfg.id} className={!cfg.enabled ? "ws-row-disabled" : ""}>
                  <td>{cfg.name || "（未命名）"}</td>
                  <td>
                    <span className={`ws-scope-tag ${cfg.scope_type === "company" ? "ws-scope-company" : cfg.scope_type === "personal" ? "ws-scope-personal" : "ws-scope-project"}`}>
                      {scopeLabel[cfg.scope_type] ?? cfg.scope_type}
                    </span>
                    {cfg.scope_type === "project" && cfg.related_project_name && (
                      <span className="ws-cell-project"> · {cfg.related_project_name}</span>
                    )}
                  </td>
                  <td>
                    {cfg.task_owner_name ?? "—"}
                    {cfg.task_owner_role_label && <span className="ws-cell-project">（{cfg.task_owner_role_label}）</span>}
                  </td>
                  <td className="ws-cell-path" title={cfg.directory_path}><code>{cfg.directory_path}</code></td>
                  <td>
                    <span className={`ws-status-pill ${cfg.enabled ? "ws-status-on" : "ws-status-off"}`}>
                      {cfg.enabled ? "启用" : "停用"}
                    </span>
                  </td>
                  <td className="ws-cell-time">{formatBeijingTime(cfg.last_scan_at)}</td>
                  <td className="ws-cell-actions">
                    <button className="btn-small" onClick={() => onSelect(cfg.id)}>详情/记录</button>
                    <button className="btn-small" onClick={() => onEdit(cfg)}>编辑</button>
                    <button className="btn-small" onClick={() => onToggle(cfg)} disabled={busyId === cfg.id}>
                      {cfg.enabled ? "停用" : "启用"}
                    </button>
                    <button
                      className="btn-small-primary"
                      onClick={() => onScan(cfg)}
                      disabled={!cfg.enabled || busyId === cfg.id}
                    >
                      {busyId === cfg.id ? "扫描中…" : "手动扫描"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
