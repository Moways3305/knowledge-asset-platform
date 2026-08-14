import type { WecomScanConfigDTO, WecomScanRecordDTO } from "../../types/wecom";
import { formatBeijingTime } from "../../utils/time";
import { scanStatusLabel, scopeLabel } from "./labels";

interface Props {
  configs: WecomScanConfigDTO[];
  latest: Record<string, WecomScanRecordDTO | null>;
  loading: boolean;
  error: string | null;
  busyId: string | null;
  selectedId: string | null;
  canEdit: boolean;
  onReload: () => void;
  onSelect: (id: string) => void;
  onEdit: (config: WecomScanConfigDTO) => void;
  onToggle: (config: WecomScanConfigDTO) => void;
  onScan: (config: WecomScanConfigDTO) => void;
}

function runSummary(record: WecomScanRecordDTO | null | undefined) {
  if (!record) return "暂无运行";
  const status = scanStatusLabel[record.scan_status] ?? "未知";
  return `${status} · 新增 ${record.new_count} · 失败 ${record.failed_count}`;
}

function issueSummary(config: WecomScanConfigDTO, record: WecomScanRecordDTO | null | undefined) {
  if (!config.enabled) return "配置已停用";
  if (config.scan_space_status !== "ready") return "项目空间不可用";
  if (config.manager_access_status === "identity_link_required") return "项目经理需绑定企微身份";
  if (config.manager_access_status !== "ready") return "负责人权限未就绪";
  if ((record?.failed_count ?? 0) > 0) return `最近扫描失败 ${record?.failed_count} 项`;
  return "无异常";
}

export default function WecomScanConfigList({
  configs,
  latest,
  loading,
  error,
  busyId,
  selectedId,
  canEdit,
  onReload,
  onSelect,
  onEdit,
  onToggle,
  onScan,
}: Props) {
  if (error)
    return (
      <div className="ws87-table-state is-danger">
        <strong>配置加载失败</strong>
        <span>{error}</span>
        <button className="btn-small" onClick={onReload}>
          重试
        </button>
      </div>
    );
  if (loading) return <div className="ws87-table-state">正在加载扫描配置…</div>;
  if (configs.length === 0)
    return (
      <div className="ws87-table-state">
        <strong>尚未配置微盘扫描</strong>
        <span>
          {canEdit
            ? "通过页首“新增扫描配置”为项目创建专属扫描空间。"
            : "当前没有可查看的扫描配置。"}
        </span>
      </div>
    );

  return (
    <div className="ws87-table-wrap">
      <table className="ws87-table">
        <thead>
          <tr>
            <th>扫描配置</th>
            <th>目标范围</th>
            <th>任务归属</th>
            <th>状态</th>
            <th>最近扫描</th>
            <th>运行摘要</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {configs.map((config) => {
            const busy = busyId === config.id;
            const needsAction =
              config.enabled &&
              (config.scan_space_status !== "ready" ||
                config.manager_access_status !== "ready" ||
                (latest[config.id]?.failed_count ?? 0) > 0);
            return (
              <tr
                key={config.id}
                className={`${needsAction ? "is-actionable" : ""} ${!config.enabled ? "is-disabled" : ""} ${selectedId === config.id ? "is-selected" : ""}`}
              >
                <td data-label="扫描配置">
                  {needsAction && <span className="ws87-disposition">需处置</span>}
                  <strong>{config.name || "未命名配置"}</strong>
                  <button className="ws87-record-link" onClick={() => onSelect(config.id)}>
                    查看记录
                  </button>
                </td>
                <td data-label="目标范围">
                  <span className={`ws87-scope is-${config.scope_type}`}>
                    {scopeLabel[config.scope_type] ?? "其他"}
                  </span>
                  {config.scope_type === "project" && config.related_project_name && (
                    <small>{config.related_project_name}</small>
                  )}
                </td>
                <td data-label="任务归属">
                  {config.task_owner_name || "待补充"}
                  {config.task_owner_role_label && <small>{config.task_owner_role_label}</small>}
                </td>
                <td data-label="状态">
                  <span className={`ws87-enabled ${config.enabled ? "is-on" : "is-off"}`}>
                    {config.enabled ? "启用" : "停用"}
                  </span>
                </td>
                <td data-label="最近扫描">{formatBeijingTime(config.last_scan_at)}</td>
                <td data-label="问题与结果">
                  <span className={needsAction ? "ws87-issue is-danger" : "ws87-issue"}>
                    {issueSummary(config, latest[config.id])}
                  </span>
                  <small>{runSummary(latest[config.id])}</small>
                </td>
                <td data-label="操作">
                  <div className="ws87-row-actions">
                    {canEdit && (
                      <>
                        <button
                          className="btn-small"
                          onClick={() => onEdit(config)}
                          disabled={busy}
                        >
                          编辑
                        </button>
                        <button
                          className="btn-small"
                          onClick={() => onToggle(config)}
                          disabled={busy}
                        >
                          {config.enabled ? "停用" : "启用"}
                        </button>
                        <button
                          className="btn-small-primary"
                          onClick={() => onScan(config)}
                          disabled={!config.enabled || busy}
                        >
                          {busy ? "处理中…" : "扫描"}
                        </button>
                      </>
                    )}
                    {!canEdit && <span className="ws87-readonly">只读</span>}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
