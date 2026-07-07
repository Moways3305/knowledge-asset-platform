import { useParams, Link, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { ApiError } from "../api/http";
import {
  deleteKnowledgeAsset,
  fetchKnowledgeDetail,
  fetchLifecycleEvents,
  issuePreview,
  lifecycleArchiveConfirm,
  lifecycleArchiveRequest,
  previewEntryHref,
  requestOriginalAccess,
  retryKnowledgeIndex,
} from "../api/knowledge";
import type { PreviewIssueResponseDTO } from "../types/preview";
import type { LifecycleEventDTO } from "../types/lifecycle";
import type {
  AiAccessLevel,
  AssetStatus,
  ConfidentialityLevel,
  FrontVisibility,
  KnowledgeDetailVM,
} from "../types/knowledge";
import { formatBeijingTime } from "../utils/time";

const visibilityLabel: Record<FrontVisibility, string> = {
  public: "公开",
  "project-only": "项目内",
  confidential: "机密",
};

const visibilityDescription: Record<FrontVisibility, string> = {
  public: "该资产全公司可见，可直接引用和复用。无需额外申请。",
  "project-only": "该资产仅对所属项目顾问可见。如需在其他项目中引用，请通过申请权限。",
  confidential: "该资产为机密级别，仅限指定人员访问。查看原文需经审批，记录全程留痕。",
};

const confidentialityLabelMap: Record<ConfidentialityLevel, string> = {
  L1: "L1 公开级",
  L2: "L2 内部参考级",
  L3: "L3 受限级",
  L4: "L4 商业秘密级",
  L5: "L5 严格商业秘密级",
};

const aiAccessLabelMap: Record<AiAccessLevel, string> = {
  A1: "A1 可直接调用",
  A2: "A2 脱敏后调用",
  A3: "A3 摘要后调用",
  A4: "A4 禁止调用",
};

const agentAccessHint: Record<AiAccessLevel, { allowed: string; desc: string }> = {
  A1: { allowed: "可进入问答与摘要", desc: "Agent 可直接检索并引用该资产进行问答、摘要生成。" },
  A2: {
    allowed: "脱敏后可进入问答",
    desc: "Agent 仅可使用脱敏版本进行问答和摘要，原文不进入 Agent 调用。",
  },
  A3: {
    allowed: "仅摘要/元数据可被调用",
    desc: "Agent 只能引用该资产的摘要和元数据，不可调用原文或脱敏版。",
  },
  A4: {
    allowed: "禁止进入 Agent 调用",
    desc: "该资产完全禁止进入 Agent 问答、摘要或任何自动化调用。",
  },
};

const confidentialityHint: Record<ConfidentialityLevel, string> = {
  L1: "公开级内容，可自由进入 AI 摘要与问答。",
  L2: "内部参考级：脱敏后可进入 AI 摘要与问答。",
  L3: "受限级：仅限脱敏或摘要形式进入 AI 处理，原文不外发。",
  L4: "商业秘密级：原文不得进入开放式 AI 环境，优先使用脱敏版或摘要。",
  L5: "严格商业秘密级：禁止任何形式进入 AI 调用，仅限授权人员线下访问。",
};

const assetStatusLabel: Record<AssetStatus, string> = {
  active: "活跃",
  needs_update: "待更新",
  deprecated: "已废弃",
  archived: "已归档",
};

const assetStatusCls: Record<AssetStatus, string> = {
  active: "asset-status-active",
  needs_update: "asset-status-needs-update",
  deprecated: "asset-status-deprecated",
  archived: "asset-status-archived",
};

const assetStatusHint: Record<AssetStatus, string> = {
  active: "该资产处于活跃状态，正常参与日常检索和问答。",
  needs_update: "该资产被标记为待更新，建议维护人尽快更新内容后恢复活跃状态。",
  deprecated: "该资产已废弃，仍可查看但不推荐引用。",
  archived: "该资产已归档，默认不参与日常检索和问答。如需重新启用，请联系维护人。",
};

const assetTypeLabel: Record<string, string> = {
  methodology: "方法论",
  deliverable: "交付物",
  case: "案例",
  template: "模板",
  insight: "洞察",
};

const confidenceText = (c: number | null) => (c == null ? "—" : `${Math.round(c * 100)}%`);

// 平台级检索索引状态展示。
const indexStatusLabel: Record<string, string> = {
  indexed: "已索引",
  indexing: "索引中",
  index_failed: "索引失败",
  skipped: "未索引（索引未启用 / 已跳过）",
  not_indexed: "待索引",
};

export default function KnowledgeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [asset, setAsset] = useState<KnowledgeDetailVM | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 预览凭证
  const [preview, setPreview] = useState<PreviewIssueResponseDTO | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  async function handleRequestPreview() {
    if (!id) return;
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      setPreview(await issuePreview(id));
    } catch (e) {
      setPreviewError(e instanceof ApiError ? e.message : "申请预览失败");
    } finally {
      setPreviewLoading(false);
    }
  }

  // 原文访问申请
  const [oaBusy, setOaBusy] = useState(false);
  const [oaError, setOaError] = useState<string | null>(null);
  const [oaNote, setOaNote] = useState<string | null>(null);

  async function reloadAsset() {
    if (!id) return;
    try {
      setAsset(await fetchKnowledgeDetail(id));
    } catch {
      /* 保持原状 */
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
        created: "原文访问申请已提交，待项目经理 / 治理角色审批。",
        pending_exists: "你已有待审批的原文访问申请。",
        already_granted: "你已拥有该资产的原文访问权。",
      };
      setOaNote(msg[r.status] ?? r.message);
      await reloadAsset();
    } catch (e) {
      setOaError(
        e instanceof ApiError
          ? `${e.message}（${e.deniedReason ?? e.status}）`
          : "申请原文访问失败",
      );
    } finally {
      setOaBusy(false);
    }
  }

  // 生命周期治理动作。归档是治理流程：先发起建议，再人工确认。
  const [lcEvents, setLcEvents] = useState<LifecycleEventDTO[] | null>(null);
  const [lcReason, setLcReason] = useState("");
  const [lcMsg, setLcMsg] = useState<string | null>(null);
  const [lcErr, setLcErr] = useState<string | null>(null);
  const [lcBusy, setLcBusy] = useState(false);

  // 受控删除 / 撤下。仅在后端 access.canDelete 时展示；二次确认后调真实接口。
  const navigate = useNavigate();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteReason, setDeleteReason] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);

  async function handleDelete() {
    if (!id) return;
    setDeleteBusy(true);
    setDeleteErr(null);
    try {
      await deleteKnowledgeAsset(id, deleteReason || undefined);
      // 成功后资产退出检索/问答/预览，详情页跳回知识列表。
      navigate("/knowledge");
    } catch (e) {
      setDeleteErr(
        e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "删除失败",
      );
      setDeleteBusy(false);
    }
  }

  // 底座索引重试。仅在后端 access.canRetryIndex 时展示按钮；成功后刷新详情。
  const [retryBusy, setRetryBusy] = useState(false);
  const [retryNote, setRetryNote] = useState<string | null>(null);
  const [retryErr, setRetryErr] = useState<string | null>(null);

  async function handleRetryIndex() {
    if (!id) return;
    setRetryBusy(true);
    setRetryNote(null);
    setRetryErr(null);
    try {
      const r = await retryKnowledgeIndex(id);
      if (r.index_status === "indexed") setRetryNote("已重新完成检索索引。");
      else if (r.index_status === "skipped") setRetryNote("检索索引暂未启用，已标记为跳过索引。");
      else setRetryNote(r.index_error_message ?? "重试后索引仍失败，可稍后再试或联系管理员。");
      await reloadAsset();
    } catch (e) {
      setRetryErr(
        e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "重试索引失败",
      );
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
      setLcErr(
        e instanceof ApiError
          ? `${e.message}（${e.deniedReason ?? e.status}）`
          : "加载生命周期事件失败",
      );
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
      setLcMsg(`已生成归档候选（${r.status}）。归档需再行人工确认。`);
      await loadLcEvents();
    } catch (e) {
      setLcErr(
        e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "发起归档失败",
      );
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
      setLcMsg(`资产已归档（状态：${r.asset_status}）。归档资产默认退出检索 / 问答。`);
      await loadLcEvents();
    } catch (e) {
      setLcErr(
        e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "确认归档失败",
      );
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
          <p>资产「{id}」不存在或当前身份不可见（如 L5 / 他人个人知识 / 已归档）。</p>
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

  return (
    <div className="detail-page">
      <Link to="/knowledge" className="back-link">
        &larr; 返回知识首页
      </Link>

      <div className="detail-title-area">
        <h2 className="detail-title">{asset.title}</h2>
        <div className="detail-title-meta">
          <span className={`visibility-badge ${asset.visibility}`}>
            {visibilityLabel[asset.visibility]}
          </span>
          <span className="asset-type-badge">
            {assetTypeLabel[asset.assetType] ?? asset.assetType}
          </span>
          <span className="detail-meta-item">置信度 {confidenceText(asset.confidence)}</span>
          <span className="detail-meta-item">更新 {formatBeijingTime(asset.updatedAt)}</span>
        </div>
      </div>

      {/* 摘要与标签：按 access_info.summary 控制 */}
      <section className="detail-section">
        <h3>摘要与标签</h3>
        {canSummary ? (
          <div className="detail-summary-layers">
            <div className="detail-summary-layer">
              <span className="detail-summary-layer-label">一句话摘要</span>
              <p className="detail-summary-oneliner">{asset.oneLiner || "—"}</p>
            </div>
            <div className="detail-summary-layer">
              <span className="detail-summary-layer-label">详细摘要</span>
              <p className="detail-summary-text">{asset.detailed || "—"}</p>
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
            {(asset.confidentialityLevel === "L3" || asset.confidentialityLevel === "L4") && (
              <p className="confidentiality-derivation-note">
                L3/L4 对外仅展示脱敏/安全摘要，不含客户敏感数据。
              </p>
            )}
          </div>
        ) : (
          <p className="detail-summary-text">当前身份无摘要层权限。</p>
        )}
        <div className="card-tags">
          {asset.tags.map((t) => (
            <span key={t} className="tag">
              {t}
            </span>
          ))}
        </div>
      </section>

      {/* 来源追溯（仅展示后端可见的安全元数据） */}
      <section className="detail-section">
        <h3>来源追溯</h3>
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
            <span className="detail-prov-label">归属范围</span>
            <span className="detail-prov-value">
              {asset.scope} / {asset.zone}
            </span>
          </div>
        </div>
      </section>

      {/* 权限与治理 */}
      <section className="detail-section">
        <h3>权限与治理</h3>
        <div className={`visibility-notice ${asset.visibility}`}>
          <strong>当前可见性：{visibilityLabel[asset.visibility]}</strong>
          <p>{visibilityDescription[asset.visibility]}</p>
        </div>
        <div className="detail-access-rules">
          <div className="detail-access-rule">
            <span className="detail-access-indicator detail-access-phase1" />
            <span className="detail-access-text">
              <strong>发现层</strong> — {asset.access.discovery ? "可发现" : "不可发现"}
            </span>
          </div>
          <div className="detail-access-rule">
            <span className="detail-access-indicator detail-access-phase2" />
            <span className="detail-access-text">
              <strong>摘要层</strong> — {canSummary ? "可查看摘要" : "无摘要权限"}
            </span>
          </div>
          <div className="detail-access-rule">
            <span className="detail-access-indicator detail-access-cross" />
            <span className="detail-access-text">
              <strong>原文层</strong> —{" "}
              {canOriginal
                ? "可访问原文"
                : asset.access.canRequestOriginal
                  ? "需申请原文"
                  : "不可访问原文"}
              （权限来源：{asset.access.effectiveSource}）
            </span>
          </div>
        </div>
      </section>

      {/* 保密分级与 AI 调用边界 */}
      <section className="detail-section">
        <h3>保密分级与 AI 调用边界</h3>
        <div className="confidentiality-detail-grid">
          <div className="confidentiality-detail-card">
            <div className="confidentiality-detail-label">保密级别</div>
            <div className="confidentiality-detail-value">
              <span
                className={`confidentiality-badge confidentiality-${asset.confidentialityLevel}`}
              >
                {confidentialityLabelMap[asset.confidentialityLevel]}
              </span>
            </div>
          </div>
          <div className="confidentiality-detail-card">
            <div className="confidentiality-detail-label">AI 调用级别</div>
            <div className="confidentiality-detail-value">
              <span className={`ai-access-badge ai-access-${asset.aiAccessLevel}`}>
                {aiAccessLabelMap[asset.aiAccessLevel]}
              </span>
            </div>
          </div>
        </div>
        <div className="confidentiality-hint-card">
          <strong>调用边界说明</strong>
          <p>{confidentialityHint[asset.confidentialityLevel]}</p>
          {(asset.confidentialityLevel === "L4" || asset.confidentialityLevel === "L5") && (
            <p className="confidentiality-l45-warning">
              L4/L5 文件不得进入开放式 AI 调用；仅可按脱敏/摘要策略处理。
            </p>
          )}
        </div>
      </section>

      {/* Agent 调用边界 */}
      <section className="detail-section">
        <h3>Agent 调用边界</h3>
        <div className="agent-access-panel">
          <div className="agent-access-status">
            <span className="agent-access-status-label">当前 Agent 调用策略</span>
            <span
              className={`agent-access-status-badge ${asset.aiAccessLevel === "A4" ? "agent-access-denied" : "agent-access-allowed"}`}
            >
              {agentAccessHint[asset.aiAccessLevel].allowed}
            </span>
          </div>
          <div className="agent-access-desc">{agentAccessHint[asset.aiAccessLevel].desc}</div>
          <p className="page-help-line">
            Agent
            跟随调用人权限、经平台权限网关调用，不获得原文访问凭证、不绕过权限网关，只生成建议；详见{" "}
            <Link to="/help#integration" className="page-help-link">
              使用说明 →
            </Link>
          </p>
        </div>
      </section>

      {/* 资产生命周期 */}
      <section className="detail-section">
        <h3>资产生命周期</h3>
        <div className="lifecycle-status-grid">
          <div className="lifecycle-status-card">
            <div className="lifecycle-status-label">生命周期状态</div>
            <div className="lifecycle-status-value">
              <span className={`asset-status-badge ${assetStatusCls[asset.assetStatus]}`}>
                {assetStatusLabel[asset.assetStatus]}
              </span>
            </div>
          </div>
          <div className="lifecycle-status-card">
            <div className="lifecycle-status-label">最后调用时间</div>
            <div className="lifecycle-status-value">{formatBeijingTime(asset.lastCalledAt)}</div>
          </div>
          <div className="lifecycle-status-card">
            <div className="lifecycle-status-label">维护人</div>
            <div className="lifecycle-status-value">{asset.maintainerName || "—"}</div>
          </div>
        </div>
        <div className="lifecycle-status-hint">{assetStatusHint[asset.assetStatus]}</div>
        {asset.assetStatus === "archived" && (
          <div className="lifecycle-archive-detail">
            <div className="lifecycle-archive-reason">
              <strong>归档原因：</strong>
              {asset.archiveReason || "—"}
            </div>
            <div className="lifecycle-archive-warning">归档资产默认不参与日常检索和问答。</div>
          </div>
        )}

        {/* 生命周期治理动作。归档需「发起建议 → 人工确认」两步；
            权限由后端按 scope 治理角色裁定（personal 本人 / project maintainer·PM /
            company 治理角色），纯 admin 无业务治理权。Agent 不执行治理动作。 */}
        <div className="lifecycle-action-area">
          <div className="lifecycle-action-row">
            <input
              className="lifecycle-reason-input"
              type="text"
              placeholder="治理原因（归档 / 重新启用说明）"
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
              查看生命周期事件
            </button>
            {asset.access.canDelete && asset.assetStatus !== "archived" && (
              <button
                className="btn-small btn-small-danger"
                onClick={() => {
                  setConfirmDelete(true);
                  setDeleteErr(null);
                }}
                disabled={deleteBusy}
              >
                删除 / 撤下
              </button>
            )}
          </div>
          {confirmDelete && (
            <div className="lifecycle-delete-confirm">
              <p className="lifecycle-delete-warning">
                删除后该资产将<strong>立即退出检索 / 问答 / 预览 / 外部 Agent</strong>
                ，相关原文授权同时失效；操作保留审计追溯，不可在产品内自助恢复。
              </p>
              <input
                className="lifecycle-reason-input"
                type="text"
                placeholder="删除原因（如：上传错误 / 重复 / 不应入库）"
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
          {lcEvents &&
            (lcEvents.length === 0 ? (
              <div className="lifecycle-events-empty">暂无生命周期事件</div>
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
      </section>

      {/* 检索索引状态。未索引资产不会被语义检索召回；可重试者可重新推进索引。 */}
      <section className="detail-section">
        <h3>检索索引</h3>
        <div className="lifecycle-status-grid">
          <div className="lifecycle-status-card">
            <div className="lifecycle-status-label">索引状态</div>
            <div className="lifecycle-status-value">
              <span
                className={`asset-status-badge kl-index-badge ${asset.indexStatus ? `kl-index-${asset.indexStatus}` : ""}`}
              >
                {asset.indexStatus
                  ? (indexStatusLabel[asset.indexStatus] ?? asset.indexStatus)
                  : "—"}
              </span>
            </div>
          </div>
          <div className="lifecycle-status-card">
            <div className="lifecycle-status-label">解析状态</div>
            <div className="lifecycle-status-value">{asset.parseStatus ?? "—"}</div>
          </div>
          <div className="lifecycle-status-card">
            <div className="lifecycle-status-label">最近索引时间</div>
            <div className="lifecycle-status-value">
              {asset.indexedAt ? formatBeijingTime(asset.indexedAt) : "—"}
            </div>
          </div>
        </div>
        {asset.indexStatus === "index_failed" && (
          <div
            className="lifecycle-status-hint"
            style={{ color: "var(--color-warning-fg, #8a6d00)" }}
          >
            {asset.indexErrorMessage ??
              "检索索引失败：资产已保留，但暂不会被语义检索召回，可重试。"}
          </div>
        )}
        {asset.indexStatus === "skipped" && (
          <div className="lifecycle-status-hint">
            检索索引暂未启用，已跳过索引；该资产暂不会被语义检索召回。
          </div>
        )}
        {asset.access.canRetryIndex && (
          <div className="lifecycle-action-row" style={{ marginTop: 10 }}>
            <button
              className="btn-small btn-small-primary"
              onClick={handleRetryIndex}
              disabled={retryBusy}
            >
              {retryBusy ? "重试中…" : "重试索引"}
            </button>
          </div>
        )}
        {retryNote && <div className="lifecycle-action-msg">{retryNote}</div>}
        {retryErr && <div className="lifecycle-action-err">{retryErr}</div>}
      </section>

      {/* 原文预览：有 original 权限时可申请受控预览凭证 */}
      <section className="detail-section">
        <h3>原文预览</h3>
        <div className="doc-preview-panel">
          <div className="doc-preview-policy-hint">
            {canOriginal
              ? `当前身份具备原文层权限${asset.access.effectiveSource === "access_grant" ? "（经原文访问授权）" : ""}，可申请短期受控预览凭证（默认 30 分钟）。`
              : asset.access.existingRequestStatus === "pending"
                ? "你已提交原文访问申请，待项目经理 / 治理角色审批。"
                : asset.access.canRequestOriginal
                  ? "当前身份无原文层权限，可发起原文访问申请，经审批授权后可预览 / 取原文。"
                  : "当前身份不可访问原文。"}
          </div>

          {canOriginal ? (
            <button
              className="btn-primary doc-preview-btn"
              onClick={handleRequestPreview}
              disabled={previewLoading}
            >
              {previewLoading ? "签发中…" : preview ? "重新申请预览" : "申请受控预览"}
            </button>
          ) : (
            <button className="btn-secondary doc-preview-btn" disabled>
              原文预览受限
            </button>
          )}

          {previewError && (
            <div className="doc-preview-note" style={{ color: "var(--color-danger-fg, #b00)" }}>
              {previewError}
            </div>
          )}

          {preview && (
            <div className="doc-preview-cred-area">
              <div className="doc-preview-cred-badge">
                受控预览凭证已签发（{preview.preview_type}）
              </div>
              <div className="doc-preview-cred-meta">
                凭证指纹：{preview.credential_fingerprint} · 有效期至：
                {formatBeijingTime(preview.expires_at)}（北京时间） · 状态：
                {preview.credential_status}
              </div>
              <a
                className="btn-secondary doc-preview-btn"
                href={previewEntryHref(preview.preview_entry_url)}
                target="_blank"
                rel="noreferrer"
              >
                打开受控预览
              </a>
              <div className="doc-preview-note">
                预览由平台权限网关签发凭证、只读打开（仅查看，禁编辑 / 下载 /
                打印），全程审计；未启用预览服务或该类型不支持时，不暴露原文地址。详细预览与凭证边界见{" "}
                <Link to="/help#knowledge" className="page-help-link">
                  使用说明 →
                </Link>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* 操作 */}
      <section className="detail-section">
        <div className="detail-actions-bar">
          {canOriginal ? (
            <button className="btn-secondary" disabled title="你已拥有原文层权限">
              已有原文权限
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
              {oaBusy ? "提交中…" : "申请原文权限"}
            </button>
          ) : (
            <button className="btn-secondary" disabled>
              原文不可访问
            </button>
          )}
          <button className="btn-secondary" disabled>
            推荐升级
          </button>
          <button className="btn-secondary" disabled>
            编辑可见性
          </button>
          <button className="btn-secondary" disabled>
            导出摘要
          </button>
        </div>
        {oaError && (
          <div className="doc-preview-note" style={{ color: "var(--color-danger-fg, #b00)" }}>
            {oaError}
          </div>
        )}
        {oaNote && (
          <div className="doc-preview-note" style={{ color: "var(--color-success-fg, #176)" }}>
            {oaNote}
          </div>
        )}
      </section>
    </div>
  );
}
