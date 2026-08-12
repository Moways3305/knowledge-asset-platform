import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Archive,
  ArrowLeft,
  ChevronRight,
  Eye,
  FileText,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { ApiError } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import AccessExplanationDrawer, { accessLabel } from "../components/AccessExplanationDrawer";
import TaskModal from "../components/TaskModal";
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
import type { LifecycleEventDTO } from "../types/lifecycle";
import type {
  AiAccessLevel,
  AssetStatus,
  ConfidentialityLevel,
  FrontVisibility,
  KnowledgeDetailVM,
} from "../types/knowledge";
import type { PreviewEntryVM } from "../types/preview";
import { formatBeijingTime } from "../utils/time";
import { OnlyOfficePreview } from "./knowledge/OnlyOfficePreview";
import "./KnowledgeDetailPage.css";

export { OnlyOfficePreview } from "./knowledge/OnlyOfficePreview";

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

const assetTypeLabel: Record<string, string> = {
  methodology: "方法论",
  deliverable: "交付物",
  case: "案例",
  template: "模板",
  insight: "洞察",
};

const indexStatusLabel: Record<string, string> = {
  indexed: "可检索",
  indexing: "WeKnora 处理中",
  index_failed: "索引失败，可重试",
  skipped: "已确认，未启用索引",
  not_indexed: "已确认，等待索引",
};

const scopeLabel: Record<string, string> = {
  personal: "个人范围",
  project: "项目范围",
  company: "公司范围",
};

const lifecycleEventLabel: Record<string, string> = {
  archive_warning: "归档预警",
  archive_candidate: "归档候选",
  archived: "资产已归档",
  reenable_requested: "申请重新启用",
  reenabled: "资产已重新启用",
  status_changed: "资产状态已变更",
};

const hasText = (value: string | null | undefined) => Boolean(value && value.trim());

function safeActionError(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

export default function KnowledgeDetailPage() {
  const { capabilities } = useAuth();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const requestRef = useRef(0);
  const [asset, setAsset] = useState<KnowledgeDetailVM | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);

  const [previewEntry, setPreviewEntry] = useState<PreviewEntryVM | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const [oaBusy, setOaBusy] = useState(false);
  const [oaError, setOaError] = useState<string | null>(null);
  const [oaNote, setOaNote] = useState<string | null>(null);
  const [requestOpen, setRequestOpen] = useState(false);
  const [requestReason, setRequestReason] = useState("");
  const [explainOpen, setExplainOpen] = useState(false);

  const [lcEvents, setLcEvents] = useState<LifecycleEventDTO[] | null>(null);
  const [lcLoading, setLcLoading] = useState(false);
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
  const backPath =
    asset?.projectId && !asset.access.crossProjectSummary
      ? `/project/${asset.projectId}/knowledge`
      : "/knowledge";
  const backLabel =
    asset?.projectId && !asset.access.crossProjectSummary ? "返回项目知识库" : "返回知识资产库";

  async function reloadAsset() {
    if (!id) return;
    try {
      setAsset(await fetchKnowledgeDetail(id));
    } catch {
      // Keep the confirmed detail visible if an action refresh fails.
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
    } catch (error) {
      setPreviewError(safeActionError(error, "原文预览暂时无法打开，请稍后再试。"));
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
      const result = await requestOriginalAccess(id, requestReason.trim() || undefined);
      const message: Record<string, string> = {
        created: "原文访问申请已提交，待审批。",
        pending_exists: "原文访问申请正在审批中。",
        already_granted: "你已拥有该资产的原文访问权。",
      };
      setOaNote(message[result.status] ?? result.message);
      await reloadAsset();
      setRequestOpen(false);
      setRequestReason("");
    } catch (error) {
      setOaError(safeActionError(error, "申请原文访问失败，请重试。"));
    } finally {
      setOaBusy(false);
    }
  }

  async function loadLifecycleEvents() {
    if (!id) return;
    setLcLoading(true);
    setLcErr(null);
    try {
      const result = await fetchLifecycleEvents(id);
      setLcEvents(result.items);
    } catch (error) {
      setLcErr(safeActionError(error, "生命周期记录加载失败，请重试。"));
    } finally {
      setLcLoading(false);
    }
  }

  async function handleArchiveRequest() {
    if (!id) return;
    if (!lcReason.trim()) {
      setLcErr("请填写归档原因。");
      return;
    }
    setLcBusy(true);
    setLcMsg(null);
    setLcErr(null);
    try {
      await lifecycleArchiveRequest(id, {
        reason: lcReason.trim(),
        candidate_source: "manual",
      });
      setLcMsg("归档候选已提交。");
      await loadLifecycleEvents();
    } catch (error) {
      setLcErr(safeActionError(error, "发起归档失败，请重试。"));
    } finally {
      setLcBusy(false);
    }
  }

  async function handleArchiveConfirm() {
    if (!id) return;
    if (!lcReason.trim()) {
      setLcErr("请填写归档原因。");
      return;
    }
    setLcBusy(true);
    setLcMsg(null);
    setLcErr(null);
    try {
      await lifecycleArchiveConfirm(id, { reason: lcReason.trim() });
      setLcMsg("资产已归档。");
      await reloadAsset();
      await loadLifecycleEvents();
    } catch (error) {
      setLcErr(safeActionError(error, "确认归档失败，请重试。"));
    } finally {
      setLcBusy(false);
    }
  }

  async function handleRetryIndex() {
    if (!id) return;
    setRetryBusy(true);
    setRetryNote(null);
    setRetryErr(null);
    try {
      const result = await retryKnowledgeIndex(id);
      if (result.index_status === "indexed") setRetryNote("问答处理已完成。");
      else if (result.index_status === "skipped") setRetryNote("资产已保留，暂未进入问答。");
      else setRetryNote(result.index_error_message ?? "处理尚未完成，可稍后重试。");
      await reloadAsset();
    } catch (error) {
      setRetryErr(safeActionError(error, "重新处理问答失败，请重试。"));
    } finally {
      setRetryBusy(false);
    }
  }

  async function handleDelete() {
    if (!id) return;
    if (!deleteReason.trim()) {
      setDeleteErr("请填写删除原因。");
      return;
    }
    setDeleteBusy(true);
    setDeleteErr(null);
    try {
      await deleteKnowledgeAsset(id, deleteReason.trim());
      navigate(backPath);
    } catch (error) {
      setDeleteErr(safeActionError(error, "删除失败，请重试。"));
      setDeleteBusy(false);
    }
  }

  useEffect(() => {
    if (!id) return;
    const request = ++requestRef.current;
    setLoading(true);
    setNotFound(false);
    setLoadError(false);
    setAsset(null);
    setLcEvents(null);
    fetchKnowledgeDetail(id)
      .then((detail) => {
        if (request !== requestRef.current) return;
        setAsset(detail);
        setLoading(false);
      })
      .catch((error) => {
        if (request !== requestRef.current) return;
        if (error instanceof ApiError && (error.status === 403 || error.status === 404)) {
          setNotFound(true);
        } else {
          setLoadError(true);
        }
        setLoading(false);
      });
  }, [id, loadAttempt]);

  if (loading) {
    return (
      <main className="product-page kdetail-page" aria-busy="true">
        <Link to="/knowledge" className="kdetail-back">
          <ArrowLeft size={15} aria-hidden="true" /> 返回知识资产库
        </Link>
        <div className="kdetail-state">正在加载资产详情…</div>
      </main>
    );
  }

  if (notFound || (!asset && !loadError)) {
    return (
      <main className="product-page kdetail-page">
        <div className="kdetail-state kdetail-state-centered">
          <FileText size={28} aria-hidden="true" />
          <h1>未找到或无权查看</h1>
          <Link to="/knowledge" className="btn-primary">
            返回知识资产库
          </Link>
        </div>
      </main>
    );
  }

  if (loadError || !asset) {
    return (
      <main className="product-page kdetail-page">
        <div className="kdetail-state kdetail-state-centered" role="alert">
          <h1>资产详情加载失败</h1>
          <p>请检查网络连接后重试。</p>
          <div className="kdetail-state-actions">
            <button
              type="button"
              className="btn-primary"
              onClick={() => setLoadAttempt((value) => value + 1)}
            >
              重新加载
            </button>
            <Link to="/knowledge" className="btn-secondary">
              返回知识资产库
            </Link>
          </div>
        </div>
      </main>
    );
  }

  const canSummary = asset.access.summary;
  const canOriginal = asset.access.original;
  const crossProjectSummary = Boolean(asset.access.crossProjectSummary);
  const pendingOriginal = asset.access.existingRequestStatus === "pending";
  const hasSummaryBody = hasText(asset.detailed) || asset.keyPoints.length > 0;
  const hasOpsActions =
    !crossProjectSummary &&
    (asset.access.canRetryIndex ||
      ((asset.access.canManageLifecycle || asset.access.canDelete) &&
        asset.assetStatus !== "archived"));
  const sharedFacts = [
    { label: "所属范围", value: scopeLabel[asset.scope] ?? asset.scope },
    { label: "所属项目", value: asset.projectName },
  ];
  const memberFacts = [
    { label: "业务阶段", value: asset.lifecyclePhase },
    { label: "当前版本", value: asset.currentVersionNo },
    { label: "维护人", value: asset.maintainerName },
    { label: "访问范围", value: visibilityLabel[asset.visibility] },
    { label: "AI 使用等级", value: aiAccessLabelMap[asset.aiAccessLevel] },
    {
      label: "问答索引",
      value: asset.indexStatus ? (indexStatusLabel[asset.indexStatus] ?? asset.indexStatus) : "",
    },
    {
      label: "规范文本",
      value:
        asset.canonicalMarkdownStatus == null
          ? ""
          : asset.canonicalMarkdownStatus === "generated"
            ? "Markdown 已生成"
            : "Markdown 未生成",
    },
  ];
  const crossProjectFacts = [
    { label: "目录类别", value: asset.categoryPath },
    { label: "规范名版本", value: asset.safeVersion },
    { label: "维护人", value: asset.maintainerName },
    {
      label: "问答与检索",
      value:
        asset.qaAvailable == null && asset.retrievalAvailable == null
          ? ""
          : `${asset.qaAvailable ? "问答可用" : "问答不可用"} · ${asset.retrievalAvailable ? "检索可用" : "检索不可用"}`,
    },
  ];
  const coreFacts = [
    ...sharedFacts,
    ...(crossProjectSummary ? crossProjectFacts : memberFacts),
  ].filter((fact) => hasText(fact.value));

  return (
    <main className="product-page kdetail-page">
      <Link to={backPath} className="kdetail-back">
        <ArrowLeft size={15} aria-hidden="true" /> {backLabel}
      </Link>

      <header className="kdetail-header">
        <div className="kdetail-header-copy">
          <div className="kdetail-badges">
            {crossProjectSummary && (
              <span className="asset-status-badge">
                {canOriginal ? "其他项目 · 原文已授权" : "其他项目 · 摘要可见"}
              </span>
            )}
            <span className={`asset-status-badge ${assetStatusCls[asset.assetStatus]}`}>
              {assetStatusLabel[asset.assetStatus]}
            </span>
            <span className="asset-type-badge">
              {assetTypeLabel[asset.assetType] ?? asset.assetType}
            </span>
            <span className={`confidentiality-badge confidentiality-${asset.confidentialityLevel}`}>
              {confidentialityLabelMap[asset.confidentialityLevel]}
            </span>
            {asset.updatedAt && <time>更新于 {formatBeijingTime(asset.updatedAt)}</time>}
          </div>
          <h1>{asset.title}</h1>
          {!crossProjectSummary && asset.canonicalName && (
            <p className="kd-canonical-name">{asset.canonicalName}</p>
          )}
          {canSummary && (
            <p className={hasText(asset.oneLiner) ? "" : "kdetail-summary-pending"}>
              {hasText(asset.oneLiner) ? asset.oneLiner : "摘要待生成"}
            </p>
          )}
        </div>

        <div className="kdetail-primary-action">
          {canOriginal ? (
            <button
              type="button"
              className="btn-primary"
              onClick={() => void handlePreviewOriginal()}
              disabled={previewLoading}
            >
              <Eye size={16} aria-hidden="true" />
              {previewLoading ? "打开中…" : "预览原文"}
            </button>
          ) : pendingOriginal ? (
            <Link className="btn-secondary" to="/original-access?box=mine">
              查看申请进度
            </Link>
          ) : asset.access.canRequestOriginal ? (
            <button
              type="button"
              className="btn-primary"
              onClick={() => setRequestOpen(true)}
              disabled={oaBusy}
            >
              <FileText size={16} aria-hidden="true" />
              {oaBusy ? "提交中…" : "申请原文访问"}
            </button>
          ) : null}
        </div>
      </header>

      {(previewError || oaError || oaNote) && (
        <div
          className={
            previewError || oaError ? "kdetail-alert is-error" : "kdetail-alert is-success"
          }
          role="status"
        >
          {previewError || oaError || oaNote}
          {oaNote && asset?.access.existingRequestStatus === "pending" && (
            <Link to="/original-access?box=mine">查看申请进度</Link>
          )}
        </div>
      )}

      <div className="kdetail-layout">
        <div className="kdetail-main-column">
          {(!canSummary || hasSummaryBody || !hasText(asset.oneLiner)) && (
            <section className="kdetail-panel" aria-labelledby="summary-title">
              <div className="kdetail-panel-heading">
                <FileText size={17} aria-hidden="true" />
                <h2 id="summary-title">内容摘要</h2>
              </div>
              {!canSummary ? (
                <div className="kdetail-restricted">当前身份不可查看内容摘要。</div>
              ) : !hasText(asset.oneLiner) && !hasSummaryBody ? (
                <div className="kdetail-muted-state">摘要待生成</div>
              ) : (
                <div className="kdetail-summary-body">
                  {hasText(asset.detailed) && <p>{asset.detailed}</p>}
                  {asset.keyPoints.length > 0 && (
                    <div>
                      <h3>关键知识点</h3>
                      <ul>
                        {asset.keyPoints.map((point) => (
                          <li key={point}>{point}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </section>
          )}

          <section className="kdetail-panel" aria-labelledby="facts-title">
            <div className="kdetail-panel-heading">
              <ShieldCheck size={17} aria-hidden="true" />
              <h2 id="facts-title">核心信息</h2>
            </div>
            <dl className="kdetail-facts">
              {coreFacts.map((fact) => (
                <div key={fact.label}>
                  <dt>{fact.label}</dt>
                  <dd>{fact.value}</dd>
                </div>
              ))}
              {asset.tags.length > 0 && (
                <div className="kdetail-fact-tags">
                  <dt>标签</dt>
                  <dd>
                    {asset.tags.map((tag) => (
                      <span className="tag" key={tag}>
                        {tag}
                      </span>
                    ))}
                  </dd>
                </div>
              )}
            </dl>
            {!crossProjectSummary && asset.indexStatus === "index_failed" && (
              <div className="kdetail-inline-error" role="alert">
                {asset.indexErrorMessage ?? "问答处理失败，可在更多操作中重新处理。"}
              </div>
            )}
          </section>
        </div>

        <aside className="kdetail-side-column" aria-label="访问与治理">
          <section className="kdetail-panel kdetail-access-panel">
            <div className="kdetail-panel-heading">
              <ShieldCheck size={17} aria-hidden="true" />
              <h2>访问与状态</h2>
            </div>
            <dl className="kdetail-access-list">
              <div>
                <dt>访问层级</dt>
                <dd className={canOriginal ? "is-allowed" : "is-restricted"}>
                  {accessLabel(asset)}
                </dd>
              </div>
              <div>
                <dt>内容摘要</dt>
                <dd className={canSummary ? "is-allowed" : "is-restricted"}>
                  {canSummary ? "可访问" : "受限"}
                </dd>
              </div>
              <div>
                <dt>原文</dt>
                <dd className={canOriginal ? "is-allowed" : "is-restricted"}>
                  {canOriginal
                    ? "可访问"
                    : pendingOriginal
                      ? "审批中"
                      : asset.access.canRequestOriginal
                        ? "需申请"
                        : "不可访问"}
                </dd>
              </div>
              {asset.access.existingGrantExpiresAt && (
                <div>
                  <dt>授权有效期</dt>
                  <dd>{formatBeijingTime(asset.access.existingGrantExpiresAt)}</dd>
                </div>
              )}
            </dl>
            <button
              type="button"
              className="kdetail-explain-action"
              onClick={() => setExplainOpen(true)}
            >
              为什么是这个状态？
            </button>
          </section>

          {!crossProjectSummary && (
            <details
              className="kdetail-panel kdetail-disclosure"
              onToggle={(event) => {
                if (event.currentTarget.open && lcEvents === null && !lcLoading) {
                  void loadLifecycleEvents();
                }
              }}
            >
              <summary>
                <span>生命周期</span>
                <ChevronRight size={17} aria-hidden="true" />
              </summary>
              <div className="kdetail-disclosure-body">
                {lcLoading ? (
                  <div className="kdetail-muted-state">正在加载记录…</div>
                ) : lcErr && lcEvents === null ? (
                  <div className="kdetail-retry-state" role="alert">
                    <span>{lcErr}</span>
                    <button
                      type="button"
                      className="btn-small"
                      onClick={() => void loadLifecycleEvents()}
                    >
                      重试
                    </button>
                  </div>
                ) : lcEvents?.length ? (
                  <ol className="kdetail-timeline">
                    {lcEvents.map((event) => (
                      <li key={event.event_id}>
                        <span className="kdetail-timeline-dot" aria-hidden="true" />
                        <div>
                          <strong>{lifecycleEventLabel[event.event_type] ?? "生命周期事件"}</strong>
                          <time>{formatBeijingTime(event.created_at)}</time>
                          {event.actor_display && <span>{event.actor_display}</span>}
                          {event.reason && <p>{event.reason}</p>}
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <div className="kdetail-muted-state">暂无生命周期记录</div>
                )}
              </div>
            </details>
          )}

          {hasOpsActions && (
            <details className="kdetail-panel kdetail-disclosure kdetail-ops">
              <summary>
                <span>更多操作</span>
                <ChevronRight size={17} aria-hidden="true" />
              </summary>
              <div className="kdetail-disclosure-body">
                {asset.access.canManageLifecycle && asset.assetStatus !== "archived" && (
                  <div className="kdetail-ops-group">
                    <label htmlFor="archive-reason">归档原因</label>
                    <textarea
                      id="archive-reason"
                      rows={3}
                      value={lcReason}
                      onChange={(event) => setLcReason(event.target.value)}
                    />
                    <div className="kdetail-ops-buttons">
                      <button
                        type="button"
                        className="btn-small"
                        onClick={() => void handleArchiveRequest()}
                        disabled={lcBusy}
                      >
                        <Archive size={14} aria-hidden="true" /> 发起归档候选
                      </button>
                      <button
                        type="button"
                        className="btn-small"
                        onClick={() => void handleArchiveConfirm()}
                        disabled={lcBusy}
                      >
                        确认归档
                      </button>
                    </div>
                  </div>
                )}

                {asset.access.canRetryIndex && (
                  <button
                    type="button"
                    className="btn-small kdetail-full-action"
                    onClick={() => void handleRetryIndex()}
                    disabled={retryBusy}
                  >
                    <RefreshCw size={14} aria-hidden="true" />
                    {retryBusy ? "处理中…" : "重新处理问答"}
                  </button>
                )}

                {asset.access.canDelete && asset.assetStatus !== "archived" && (
                  <div className="kdetail-danger-zone">
                    {!confirmDelete ? (
                      <button
                        type="button"
                        className="btn-small btn-small-danger"
                        onClick={() => setConfirmDelete(true)}
                      >
                        <Trash2 size={14} aria-hidden="true" /> 删除资产
                      </button>
                    ) : (
                      <div className="kdetail-delete-confirm">
                        <p>删除后资产将退出列表、问答与原文预览，此操作会保留审计记录。</p>
                        <label htmlFor="delete-reason">删除原因</label>
                        <textarea
                          id="delete-reason"
                          rows={3}
                          value={deleteReason}
                          onChange={(event) => setDeleteReason(event.target.value)}
                        />
                        <div className="kdetail-ops-buttons">
                          <button
                            type="button"
                            className="btn-small btn-small-danger"
                            onClick={() => void handleDelete()}
                            disabled={deleteBusy}
                          >
                            {deleteBusy ? "删除中…" : "确认删除"}
                          </button>
                          <button
                            type="button"
                            className="btn-small"
                            onClick={() => setConfirmDelete(false)}
                            disabled={deleteBusy}
                          >
                            取消
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {(lcMsg || lcErr || retryNote || retryErr || deleteErr) && (
                  <div
                    className={
                      lcErr || retryErr || deleteErr
                        ? "kdetail-inline-error"
                        : "kdetail-inline-success"
                    }
                    role="status"
                  >
                    {lcErr || retryErr || deleteErr || lcMsg || retryNote}
                  </div>
                )}
              </div>
            </details>
          )}
        </aside>
      </div>

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
          </div>
        </div>
      )}
      <AccessExplanationDrawer
        open={explainOpen}
        asset={asset}
        capabilities={capabilities}
        onClose={() => setExplainOpen(false)}
        onRequest={() => {
          setExplainOpen(false);
          setRequestOpen(true);
        }}
        onRetryIndex={() => {
          setExplainOpen(false);
          void handleRetryIndex();
        }}
      />
      <TaskModal
        open={requestOpen}
        size="small"
        title="申请原文"
        description="申请当前资料的受控原文；提交前不会改变资料、授权或审批状态。"
        busy={oaBusy}
        onClose={() => {
          if (!oaBusy) {
            setRequestOpen(false);
            setRequestReason("");
          }
        }}
        footer={
          <>
            <button
              type="button"
              className="btn-secondary"
              disabled={oaBusy}
              onClick={() => {
                setRequestOpen(false);
                setRequestReason("");
              }}
            >
              取消
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={oaBusy}
              onClick={() => void handleRequestOriginal()}
            >
              {oaBusy ? "提交中…" : "提交申请"}
            </button>
          </>
        }
      >
        <label className="kdetail-request-field">
          <span>申请理由（可选）</span>
          <textarea
            rows={4}
            value={requestReason}
            onChange={(event) => setRequestReason(event.target.value)}
            placeholder="说明需要使用原文的业务场景"
          />
        </label>
      </TaskModal>
    </main>
  );
}
