import { RestoreAssetButton } from "../components/operations/AssetTools";
import {
  Archive,
  ArrowLeft,
  ChevronRight,
  Eye,
  FileText,
  History,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { Link } from "react-router-dom";
import AccessExplanationDrawer, { accessLabel } from "../components/AccessExplanationDrawer";
import { ActionGroup } from "../components/ActionLayout";
import KnowledgeMetadataEditor from "../components/KnowledgeMetadataEditor";
import { summaryPendingLabel } from "../components/knowledgeSummaryState";
import KnowledgeTrustPanel from "../components/KnowledgeTrustPanel";
import KnowledgeVersionPanel from "../components/KnowledgeVersionPanel";
import ProjectCompanyPublicationDialog, {
  getProjectCompanyPublicationEligibility,
} from "../components/ProjectCompanyPublicationDialog";
import TaskModal from "../components/TaskModal";
import WorkspaceTabs from "../components/WorkspaceTabs";
import { HistoryBackButton } from "../routing/SafeNavigation";
import { formatBeijingTime } from "../utils/time";
import {
  aiAccessLabelMap,
  assetStatusCls,
  assetStatusLabel,
  confidentialityLabelMap,
  hasText,
  indexStatusLabel,
  lifecycleEventLabel,
  scopeLabel,
  visibilityLabel,
} from "./controllers/KnowledgeDetail/model";
import { useKnowledgeDetail } from "./controllers/KnowledgeDetail/useKnowledgeDetail";
import { OnlyOfficePreview } from "./knowledge/OnlyOfficePreview";
import "./KnowledgeDetailPage.css";
export { OnlyOfficePreview } from "./knowledge/OnlyOfficePreview";
export default function KnowledgeDetailPage() {
  const {
    loading,
    backPath,
    backLabel,
    notFound,
    asset,
    loadError,
    authorizedHistory,
    id,
    setAuthorizedHistory,
    setLoadAttempt,
    authMe,
    handlePreviewOriginal,
    previewLoading,
    setRequestOpen,
    oaBusy,
    setPreviewOpen,
    setPreviewEntry,
    previewError,
    oaError,
    oaNote,
    publicationNote,
    detailView,
    setDetailView,
    setNotFound,
    reloadAsset,
    setPublicationNote,
    setPublicationOpen,
    lcEvents,
    lcLoading,
    loadLifecycleEvents,
    lcErr,
    lcReason,
    setLcReason,
    handleArchiveRequest,
    lcBusy,
    handleArchiveConfirm,
    handleRetryIndex,
    retryBusy,
    confirmDelete,
    setConfirmDelete,
    deleteReason,
    setDeleteReason,
    handleDelete,
    deleteBusy,
    lcMsg,
    retryNote,
    retryErr,
    deleteErr,
    metadataExpanded,
    setMetadataExpanded,
    setExplainOpen,
    publicationOpen,
    previewOpen,
    previewEntry,
    explainOpen,
    capabilities,
    requestOpen,
    setRequestReason,
    handleRequestOriginal,
    requestReason,
  } = useKnowledgeDetail();

  if (loading) {
    return (
      <main className="product-page kdetail-page" aria-busy="true">
        <HistoryBackButton fallback={backPath} className="kdetail-back">
          <ArrowLeft size={15} aria-hidden="true" /> {backLabel}
        </HistoryBackButton>
        <div className="kdetail-state">正在加载资产详情…</div>
      </main>
    );
  }

  if (notFound || (!asset && !loadError)) {
    const replaced =
      authorizedHistory !== null &&
      authorizedHistory.asset_id === id &&
      Boolean(authorizedHistory.current_asset_id && authorizedHistory.current_asset_id !== id) &&
      authorizedHistory.items.some((item) => item.asset_id === id && item.status === "archived");
    return (
      <main className="product-page kdetail-page">
        <div className="kdetail-state kdetail-state-centered">
          <FileText size={28} aria-hidden="true" />
          <h1>{replaced ? "资料已被新版替代" : "未找到或无权查看"}</h1>
          {replaced && <p>旧版已归档；可查看当前版本或在版本历史中追溯旧版。</p>}
          <HistoryBackButton fallback={backPath} className="btn-primary">
            {backLabel}
          </HistoryBackButton>
        </div>
        {id && (
          <>
            <KnowledgeVersionPanel key={id} assetId={id} onHistoryLoaded={setAuthorizedHistory} />
            <KnowledgeTrustPanel assetId={id} />
          </>
        )}
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
            <HistoryBackButton fallback={backPath} className="btn-secondary">
              {backLabel}
            </HistoryBackButton>
          </div>
        </div>
      </main>
    );
  }

  const canSummary = asset.access.summary;
  const canOriginal = asset.access.original;
  const crossProjectSummary = Boolean(asset.access.crossProjectSummary);
  const assetProject = asset.projectId
    ? authMe?.projects.find((project) => project.projectId === asset.projectId)
    : null;
  const publicationEligibility = asset.projectId
    ? getProjectCompanyPublicationEligibility(asset, asset.projectId, assetProject?.projectRole)
    : { eligible: false, reason: "仅项目经理可提交公司发布申请" };
  const pendingOriginal = asset.access.existingRequestStatus === "pending";
  const hasSummaryBody = hasText(asset.detailed) || asset.keyPoints.length > 0;
  const hasOpsActions =
    !crossProjectSummary &&
    (asset.access.canRetryIndex ||
      asset.access.canManageLifecycle ||
      (asset.access.canDelete && asset.assetStatus !== "archived"));
  const sharedFacts = [
    { label: "所属范围", value: scopeLabel[asset.scope] ?? asset.scope },
    { label: "所属项目", value: asset.projectName },
  ];
  const memberFacts = [
    { label: "标准目录", value: asset.directoryPath },
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
    { label: "正式目录", value: asset.directoryPath ?? "未提供" },
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
      <HistoryBackButton fallback={backPath} className="kdetail-back">
        <ArrowLeft size={15} aria-hidden="true" /> {backLabel}
      </HistoryBackButton>

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
            <span className={`confidentiality-badge confidentiality-${asset.confidentialityLevel}`}>
              {confidentialityLabelMap[asset.confidentialityLevel]}
            </span>
            {(asset.metadataUpdatedAt || asset.updatedAt) && (
              <time>更新于 {formatBeijingTime(asset.metadataUpdatedAt || asset.updatedAt)}</time>
            )}
          </div>
          <div className="kdetail-object-title">
            <span className="workspace-file-mark" aria-hidden="true">
              <FileText size={23} />
            </span>
            <h1>{asset.title}</h1>
          </div>
          {!crossProjectSummary && asset.canonicalName && (
            <p className="kd-canonical-name">{asset.canonicalName}</p>
          )}
        </div>

        <ActionGroup
          className="kdetail-primary-action"
          label="资料阅读与编辑"
          primary={
            <>
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
            </>
          }
          secondary={
            <>
              {" "}
              <KnowledgeMetadataEditor
                key={asset.id}
                asset={asset}
                onSaved={() => {
                  setPreviewOpen(false);
                  setPreviewEntry(null);
                  setLoadAttempt((value) => value + 1);
                }}
              />
            </>
          }
        />
      </header>

      {(previewError || oaError || oaNote || publicationNote) && (
        <div
          className={
            previewError || oaError ? "kdetail-alert is-error" : "kdetail-alert is-success"
          }
          role="status"
        >
          {previewError || oaError || oaNote || publicationNote}
          {oaNote && asset?.access.existingRequestStatus === "pending" && (
            <Link to="/original-access?box=mine">查看申请进度</Link>
          )}
        </div>
      )}

      <div className="kdetail-layout">
        <div className="kdetail-main-column">
          <WorkspaceTabs
            label="资料内容导航"
            value={detailView}
            onChange={setDetailView}
            items={[
              {
                key: "content",
                label: "内容摘要",
                icon: <FileText size={16} aria-hidden="true" />,
                content: (
                  <>
                    <section
                      className="kdetail-panel kdetail-reading-surface"
                      aria-labelledby="summary-title"
                    >
                      <div className="kdetail-panel-heading">
                        <FileText size={17} aria-hidden="true" />
                        <h2 id="summary-title">内容摘要</h2>
                      </div>
                      {!canSummary ? (
                        <div className="kdetail-restricted">当前身份不可查看内容摘要。</div>
                      ) : !hasText(asset.oneLiner) && !hasSummaryBody ? (
                        <div className="kdetail-muted-state">{summaryPendingLabel(asset)}</div>
                      ) : (
                        <div className="kdetail-summary-body">
                          {hasText(asset.oneLiner) && (
                            <p className="kdetail-lead">{asset.oneLiner}</p>
                          )}
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
                  </>
                ),
              },
              {
                key: "versions",
                label: "版本记录",
                icon: <History size={16} aria-hidden="true" />,
                content: (
                  <>
                    <div className="kdetail-view-intro">
                      <h2>版本记录</h2>
                      <p>查看资料版本，比较内容变化；可用操作以当前权限为准。</p>
                    </div>
                    <div className="kdetail-version-area">
                      <KnowledgeVersionPanel
                        showOverview
                        key={`${asset.id}:${asset.metadataUpdatedAt ?? ""}`}
                        assetId={asset.id}
                        onReplaced={() => setNotFound(true)}
                      />
                    </div>
                  </>
                ),
              },
              {
                key: "manage",
                label: "维护与发布",
                icon: <Settings2 size={16} aria-hidden="true" />,
                content: (
                  <div className="kdetail-management-content">
                    <section
                      className="kdetail-panel kdetail-governance-panel"
                      aria-labelledby="governance-title"
                    >
                      <div className="kdetail-panel-heading">
                        <ShieldCheck size={17} aria-hidden="true" />
                        <h2 id="governance-title">维护与发布</h2>
                      </div>
                      <ActionGroup label="资料治理操作">
                        <KnowledgeTrustPanel
                          assetId={asset.id}
                          revision={asset.metadataUpdatedAt ?? undefined}
                          onChanged={(result) => {
                            if (result.freshness === "archived") setNotFound(true);
                            else void reloadAsset();
                          }}
                        />
                        {asset.scope === "project" && (
                          <div className="kdetail-publication-action">
                            {publicationEligibility.eligible ? (
                              <button
                                type="button"
                                className="product-button is-secondary"
                                onClick={() => {
                                  setPublicationNote(null);
                                  setPublicationOpen(true);
                                }}
                              >
                                发布到公司知识库
                              </button>
                            ) : (
                              <span className="kdetail-action-reason">
                                {publicationEligibility.reason}
                              </span>
                            )}
                          </div>
                        )}
                      </ActionGroup>
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
                                    <strong>
                                      {lifecycleEventLabel[event.event_type] ?? "生命周期事件"}
                                    </strong>
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
                          {asset.access.canManageLifecycle && asset.assetStatus === "archived" && (
                            <RestoreAssetButton
                              assetId={asset.id}
                              onChanged={() => void reloadAsset()}
                            />
                          )}
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
                                  <p>
                                    删除后资产将退出列表、问答与原文预览，此操作会保留审计记录。
                                  </p>
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
                  </div>
                ),
              },
            ]}
          />
        </div>
        <aside
          className={`kdetail-side-column${metadataExpanded ? " is-expanded" : ""}`}
          aria-label="访问与治理"
        >
          <button
            className="kdetail-property-toggle"
            type="button"
            aria-expanded={metadataExpanded}
            aria-controls="knowledge-detail-properties"
            onClick={() => setMetadataExpanded((value) => !value)}
          >
            <ShieldCheck size={17} aria-hidden="true" /> 资料信息与访问权限{" "}
            <ChevronRight size={16} aria-hidden="true" />
          </button>
          <div className="kdetail-properties" id="knowledge-detail-properties">
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
                  {asset.indexErrorMessage ?? "资产已保留，但索引未完成；可在更多操作中恢复索引。"}
                </div>
              )}
            </section>
          </div>
        </aside>
      </div>

      {asset.projectId && (
        <ProjectCompanyPublicationDialog
          projectId={asset.projectId}
          target={publicationOpen ? asset : null}
          onClose={() => setPublicationOpen(false)}
          onSubmitted={() => {
            setPublicationOpen(false);
            setPublicationNote("已提交公司发布申请。");
          }}
        />
      )}

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
