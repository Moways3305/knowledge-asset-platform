import { useState, useMemo, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  createWecomScanConfig,
  fetchWecomDriveDirectories,
  fetchWecomDriveSpaces,
  fetchWecomScanConfigs,
  fetchWecomScanOwnerOptions,
  fetchWecomScanProjectOptions,
  fetchWecomScanRecords,
  triggerWecomScan,
  updateWecomScanConfig,
} from "../api/client";
import type {
  WecomDriveDirectoryDTO,
  WecomDriveSpaceDTO,
  WecomOwnerOptionDTO,
  WecomProjectOptionDTO,
  WecomScanConfigDTO,
  WecomScanRecordDTO,
} from "../types/wecom";
import { formatBeijingTime } from "../utils/time";

const scopeLabel: Record<string, string> = {
  company: "公司级",
  project: "项目级",
  personal: "个人级",
};

const scopeOptions = [
  { value: "project", label: "项目知识库" },
  { value: "company", label: "公司知识库" },
  { value: "personal", label: "个人知识库" },
];

const scanStatusLabel: Record<string, string> = {
  completed: "完成",
  failed: "失败",
  running: "进行中",
  partial: "部分成功",
};
const scanStatusCls: Record<string, string> = {
  completed: "ws-result-success",
  failed: "ws-result-error",
  running: "ws-result-empty",
  partial: "ws-result-duplicate",
};

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

  // 创建 / 编辑表单状态。editingId=null 表示新建。
  const [projectOptions, setProjectOptions] = useState<WecomProjectOptionDTO[]>([]);
  const [ownerOptions, setOwnerOptions] = useState<WecomOwnerOptionDTO[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [fName, setFName] = useState("");
  const [fDir, setFDir] = useState("");
  const [fDirLabel, setFDirLabel] = useState("");  // 选择器生成的友好目录名
  const [pickerOpen, setPickerOpen] = useState(false);
  const [fScope, setFScope] = useState("project");
  const [fProjectId, setFProjectId] = useState("");
  const [fOwnerId, setFOwnerId] = useState("");
  const [fEnabled, setFEnabled] = useState(true);
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const describeError = (e: unknown, fallback: string) =>
    e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : fallback;

  const loadConfigs = useCallback(async () => {
    setLoadingConfigs(true);
    setConfigError(null);
    try {
      const data = await fetchWecomScanConfigs();
      setConfigs(data.items);
    } catch (e) {
      setConfigError(describeError(e, "加载扫描配置失败（请确认后端已启动）"));
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

  // 业务归属人候选按目标 scope 过滤（后端最终校验为准；前端仅提示合法候选）。
  const ownerCandidates = useMemo(() => {
    if (fScope === "project") {
      return fProjectId ? ownerOptions.filter((o) => o.project_ids.includes(fProjectId)) : [];
    }
    if (fScope === "company") {
      return ownerOptions.filter((o) => o.is_governance);
    }
    return ownerOptions; // personal：任意业务用户
  }, [ownerOptions, fScope, fProjectId]);

  const openCreate = useCallback(() => {
    setEditingId(null);
    setFName("");
    setFDir("");
    setFDirLabel("");
    setPickerOpen(false);
    setFScope("project");
    setFProjectId("");
    setFOwnerId("");
    setFEnabled(true);
    setSaveError(null);
    setFormOpen(true);
  }, []);

  const openEdit = useCallback((cfg: WecomScanConfigDTO) => {
    setEditingId(cfg.id);
    setFName(cfg.name ?? "");
    setFDir(cfg.directory_path);
    setFDirLabel("");
    setPickerOpen(false);
    setFScope(cfg.scope_type);
    setFProjectId(cfg.related_project_id ?? "");
    setFOwnerId(cfg.created_by);
    setFEnabled(cfg.enabled);
    setSaveError(null);
    setFormOpen(true);
  }, []);

  const handleSave = useCallback(async () => {
    setSaveError(null);
    if (!fName.trim()) { setSaveError("请填写配置名称"); return; }
    if (!fDir.trim()) { setSaveError("请填写微盘目录内部标识"); return; }
    if (fScope === "project" && !fProjectId) { setSaveError("项目级配置必须选择目标项目"); return; }
    if (!fOwnerId) { setSaveError("请选择待确认任务的业务归属人"); return; }
    setSaveBusy(true);
    const base = {
      name: fName.trim(),
      directory_path: fDir.trim(),
      target_scope: fScope,
      target_project_id: fScope === "project" ? fProjectId : null,
      task_owner_user_id: fOwnerId,
    };
    try {
      if (editingId) {
        await updateWecomScanConfig(editingId, { ...base, enabled: fEnabled });
        setScanNote("配置已更新");
      } else {
        await createWecomScanConfig({ ...base, enabled: fEnabled });
        setScanNote("配置已创建");
      }
      setFormOpen(false);
      await loadConfigs();
    } catch (e) {
      setSaveError(describeError(e, "保存配置失败（创建/编辑需 admin 权限）"));
    } finally {
      setSaveBusy(false);
    }
  }, [editingId, fName, fDir, fScope, fProjectId, fOwnerId, fEnabled, loadConfigs]);

  const selectConfig = useCallback((id: string) => {
    setSelectedId(id);
    setScanNote(null);
    void loadRecords(id);
  }, [loadRecords]);

  const handleToggle = useCallback(async (cfg: WecomScanConfigDTO) => {
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
  }, [loadConfigs]);

  const handleScan = useCallback(async (cfg: WecomScanConfigDTO) => {
    setBusyId(cfg.id);
    setActionError(null);
    setScanNote(null);
    try {
      const rec = await triggerWecomScan(cfg.id);
      setScanNote(
        `扫描完成（${scanStatusLabel[rec.scan_status] ?? rec.scan_status}）：发现 ${rec.discovered_count} · 新增 ${rec.new_count} · 重复 ${rec.duplicate_count} · 失败 ${rec.failed_count}`
      );
      setSelectedId(cfg.id);
      await Promise.all([loadConfigs(), loadRecords(cfg.id)]);
    } catch (e) {
      // 403=无权限（需 admin）；503=企微未配置（后端 fail-closed 安全错误）。
      setActionError(describeError(e, "手动扫描失败"));
    } finally {
      setBusyId(null);
    }
  }, [loadConfigs, loadRecords]);

  const stats = useMemo(() => {
    const enabled = configs.filter((c) => c.enabled).length;
    return { enabled, total: configs.length };
  }, [configs]);

  const selectedConfig = selectedId ? configs.find((c) => c.id === selectedId) ?? null : null;

  return (
    <div className="ws-page">
      {/* Header */}
      <div className="kl-header">
        <div className="kl-header-text">
          <h2>企微微盘扫描配置</h2>
          <p>管理 Path A 上游扫描目录：配置企微微盘监控路径，扫描发现的文件将生成待确认资产化任务。本页调用后端 R6 微盘扫描 API，仅展示安全运营元数据。</p>
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
          <div className="ws-note-hint" style={{ color: "var(--color-danger-fg, #b00)" }}>{actionError}</div>
        </section>
      )}
      {scanNote && (
        <section className="ws-section">
          <div className="ws-note-hint" style={{ color: "var(--color-success-fg, #176)" }}>{scanNote}</div>
        </section>
      )}

      {/* Create / edit form */}
      {formOpen && (
        <section className="ws-section">
          <div className="ws-detail-panel">
            <div className="ws-detail-head">
              <span className="ws-detail-title">{editingId ? "编辑扫描配置" : "新增扫描配置"}</span>
              <button className="btn-small" onClick={() => setFormOpen(false)} disabled={saveBusy}>关闭</button>
            </div>
            <div className="ws-form-grid">
              <label className="ws-form-field">
                <span className="ws-form-label">配置名称</span>
                <input className="ws-form-input" value={fName} onChange={(e) => setFName(e.target.value)} placeholder="如：Alpha 项目交付目录" maxLength={200} />
              </label>
              <div className="ws-form-field">
                <span className="ws-form-label">扫描目录</span>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <button className="btn-small btn-small-primary" type="button" onClick={() => setPickerOpen((v) => !v)}>
                    {pickerOpen ? "收起目录选择" : "选择微盘目录"}
                  </button>
                  <span className="ws-form-hint">
                    {fDir
                      ? (fDirLabel ? `已选择：${fDirLabel}` : "已设置服务端目录配置")
                      : "从微盘空间/目录中选择，无需手填内部标识"}
                  </span>
                </div>
                {pickerOpen && (
                  <WecomDirectoryPicker
                    onSelect={(ref, label) => { setFDir(ref); setFDirLabel(label); setPickerOpen(false); }}
                  />
                )}
                <details className="ws-form-advanced" style={{ marginTop: 8 }}>
                  <summary style={{ cursor: "pointer", fontSize: 12, color: "var(--color-text-muted, #888)" }}>
                    高级：手动输入目录标识（API 暂不可用 / 修复旧配置时）
                  </summary>
                  <input className="ws-form-input" style={{ marginTop: 6 }} value={fDir}
                    onChange={(e) => { setFDir(e.target.value); setFDirLabel(""); }}
                    placeholder="spaceid:<id>;fatherid:<id>" />
                  <span className="ws-form-hint">服务端内部标识，格式 <code>spaceid:&lt;id&gt;;fatherid:&lt;id&gt;</code>；fatherid 省略表示根目录。</span>
                </details>
              </div>
              <label className="ws-form-field">
                <span className="ws-form-label">目标知识库</span>
                <select className="ws-form-input" value={fScope} onChange={(e) => { setFScope(e.target.value); setFOwnerId(""); if (e.target.value !== "project") setFProjectId(""); }}>
                  {scopeOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </label>
              {fScope === "project" && (
                <label className="ws-form-field">
                  <span className="ws-form-label">目标项目</span>
                  {projectOptions.length > 0 ? (
                    <select className="ws-form-input" value={fProjectId} onChange={(e) => { setFProjectId(e.target.value); setFOwnerId(""); }}>
                      <option value="">请选择项目…</option>
                      {projectOptions.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  ) : (
                    <span className="ws-form-hint">暂无可选的 active 项目，请先创建项目后再配置项目级扫描。</span>
                  )}
                </label>
              )}
              <label className="ws-form-field">
                <span className="ws-form-label">待确认任务业务归属人</span>
                {(fScope !== "project" || fProjectId) && ownerCandidates.length > 0 ? (
                  <select className="ws-form-input" value={fOwnerId} onChange={(e) => setFOwnerId(e.target.value)}>
                    <option value="">请选择业务归属人…</option>
                    {ownerCandidates.map((o) => (
                      <option key={o.user_id} value={o.user_id}>
                        {o.name}{o.role_label ? `（${o.role_label}）` : ""}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="ws-form-hint">
                    {fScope === "project" && !fProjectId
                      ? "请先选择目标项目，再选择该项目的业务归属人。"
                      : fScope === "company"
                        ? "公司级配置需选择 Boss / 咨询总监作为业务归属人，当前无可选治理角色。"
                        : "暂无可选业务用户作为归属人。"}
                  </span>
                )}
                <span className="ws-form-hint">扫描发现的文件会生成待确认入库任务，由该业务归属人进入资产化确认工作台处理（配置操作人仍是当前 admin）。</span>
              </label>
              <label className="ws-form-field ws-form-checkbox">
                <input type="checkbox" checked={fEnabled} onChange={(e) => setFEnabled(e.target.checked)} />
                <span>创建后启用</span>
              </label>
            </div>
            {saveError && <div className="ws-note-hint" style={{ color: "var(--color-danger-fg, #b00)" }}>{saveError}</div>}
            <div className="ws-form-actions">
              <button className="btn-small-primary" onClick={() => void handleSave()} disabled={saveBusy}>
                {saveBusy ? "保存中…" : (editingId ? "保存修改" : "创建配置")}
              </button>
              <button className="btn-small" onClick={() => setFormOpen(false)} disabled={saveBusy}>取消</button>
            </div>
          </div>
        </section>
      )}

      {/* Config table */}
      <section className="ws-section">
        <div className="ig-toolbar">
          <h3 style={{ margin: 0 }}>扫描目录配置</h3>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn-small-primary" onClick={openCreate}>新增扫描配置</button>
            <button className="btn-small" onClick={() => void loadConfigs()} disabled={loadingConfigs}>
              {loadingConfigs ? "加载中…" : "刷新"}
            </button>
          </div>
        </div>
        {configError ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">加载失败</div>
            <p className="ig-empty-desc">{configError}</p>
            <button className="btn-small" onClick={() => void loadConfigs()}>重试</button>
          </div>
        ) : loadingConfigs ? (
          <div className="ig-empty-state"><div className="ig-empty-title">加载中…</div></div>
        ) : configs.length === 0 ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">尚未配置微盘扫描目录</div>
            <p className="ig-empty-desc">还没有任何企微微盘扫描目录。点击下方按钮创建第一个扫描配置（需要 admin 权限）。</p>
            <button className="btn-small-primary" onClick={openCreate}>新增扫描配置</button>
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
                    <td className="ws-cell-time">{fmtTime(cfg.last_scan_at)}</td>
                    <td className="ws-cell-actions">
                      <button className="btn-small" onClick={() => selectConfig(cfg.id)}>详情/记录</button>
                      <button className="btn-small" onClick={() => openEdit(cfg)}>编辑</button>
                      <button className="btn-small" onClick={() => void handleToggle(cfg)} disabled={busyId === cfg.id}>
                        {cfg.enabled ? "停用" : "启用"}
                      </button>
                      <button
                        className="btn-small-primary"
                        onClick={() => void handleScan(cfg)}
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

      {/* Detail + records */}
      {selectedConfig && (
        <section className="ws-section">
          <div className="ws-detail-panel">
            <div className="ws-detail-head">
              <span className="ws-detail-title">配置详情与扫描记录</span>
              <button className="btn-small" onClick={() => { setSelectedId(null); setRecords([]); }}>关闭</button>
            </div>
            <div className="ws-detail-grid">
              <div className="ws-detail-item">
                <span className="ws-detail-label">目录归属</span>
                <span className="ws-detail-value">
                  <span className={`ws-scope-tag ${selectedConfig.scope_type === "company" ? "ws-scope-company" : "ws-scope-project"}`}>
                    {scopeLabel[selectedConfig.scope_type] ?? selectedConfig.scope_type}
                  </span>
                </span>
              </div>
              <div className="ws-detail-item">
                <span className="ws-detail-label">服务端目录配置标识</span>
                <span className="ws-detail-value ws-detail-path"><code>{selectedConfig.directory_path}</code></span>
              </div>
              <div className="ws-detail-item ws-detail-full">
                <span className="ws-detail-label">扫描范围说明</span>
                <span className="ws-detail-value">
                  扫描该目录下新增或更新的文件，生成 <code>ingest_task</code> 待确认记录。
                  Path A 文件不会直接入库，需经业务侧确认后方可进入知识库。
                </span>
              </div>
              <div className="ws-detail-item ws-detail-full">
                <span className="ws-detail-label">下游流程</span>
                <span className="ws-detail-value">
                  <div className="ws-detail-links">
                    <Link to="/upload" className="ws-detail-link">资产化确认工作台 →</Link>
                    <Link to="/admin/ingest" className="ws-detail-link">入库管理 →</Link>
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
              <div className="ig-empty-state"><div className="ig-empty-title">加载中…</div></div>
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
                          <span className={`ws-result-pill ${scanStatusCls[r.scan_status] ?? "ws-result-empty"}`}>
                            {scanStatusLabel[r.scan_status] ?? r.scan_status}
                          </span>
                        </td>
                        <td className="ws-cell-num">{r.discovered_count}</td>
                        <td className="ws-cell-num">{r.new_count}</td>
                        <td className="ws-cell-num">{r.duplicate_count}</td>
                        <td className="ws-cell-num">{r.failed_count}</td>
                        <td className="ws-cell-suggestion">{r.error_message || r.error_type || "—"}</td>
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
        扫盘只发现文件并生成待确认任务，不直接入库；目标库与分区、权限与企微配置边界见 <Link to="/help#ingest" className="page-help-link">使用说明 →</Link>
      </p>
    </div>
  );
}

// 微盘目录选择器。先列空间，再浏览子目录并钻取；选中后回填可保存的 directory_ref。
// 只展示目录名（友好），不要求用户理解 spaceid/fatherid；不展示文件、不下载。
function WecomDirectoryPicker({ onSelect }: { onSelect: (ref: string, label: string) => void }) {
  const [spaces, setSpaces] = useState<WecomDriveSpaceDTO[]>([]);
  const [space, setSpace] = useState<WecomDriveSpaceDTO | null>(null);
  // 面包屑：第一项为空间根（ref=null），后续为已钻取目录。
  const [stack, setStack] = useState<{ ref: string | null; name: string }[]>([]);
  const [dirs, setDirs] = useState<WecomDriveDirectoryDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const describe = (e: unknown, fallback: string) =>
    e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : fallback;

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    fetchWecomDriveSpaces()
      .then((d) => { if (!cancelled) setSpaces(d.items); })
      .catch((e) => { if (!cancelled) setError(describe(e, "加载微盘空间失败（未配置企微或无权限时不可用，可用高级手动输入）")); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const loadDirs = useCallback(async (spaceRef: string, parentRef: string | undefined) => {
    setLoading(true); setError(null);
    try { setDirs((await fetchWecomDriveDirectories(spaceRef, parentRef)).items); }
    catch (e) { setError(describe(e, "加载目录失败")); setDirs([]); }
    finally { setLoading(false); }
  }, []);

  const openSpace = useCallback(async (sp: WecomDriveSpaceDTO) => {
    setSpace(sp); setStack([{ ref: null, name: sp.name }]);
    await loadDirs(sp.space_ref, undefined);
  }, [loadDirs]);

  const drill = useCallback(async (d: WecomDriveDirectoryDTO) => {
    if (!space) return;
    setStack((s) => [...s, { ref: d.directory_ref, name: d.name }]);
    await loadDirs(space.space_ref, d.directory_ref);
  }, [space, loadDirs]);

  const goTo = useCallback(async (idx: number) => {
    if (!space) return;
    const ns = stack.slice(0, idx + 1); setStack(ns);
    await loadDirs(space.space_ref, ns[ns.length - 1].ref ?? undefined);
  }, [space, stack, loadDirs]);

  const useHere = useCallback(() => {
    if (!space) return;
    const cur = stack[stack.length - 1];
    const ref = cur?.ref ?? `spaceid:${space.space_ref};fatherid:`;  // 空间根 = fatherid 空
    const label = stack.map((s) => s.name).join(" / ");
    onSelect(ref, label);
  }, [space, stack, onSelect]);

  return (
    <div className="ws-detail-panel" style={{ marginTop: 8 }}>
      {error && <div className="ws-note-hint" style={{ color: "var(--color-danger-fg, #b00)" }}>{error}</div>}
      {!space ? (
        <div>
          <div className="ws-form-label">选择微盘空间</div>
          {loading ? <div className="ig-empty-state"><div className="ig-empty-title">加载中…</div></div>
            : spaces.length === 0 ? <p className="ws-form-hint">无可用空间（或企微未配置）。可用下方「高级」手动输入。</p>
            : (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
                {spaces.map((sp) => (
                  <button key={sp.space_ref} className="btn-small" type="button" onClick={() => void openSpace(sp)}>{sp.name}</button>
                ))}
              </div>
            )}
        </div>
      ) : (
        <div>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", fontSize: 13 }}>
            {stack.map((s, i) => (
              <span key={i}>
                {i > 0 && <span style={{ color: "var(--color-text-muted, #aaa)" }}> / </span>}
                <button className="btn-link" type="button" style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-link, #36c)", padding: 0 }} onClick={() => void goTo(i)}>{s.name}</button>
              </span>
            ))}
            <button className="btn-small" type="button" style={{ marginLeft: "auto" }} onClick={() => { setSpace(null); setDirs([]); setStack([]); }}>切换空间</button>
          </div>
          {loading ? <div className="ig-empty-state"><div className="ig-empty-title">加载中…</div></div>
            : dirs.length === 0 ? <p className="ws-form-hint" style={{ marginTop: 8 }}>该目录下无子目录。可直接「使用当前目录」。</p>
            : (
              <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
                {dirs.map((d) => (
                  <button key={d.directory_ref} className="btn-small" type="button" style={{ textAlign: "left" }} onClick={() => void drill(d)}>📁 {d.name}{d.has_children ? " ›" : ""}</button>
                ))}
              </div>
            )}
          <div className="ws-form-actions" style={{ marginTop: 10 }}>
            <button className="btn-small-primary" type="button" onClick={useHere}>使用当前目录</button>
          </div>
        </div>
      )}
    </div>
  );
}

