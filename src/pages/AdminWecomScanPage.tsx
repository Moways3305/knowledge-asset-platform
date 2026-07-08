import { useState, useMemo, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/http";
import {
  fetchWecomScanConfigs,
  fetchWecomScanOwnerOptions,
  fetchWecomScanProjectOptions,
  fetchWecomScanRecords,
  triggerWecomScan,
  updateWecomScanConfig,
} from "../api/admin";
import type {
  WecomOwnerOptionDTO,
  WecomProjectOptionDTO,
  WecomScanConfigDTO,
  WecomScanRecordDTO,
} from "../types/wecom";
import { formatBeijingTime } from "../utils/time";
import { scanStatusCls, scanStatusLabel, scopeLabel } from "./wecomScan/labels";
import WecomScanConfigForm from "./wecomScan/WecomScanConfigForm";
import WecomScanConfigList from "./wecomScan/WecomScanConfigList";

const fmtTime = (iso: string | null) => formatBeijingTime(iso); // 北京时间

export default function AdminWecomScanPage() {
  const [configs, setConfigs] = useState<WecomScanConfigDTO[]>([]);
  const [loadingConfigs, setLoadingConfigs] = useState(true);
  const [configError, setConfigError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [records, setRecords] = useState<WecomScanRecordDTO[]>([]);
  const [loadingRecords, setLoadingRecords] = useState(false);
  const [recordError, setRecordError] = useState<string | null>(null);

  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [scanNote, setScanNote] = useState<string | null>(null);

  // 创建 / 编辑表单：editingConfig=null 表示新建。
  const [projectOptions, setProjectOptions] = useState<WecomProjectOptionDTO[]>([]);
  const [ownerOptions, setOwnerOptions] = useState<WecomOwnerOptionDTO[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [editingConfig, setEditingConfig] = useState<WecomScanConfigDTO | null>(null);

  const describeError = (e: unknown, fallback: string) =>
    e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : fallback;

  const loadConfigs = useCallback(async () => {
    setLoadingConfigs(true);
    setConfigError(null);
    try {
      const data = await fetchWecomScanConfigs();
      setConfigs(data.items);
    } catch (e) {
      setConfigError(describeError(e, "扫描配置暂时无法加载，请稍后重试"));
      setConfigs([]);
    } finally {
      setLoadingConfigs(false);
    }
  }, []);

  const loadRecords = useCallback(async (configId: string) => {
    setLoadingRecords(true);
    setRecordError(null);
    try {
      const data = await fetchWecomScanRecords(configId);
      setRecords(data.items);
    } catch (e) {
      setRecordError(describeError(e, "加载扫描记录失败"));
      setRecords([]);
    } finally {
      setLoadingRecords(false);
    }
  }, []);

  const loadProjectOptions = useCallback(async () => {
    try {
      const data = await fetchWecomScanProjectOptions();
      setProjectOptions(data.items);
    } catch {
      // 项目候选加载失败不阻断页面（创建项目级配置时再提示）。
      setProjectOptions([]);
    }
  }, []);

  const loadOwnerOptions = useCallback(async () => {
    try {
      const data = await fetchWecomScanOwnerOptions();
      setOwnerOptions(data.items);
    } catch {
      setOwnerOptions([]);
    }
  }, []);

  useEffect(() => {
    void loadConfigs();
    void loadProjectOptions();
    void loadOwnerOptions();
  }, [loadConfigs, loadProjectOptions, loadOwnerOptions]);

  const openCreate = useCallback(() => {
    setEditingConfig(null);
    setFormOpen(true);
  }, []);

  const openEdit = useCallback((cfg: WecomScanConfigDTO) => {
    setEditingConfig(cfg);
    setFormOpen(true);
  }, []);

  const selectConfig = useCallback(
    (id: string) => {
      setSelectedId(id);
      setScanNote(null);
      void loadRecords(id);
    },
    [loadRecords],
  );

  const handleToggle = useCallback(
    async (cfg: WecomScanConfigDTO) => {
      setBusyId(cfg.id);
      setActionError(null);
      try {
        await updateWecomScanConfig(cfg.id, { enabled: !cfg.enabled });
        await loadConfigs();
      } catch (e) {
        setActionError(describeError(e, "更新配置失败（启停需 admin 权限）"));
      } finally {
        setBusyId(null);
      }
    },
    [loadConfigs],
  );

  const handleScan = useCallback(
    async (cfg: WecomScanConfigDTO) => {
      setBusyId(cfg.id);
      setActionError(null);
      setScanNote(null);
      try {
        const rec = await triggerWecomScan(cfg.id);
        setScanNote(
          `扫描完成（${scanStatusLabel[rec.scan_status] ?? rec.scan_status}）：发现 ${rec.discovered_count} · 新增 ${rec.new_count} · 重复 ${rec.duplicate_count} · 失败 ${rec.failed_count}`,
        );
        setSelectedId(cfg.id);
        await Promise.all([loadConfigs(), loadRecords(cfg.id)]);
      } catch (e) {
        // 403=无权限；503=企业微信未配置。
        setActionError(describeError(e, "手动扫描失败"));
      } finally {
        setBusyId(null);
      }
    },
    [loadConfigs, loadRecords],
  );

  const stats = useMemo(() => {
    const enabled = configs.filter((c) => c.enabled).length;
    return { enabled, total: configs.length };
  }, [configs]);

  const selectedConfig = selectedId ? (configs.find((c) => c.id === selectedId) ?? null) : null;

  return (
    <div className="ws-page">
      {/* Header */}
      <div className="kl-header">
        <div className="kl-header-text">
          <h2>企微微盘扫描配置</h2>
          <p>
            管理企业微信微盘扫描目录，扫描发现的文件会进入资产化确认队列。本页仅展示安全运营状态。
          </p>
        </div>
        <div className="kl-kpis">
          <div className="kl-kpi">
            <div className="kl-kpi-value">{stats.enabled}</div>
            <div className="kl-kpi-label">启用配置</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value">{stats.total}</div>
            <div className="kl-kpi-label">配置总数</div>
          </div>
        </div>
      </div>

      {actionError && (
        <section className="ws-section">
          <div className="ws-note-hint" style={{ color: "var(--color-danger-fg, #b00)" }}>
            {actionError}
          </div>
        </section>
      )}
      {scanNote && (
        <section className="ws-section">
          <div className="ws-note-hint" style={{ color: "var(--color-success-fg, #176)" }}>
            {scanNote}
          </div>
        </section>
      )}

      {/* Create / edit form */}
      <WecomScanConfigForm
        open={formOpen}
        editingConfig={editingConfig}
        projectOptions={projectOptions}
        ownerOptions={ownerOptions}
        onClose={() => setFormOpen(false)}
        onSaved={(note) => {
          setScanNote(note);
          void loadConfigs();
        }}
      />

      {/* Config table */}
      <WecomScanConfigList
        configs={configs}
        loading={loadingConfigs}
        error={configError}
        busyId={busyId}
        onReload={() => void loadConfigs()}
        onCreate={openCreate}
        onSelect={selectConfig}
        onEdit={openEdit}
        onToggle={(cfg) => void handleToggle(cfg)}
        onScan={(cfg) => void handleScan(cfg)}
      />

      {/* Detail + records */}
      {selectedConfig && (
        <section className="ws-section">
          <div className="ws-detail-panel">
            <div className="ws-detail-head">
              <span className="ws-detail-title">配置详情与扫描记录</span>
              <button
                className="btn-small"
                onClick={() => {
                  setSelectedId(null);
                  setRecords([]);
                }}
              >
                关闭
              </button>
            </div>
            <div className="ws-detail-grid">
              <div className="ws-detail-item">
                <span className="ws-detail-label">目录归属</span>
                <span className="ws-detail-value">
                  <span
                    className={`ws-scope-tag ${selectedConfig.scope_type === "company" ? "ws-scope-company" : "ws-scope-project"}`}
                  >
                    {scopeLabel[selectedConfig.scope_type] ?? selectedConfig.scope_type}
                  </span>
                </span>
              </div>
              <div className="ws-detail-item">
                <span className="ws-detail-label">服务端目录配置标识</span>
                <span className="ws-detail-value ws-detail-path">
                  <code>{selectedConfig.directory_path}</code>
                </span>
              </div>
              <div className="ws-detail-item ws-detail-full">
                <span className="ws-detail-label">扫描范围说明</span>
                <span className="ws-detail-value">
                  扫描该目录下新增或更新的文件，生成 <code>ingest_task</code> 待确认记录。 Path A
                  文件不会直接入库，需经业务侧确认后方可进入知识库。
                </span>
              </div>
              <div className="ws-detail-item ws-detail-full">
                <span className="ws-detail-label">下游流程</span>
                <span className="ws-detail-value">
                  <div className="ws-detail-links">
                    <Link to="/upload" className="ws-detail-link">
                      资产化确认工作台 →
                    </Link>
                    <Link to="/admin/ingest" className="ws-detail-link">
                      入库管理 →
                    </Link>
                  </div>
                </span>
              </div>
            </div>

            <h4 style={{ marginTop: 16 }}>扫描记录</h4>
            {recordError ? (
              <div className="ig-empty-state">
                <div className="ig-empty-title">加载失败</div>
                <p className="ig-empty-desc">{recordError}</p>
              </div>
            ) : loadingRecords ? (
              <div className="ig-empty-state">
                <div className="ig-empty-title">加载中…</div>
              </div>
            ) : records.length === 0 ? (
              <div className="ig-empty-state">
                <div className="ig-empty-title">暂无扫描记录</div>
                <p className="ig-empty-desc">该配置尚未有扫描记录，可点击「手动扫描」触发一次。</p>
              </div>
            ) : (
              <div className="ws-table-wrap">
                <table className="ws-table">
                  <thead>
                    <tr>
                      <th>开始时间</th>
                      <th>完成时间</th>
                      <th>状态</th>
                      <th>发现</th>
                      <th>新增</th>
                      <th>重复</th>
                      <th>失败</th>
                      <th>错误</th>
                    </tr>
                  </thead>
                  <tbody>
                    {records.map((r) => (
                      <tr key={r.id}>
                        <td className="ws-cell-time">{fmtTime(r.scan_started_at)}</td>
                        <td className="ws-cell-time">{fmtTime(r.scan_completed_at)}</td>
                        <td>
                          <span
                            className={`ws-result-pill ${scanStatusCls[r.scan_status] ?? "ws-result-empty"}`}
                          >
                            {scanStatusLabel[r.scan_status] ?? r.scan_status}
                          </span>
                        </td>
                        <td className="ws-cell-num">{r.discovered_count}</td>
                        <td className="ws-cell-num">{r.new_count}</td>
                        <td className="ws-cell-num">{r.duplicate_count}</td>
                        <td className="ws-cell-num">{r.failed_count}</td>
                        <td className="ws-cell-suggestion">
                          {r.error_message || r.error_type || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>
      )}

      <p className="page-help-line">
        扫盘只发现文件并生成待确认任务，不直接入库；目标库与分区、权限与企微配置边界见{" "}
        <Link to="/help#ingest" className="page-help-link">
          使用说明 →
        </Link>
      </p>
    </div>
  );
}
