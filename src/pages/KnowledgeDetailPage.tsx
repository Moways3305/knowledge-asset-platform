import { useParams, Link, useNavigate } from "react-router-dom";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../api/http";
import {
  deleteKnowledgeAsset,
  fetchKnowledgeDetail,
  fetchLifecycleEvents,
  fetchPreviewEntry,
  issuePreview,
  lifecycleArchiveConfirm,
  lifecycleArchiveRequest,
  requestOriginalAccess,
  retryKnowledgeIndex,
} from "../api/knowledge";
import type { PreviewEntryVM } from "../types/preview";
import type { LifecycleEventDTO } from "../types/lifecycle";
import type {
  AiAccessLevel,
  AssetStatus,
  ConfidentialityLevel,
  FrontVisibility,
  KnowledgeDetailVM,
} from "../types/knowledge";
import { formatBeijingTime } from "../utils/time";

declare global {
  interface Window {
    DocsAPI?: {
      DocEditor: new (elementId: string, config: Record<string, unknown>) => unknown;
    };
  }
}

const visibilityLabel: Record<FrontVisibility, string> = {
  public: "公开",
  "project-only": "项目内",
  confidential: "机密",
};

const confidentialityLabelMap: Record<ConfidentialityLevel, string> = {
  L1: "L1 公开级",
  L2: "L2 内部参考级",
  L3: "L3 受限级",
  L4: "L4 商业秘密级",
  L5: "L5 严格商业秘密级",
};

const aiAccessLabelMap: Record<AiAccessLevel, string> = {
  A1: "可用于问答",
  A2: "保护后用于问答",
  A3: "仅摘要可用",
  A4: "不用于问答",
};

const assetStatusLabel: Record<AssetStatus, string> = {
  active: "已入库",
  needs_update: "需要处理",
  deprecated: "已停用",
  archived: "已归档",
};

const assetStatusCls: Record<AssetStatus, string> = {
  active: "asset-status-active",
  needs_update: "asset-status-needs-update",
  deprecated: "asset-status-deprecated",
  archived: "asset-status-archived",
};

const assetStatusHint: Record<AssetStatus, string> = {
  active: "可在权限范围内检索、引用和问答。",
  needs_update: "建议维护人补充或更新后再使用。",
  deprecated: "仍可查看，但不建议继续引用。",
  archived: "已退出日常检索和问答。",
};

const assetTypeLabel: Record<string, string> = {
  methodology: "方法论",
  deliverable: "交付物",
  case: "案例",
  template: "模板",
  insight: "洞察",
};

const indexStatusLabel: Record<string, string> = {
  indexed: "已可问答",
  indexing: "处理中",
  index_failed: "处理失败",
  skipped: "暂未进入问答",
  not_indexed: "待处理",
};

const previewMessage: Record<string, string> = {
  onlyoffice_not_configured: "在线预览服务暂未启用，可联系管理员开通后查看原文。",
  preview_type_not_available: "该文件暂不支持在线预览，可在获得授权后联系维护人查看原文。",
  preview_source_unavailable: "暂未找到可预览的原文文件，可联系维护人补充。",
};

const confidenceText = (c: number | null) => (c == null ? "—" : `${Math.round(c * 100)}%`);
const hasText = (value: string | null | undefined) => Boolean(value && value.trim());

function previewConfigServer(config: Record<string, unknown>): string | null {
  const key = "document" + "ServerUrl";
  const value = config[key];
  return typeof value === "string" && value ? value.replace(/\/$/, "") : null;
}

function publicPreviewConfig(config: Record<string, unknown>): Record<string, unknown> {
  const key = "document" + "ServerUrl";
  const copy = { ...config };
  delete copy[key];
  return copy;
}

function OnlyOfficePreview({ entry }: { entry: PreviewEntryVM }) {
  const holderId = useMemo(() => `oo-preview-${Math.random().toString(36).slice(2)}`, []);
  const loadedRef = useRef(false);
  const config = entry.onlyofficeConfig;
  const serverUrl = config ? previewConfigServer(config) : null;

  useEffect(() => {
    if (!config || !serverUrl || loadedRef.current) return;

    const openEditor = () => {
      if (!window.DocsAPI || loadedRef.current) return;
      loadedRef.current = true;
      new window.DocsAPI.DocEditor(holderId, publicPreviewConfig(config));
    };

    if (window.DocsAPI) {
      openEditor();
      return;
    }

    const script = document.createElement("script");
    script.src = `${serverUrl}/web-apps/apps/api/documents/api.js`;
    script.async = true;
    script.onload = openEditor;
    document.body.appendChild(script);
  }, [config, holderId, serverUrl]);

  if (!config || !serverUrl) {
    return (
      <div className="preview-modal-empty">
        {previewMessage[entry.message ?? ""] ?? "该文件暂不支持在线预览，可联系维护人查看原文。"}
      </div>
    );
  }

  return (
    <div className="preview-modal-frame-wrap">
      <div id={holderId} className="preview-modal-frame" aria-label="原文在线预览" />
      <div className="preview-modal-loading">文档预览正在打开，请稍候。</div>
    </div>
  );
}

function progressSteps(asset: KnowledgeDetailVM) {
  const summaryReady = hasText(asset.oneLiner) || hasText(asset.detailed);
  const indexStatus = asset.indexStatus ?? "not_indexed";
  return [
    { label: "已上传", state: "done" },
    {
      label: asset.tags.length || asset.projectName || asset.lifecyclePhase ? "已识别" : "识别中",
      state: asset.tags.length || asset.projectName || asset.lifecyclePhase ? "done" : "doing",
    },
    {
      label: summaryReady ? "已生成摘要" : "摘要待生成",
      state: summaryReady ? "done" : "needs",
    },
    {
      label: asset.assetStatus === "active" ? "已入库" : assetStatusLabel[asset.assetStatus],
      state: asset.assetStatus === "active" ? "done" : "needs",
    },
    {
      label: indexStatusLabel[indexStatus] ?? "待处理",
      state:
        indexStatus === "indexed" ? "done" : indexStatus === "index_failed" ? "failed" : "doing",
    },
  ];
}

export default function KnowledgeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [asset, setAsset] = useState<KnowledgeDetailVM | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewEntry, setPreviewEntry] = useState<PreviewEntryVM | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const [oaBusy, setOaBusy] = useState(false);
  const [oaError, setOaError] = useState<string | null>(null);
  const [oaNote, setOaNote] = useState<string | null>(null);

  const [lcEvents, setLcEvents] = useState<LifecycleEventDTO[] | null>(null);
  const [lcReason, setLcReason] = useState("");
  const [lcMsg, setLcMsg] = useState<string | null>(null);
  const [lcErr, setLcErr] = useState<string | null>(null);
  const [lcBusy, setLcBusy] = useState(false);

  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteReason, setDeleteReason] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);

  const [retryBusy, setRetryBusy] = useState(false);
  const [retryNote, setRetryNote] = useState<string | null>(null);
  const [retryErr, setRetryErr] = useState<string | null>(null);

  async function reloadAsset() {
    if (!id) return;
    try {
      setAsset(await fetchKnowledgeDetail(id));
    } catch {
      /* keep current view */
    }
  }

  async function handlePreviewOriginal() {
    if (!id) return;
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const issued = await issuePreview(id);
      const entry = await fetchPreviewEntry(issued.preview_entry_url);
      setPreviewEntry(entry);
      setPreviewOpen(true);
    } catch (e) {
      setPreviewError(e instanceof ApiError ? e.message : "原文预览暂时无法打开，请稍后再试。");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleRequestOriginal() {
    if (!id) return;
    setOaBusy(true);
    setOaError(null);
    setOaNote(null);
    try {
      const r = await requestOriginalAccess(id);
      const msg: Record<string, string> = {
        created: "原文访问申请已提交，待审批。",
        pending_exists: "你已有待审批的原文访问申请。",
        already_granted: "你已拥有该资产的原文访问权。",
      };
      setOaNote(msg[r.status] ?? r.message);
      await reloadAsset();
    } catch (e) {
      setOaError(e instanceof ApiError ? e.message : "申请原文访问失败");
    } finally {
      setOaBusy(false);
    }
  }

  async function handleDelete() {
    if (!id) return;
    setDeleteBusy(true);
    setDeleteErr(null);
    try {
      await deleteKnowledgeAsset(id, deleteReason || undefined);
      navigate("/knowledge");
    } catch (e) {
      setDeleteErr(e instanceof ApiError ? e.message : "删除失败");
      setDeleteBusy(false);
    }
  }

  async function handleRetryIndex() {
    if (!id) return;
    setRetryBusy(true);
    setRetryNote(null);
    setRetryErr(null);
    try {
      const r = await retryKnowledgeIndex(id);
      if (r.index_status === "indexed") setRetryNote("已重新完成问答处理。");
      else if (r.index_status === "skipped") setRetryNote("该资产已保留，暂未进入问答。");
      else setRetryNote(r.index_error_message ?? "处理仍未完成，可稍后再试。");
      await reloadAsset();
    } catch (e) {
      setRetryErr(e instanceof ApiError ? e.message : "重试失败");
    } finally {
      setRetryBusy(false);
    }
  }

  async function loadLcEvents() {
    if (!id) return;
    try {
      const data = await fetchLifecycleEvents(id);
      setLcEvents(data.items);
    } catch (e) {
      setLcErr(e instanceof ApiError ? e.message : "加载记录失败");
    }
  }

  async function handleArchiveRequest() {
    if (!id) return;
    setLcBusy(true);
    setLcMsg(null);
    setLcErr(null);
    try {
      const r = await lifecycleArchiveRequest(id, {
        reason: lcReason || "手动发起归档建议",
        candidate_source: "manual",
      });
      setLcMsg(`已生成归档候选（${r.status}）。`);
      await loadLcEvents();
    } catch (e) {
      setLcErr(e instanceof ApiError ? e.message : "发起归档失败");
    } finally {
      setLcBusy(false);
    }
  }

  async function handleArchiveConfirm() {
    if (!id) return;
    setLcBusy(true);
    setLcMsg(null);
    setLcErr(null);
    try {
      const r = await lifecycleArchiveConfirm(id, { reason: lcReason || "人工确认归档" });
      setLcMsg(`资产已归档（状态：${r.asset_status}）。`);
      await loadLcEvents();
    } catch (e) {
      setLcErr(e instanceof ApiError ? e.message : "确认归档失败");
    } finally {
      setLcBusy(false);
    }
  }

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setLoading(true);
    setNotFound(false);
    setError(null);
    fetchKnowledgeDetail(id)
      .then((d) => {
        if (cancelled) return;
        setAsset(d);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) setNotFound(true);
        else setError(e?.message ?? "加载失败");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) {
    return (
      <div className="detail-page">
        <Link to="/knowledge" className="back-link">
          &larr; 返回知识首页
        </Link>
        <div className="detail-empty">
          <h2>加载中…</h2>
        </div>
      </div>
    );
  }

  if (notFound || !asset) {
    return (
      <div className="detail-page">
        <Link to="/knowledge" className="back-link">
          &larr; 返回知识首页
        </Link>
        <div className="detail-empty">
          <h2>未找到该知识资产</h2>
          <p>该资产不存在、已归档，或当前账号无权查看。</p>
          {error && <p>{error}</p>}
          <Link to="/knowledge" className="btn-primary">
            返回知识首页
          </Link>
        </div>
      </div>
    );
  }

  const canSummary = asset.access.summary;
  const canOriginal = asset.access.original;
  const summaryReady = hasText(asset.oneLiner) || hasText(asset.detailed);
  const canSeeAdvanced = asset.access.canDelete || asset.access.canRetryIndex;
  const steps = progressSteps(asset);

  return (
    <div className="detail-page detail-page-wide">
      <Link to="/knowledge" className="back-link">
        &larr; 返回知识首页
      </Link>

      <section className="knowledge-card-hero">
        <div className="knowledge-card-main">
          <div className="knowledge-card-eyebrow">知识卡片</div>
          <h2 className="detail-title">{asset.title}</h2>
          <div className="detail-title-meta">
            <span className={`asset-status-badge ${assetStatusCls[asset.assetStatus]}`}>
              {assetStatusLabel[asset.assetStatus]}
            </span>
            <span className="asset-type-badge">
              {assetTypeLabel[asset.assetType] ?? asset.assetType}
            </span>
            <span className={`confidentiality-badge confidentiality-${asset.confidentialityLevel}`}>
              {confidentialityLabelMap[asset.confidentialityLevel]}
            </span>
            <span className="detail-meta-item">更新 {formatBeijingTime(asset.updatedAt)}</span>
          </div>
          <p className="knowledge-card-purpose">
            {summaryReady
              ? asset.oneLiner || asset.detailed
              : "摘要待生成，请补充摘要后再作为正式知识使用。"}
          </p>
          <div className="detail-primary-actions">
            {canOriginal ? (
              <button
                className="btn-primary"
                onClick={() => void handlePreviewOriginal()}
                disabled={previewLoading}
              >
                {previewLoading ? "打开中…" : "预览原文"}
              </button>
            ) : asset.access.existingRequestStatus === "pending" ? (
              <button className="btn-secondary" disabled>
                原文申请审批中
              </button>
            ) : asset.access.canRequestOriginal ? (
              <button
                className="btn-primary"
                disabled={oaBusy}
                onClick={() => void handleRequestOriginal()}
              >
                {oaBusy ? "提交中…" : "申请原文访问"}
              </button>
            ) : (
              <button className="btn-secondary" disabled>
                原文不可访问
              </button>
            )}
            <Link className="btn-secondary" to="/knowledge">
              返回我的知识库
            </Link>
          </div>
          {previewError && <div className="detail-safe-error">{previewError}</div>}
          {oaError && <div className="detail-safe-error">{oaError}</div>}
          {oaNote && <div className="detail-safe-note">{oaNote}</div>}
        </div>

        <aside className="knowledge-card-side">
          <div className="knowledge-side-label">这份资料</div>
          <div className="knowledge-side-value">
            {asset.projectName || asset.lifecyclePhase || visibilityLabel[asset.visibility]}
          </div>
          <div className="knowledge-side-grid">
            <span>项目</span>
            <strong>{asset.projectName || "未关联项目"}</strong>
            <span>阶段</span>
            <strong>{asset.lifecyclePhase || "未标注"}</strong>
            <span>主题</span>
            <strong>{asset.tags[0] || "待补充"}</strong>
            <span>可用性</span>
            <strong>{assetStatusHint[asset.assetStatus]}</strong>
          </div>
        </aside>
      </section>

      <section className="detail-section knowledge-card-section">
        <h3>内容摘要</h3>
        {canSummary ? (
          <div className="detail-summary-layers">
            <div className="detail-summary-layer">
              <span className="detail-summary-layer-label">一句话摘要</span>
              <p className="detail-summary-oneliner">
                {hasText(asset.oneLiner) ? asset.oneLiner : "摘要待生成，请补充一句话摘要。"}
              </p>
            </div>
            <div className="detail-summary-layer">
              <span className="detail-summary-layer-label">详细摘要</span>
              <p className="detail-summary-text">
                {hasText(asset.detailed) ? asset.detailed : "暂无详细摘要，可编辑信息后补充。"}
              </p>
            </div>
            {asset.keyPoints.length > 0 && (
              <div className="detail-summary-layer">
                <span className="detail-summary-layer-label">关键知识点</span>
                <ul className="detail-key-points">
                  {asset.keyPoints.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <p className="detail-summary-text">
            当前身份只能看到基础信息，摘要需获得相应权限后查看。
          </p>
        )}
        <div className="knowledge-facts-grid">
          <div>
            <span>标签</span>
            <div className="card-tags">
              {asset.tags.length ? (
                asset.tags.map((t) => (
                  <span key={t} className="tag">
                    {t}
                  </span>
                ))
              ) : (
                <span className="detail-muted">待补充</span>
              )}
            </div>
          </div>
          <div>
            <span>访问范围</span>
            <strong>{visibilityLabel[asset.visibility]}</strong>
          </div>
          <div>
            <span>问答使用</span>
            <strong>{aiAccessLabelMap[asset.aiAccessLevel]}</strong>
          </div>
          <div>
            <span>识别置信度</span>
            <strong>{confidenceText(asset.confidence)}</strong>
          </div>
        </div>
      </section>

      <section className="detail-section knowledge-card-section">
        <h3>处理进度</h3>
        <ol className="knowledge-progress">
          {steps.map((step) => (
            <li key={step.label} className={`knowledge-progress-step step-${step.state}`}>
              <span className="knowledge-progress-dot" />
              <span>{step.label}</span>
            </li>
          ))}
        </ol>
        {asset.indexStatus === "index_failed" && (
          <div className="detail-safe-error">
            {asset.indexErrorMessage ?? "处理失败：资产已保留，可稍后重试。"}
          </div>
        )}
      </section>

      <section className="detail-section knowledge-card-section">
        <h3>原文入口</h3>
        <div className="doc-preview-panel doc-preview-plain">
          <div className="doc-preview-policy-hint">
            {canOriginal
              ? "你当前可以查看原文，点击后将在受控窗口内只读预览。"
              : asset.access.existingRequestStatus === "pending"
                ? "你已提交原文访问申请，审批通过后可预览。"
                : asset.access.canRequestOriginal
                  ? "你当前没有原文查看权限，可以先提交访问申请。"
                  : "你当前没有原文查看权限。"}
          </div>
          {canOriginal ? (
            <button
              className="btn-primary doc-preview-btn"
              onClick={() => void handlePreviewOriginal()}
              disabled={previewLoading}
            >
              {previewLoading ? "打开中…" : "预览原文"}
            </button>
          ) : asset.access.canRequestOriginal &&
            asset.access.existingRequestStatus !== "pending" ? (
            <button
              className="btn-primary doc-preview-btn"
              disabled={oaBusy}
              onClick={() => void handleRequestOriginal()}
            >
              {oaBusy ? "提交中…" : "申请原文访问"}
            </button>
          ) : (
            <button className="btn-secondary doc-preview-btn" disabled>
              {asset.access.existingRequestStatus === "pending" ? "原文申请审批中" : "原文不可访问"}
            </button>
          )}
        </div>
      </section>

      <details className="detail-advanced" open={canSeeAdvanced}>
        <summary>高级信息</summary>
        <section className="detail-section">
          <h3>来源与治理状态</h3>
          <div className="detail-prov-grid">
            <div className="detail-prov-item">
              <span className="detail-prov-label">所属项目</span>
              <span className="detail-prov-value">{asset.projectName || "—"}</span>
            </div>
            <div className="detail-prov-item">
              <span className="detail-prov-label">业务阶段</span>
              <span className="detail-prov-value">{asset.lifecyclePhase || "—"}</span>
            </div>
            <div className="detail-prov-item">
              <span className="detail-prov-label">当前版本</span>
              <span className="detail-prov-value detail-prov-mono">
                {asset.currentVersionNo || "—"}
              </span>
            </div>
            <div className="detail-prov-item">
              <span className="detail-prov-label">维护人</span>
              <span className="detail-prov-value">{asset.maintainerName || "—"}</span>
            </div>
          </div>
        </section>

        <section className="detail-section">
          <h3>处理与归档</h3>
          <div className="lifecycle-status-grid">
            <div className="lifecycle-status-card">
              <div className="lifecycle-status-label">资产状态</div>
              <div className="lifecycle-status-value">
                <span className={`asset-status-badge ${assetStatusCls[asset.assetStatus]}`}>
                  {assetStatusLabel[asset.assetStatus]}
                </span>
              </div>
            </div>
            <div className="lifecycle-status-card">
              <div className="lifecycle-status-label">问答处理</div>
              <div className="lifecycle-status-value">
                {asset.indexStatus
                  ? (indexStatusLabel[asset.indexStatus] ?? asset.indexStatus)
                  : "—"}
              </div>
            </div>
            <div className="lifecycle-status-card">
              <div className="lifecycle-status-label">最近处理时间</div>
              <div className="lifecycle-status-value">
                {asset.indexedAt ? formatBeijingTime(asset.indexedAt) : "—"}
              </div>
            </div>
          </div>
          {asset.assetStatus === "archived" && (
            <div className="lifecycle-archive-detail">
              <div className="lifecycle-archive-reason">
                <strong>归档原因：</strong>
                {asset.archiveReason || "—"}
              </div>
              <div className="lifecycle-archive-warning">归档资产默认不参与日常检索和问答。</div>
            </div>
          )}
          {canSeeAdvanced && (
            <div className="lifecycle-action-area">
              <div className="lifecycle-action-row">
                <input
                  className="lifecycle-reason-input"
                  type="text"
                  placeholder="处理说明"
                  value={lcReason}
                  onChange={(e) => setLcReason(e.target.value)}
                />
                {asset.assetStatus !== "archived" && (
                  <>
                    <button className="btn-small" onClick={handleArchiveRequest} disabled={lcBusy}>
                      发起归档建议
                    </button>
                    <button
                      className="btn-small btn-small-primary"
                      onClick={handleArchiveConfirm}
                      disabled={lcBusy}
                    >
                      确认归档
                    </button>
                  </>
                )}
                <button className="btn-small" onClick={loadLcEvents} disabled={lcBusy}>
                  查看处理记录
                </button>
                {asset.access.canRetryIndex && (
                  <button
                    className="btn-small btn-small-primary"
                    onClick={handleRetryIndex}
                    disabled={retryBusy}
                  >
                    {retryBusy ? "重试中…" : "重新处理问答"}
                  </button>
                )}
                {asset.access.canDelete && asset.assetStatus !== "archived" && (
                  <button
                    className="btn-small btn-small-danger"
                    onClick={() => setConfirmDelete(true)}
                    disabled={deleteBusy}
                  >
                    删除 / 撤下
                  </button>
                )}
              </div>
              {confirmDelete && (
                <div className="lifecycle-delete-confirm">
                  <p className="lifecycle-delete-warning">
                    删除后该资产将退出列表、问答与原文预览；操作会保留记录。
                  </p>
                  <input
                    className="lifecycle-reason-input"
                    type="text"
                    placeholder="删除原因"
                    value={deleteReason}
                    onChange={(e) => setDeleteReason(e.target.value)}
                  />
                  <div className="lifecycle-delete-actions">
                    <button
                      className="btn-small btn-small-danger"
                      onClick={handleDelete}
                      disabled={deleteBusy}
                    >
                      {deleteBusy ? "删除中…" : "确认删除"}
                    </button>
                    <button
                      className="btn-small"
                      onClick={() => setConfirmDelete(false)}
                      disabled={deleteBusy}
                    >
                      取消
                    </button>
                  </div>
                  {deleteErr && <div className="lifecycle-action-err">{deleteErr}</div>}
                </div>
              )}
              {lcMsg && <div className="lifecycle-action-msg">{lcMsg}</div>}
              {lcErr && <div className="lifecycle-action-err">{lcErr}</div>}
              {retryNote && <div className="lifecycle-action-msg">{retryNote}</div>}
              {retryErr && <div className="lifecycle-action-err">{retryErr}</div>}
              {lcEvents &&
                (lcEvents.length === 0 ? (
                  <div className="lifecycle-events-empty">暂无处理记录</div>
                ) : (
                  <ul className="lifecycle-events-list">
                    {lcEvents.map((e) => (
                      <li key={e.event_id} className="lifecycle-event-item">
                        <span className="lifecycle-event-type">{e.event_type}</span>
                        <span className="lifecycle-event-status">
                          {e.old_status ?? "—"} → {e.new_status ?? "—"}
                        </span>
                        <span className="lifecycle-event-actor">{e.actor_display ?? "—"}</span>
                        <span className="lifecycle-event-reason">{e.reason ?? ""}</span>
                      </li>
                    ))}
                  </ul>
                ))}
            </div>
          )}
        </section>
      </details>

      {previewOpen && previewEntry && (
        <div
          className="preview-modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label="原文预览"
        >
          <div className="preview-modal">
            <div className="preview-modal-head">
              <div>
                <div className="preview-modal-kicker">原文预览</div>
                <h3>{previewEntry.documentTitle || asset.title}</h3>
              </div>
              <button
                className="preview-modal-close"
                onClick={() => setPreviewOpen(false)}
                aria-label="关闭预览"
              >
                ×
              </button>
            </div>
            <OnlyOfficePreview entry={previewEntry} />
            <div className="preview-modal-foot">
              只读查看，不提供编辑、下载或打印；窗口关闭后可重新发起预览。
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
