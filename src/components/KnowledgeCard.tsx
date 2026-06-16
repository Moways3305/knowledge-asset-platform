import { Link } from "react-router-dom";
import { Trash2 } from "lucide-react";
import type { KnowledgeCardVM } from "../types/knowledge";
import {
  assetStatusLabel,
  assetTypeLabel,
  confidenceText,
  indexBadgeClass,
  indexStatusLabel,
  spineByVisibility,
  visibilityLabel,
} from "../utils/knowledgeLabels";
import { formatBeijingTime } from "../utils/time";

// 浏览模式知识卡（档案行 dossier）。从 KnowledgeListPage 浏览列表抽取，渲染结构与
// 既有完全一致。删除为两步内联确认，由父级用受控 props 驱动（不在卡内持有状态）。
interface KnowledgeCardProps {
  asset: KnowledgeCardVM;
  confirmDeleteId: string | null;
  deleteBusyId: string | null;
  onAskDelete: (id: string) => void;
  onCancelDelete: () => void;
  onConfirmDelete: (id: string) => void;
}

export default function KnowledgeCard({
  asset,
  confirmDeleteId,
  deleteBusyId,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: KnowledgeCardProps) {
  const idxCls = indexBadgeClass(asset.indexStatus);
  return (
    <article className={`dossier ${asset.assetStatus === "archived" ? "is-archived" : ""}`}>
      <div className={`dossier-spine ${spineByVisibility(asset.visibility)}`} />
      <div className="dossier-body">
        <div className="dossier-head">
          <Link to={`/knowledge/${asset.id}`} className="dossier-title">
            {asset.title}
          </Link>
          <div className="dossier-badges">
            <span className="dchip dchip-type">
              {assetTypeLabel[asset.assetType] ?? asset.assetType}
            </span>
            <span className={`dchip dchip-vis-${asset.visibility}`}>
              {visibilityLabel[asset.visibility]}
            </span>
            {asset.assetStatus !== "active" && (
              <span className="dchip dchip-status">{assetStatusLabel[asset.assetStatus]}</span>
            )}
          </div>
        </div>
        <p className="dossier-summary">
          {asset.summary || (asset.access.summary ? "" : "（无摘要权限）")}
        </p>
        <div className="dossier-tags">
          {asset.tags.map((t) => (
            <span key={t} className="tag">
              {t}
            </span>
          ))}
        </div>
        <div className="dossier-meta">
          {asset.projectName && <span>{asset.projectName}</span>}
          {asset.lifecyclePhase && <span>{asset.lifecyclePhase}</span>}
          {asset.confidence != null && (
            <span className="u-num">置信度 {confidenceText(asset.confidence)}</span>
          )}
          {asset.updatedAt && <span>{formatBeijingTime(asset.updatedAt)}</span>}
          {asset.indexStatus && asset.indexStatus !== "indexed" && (
            <span
              className={`dossier-index ${idxCls}`}
              title={asset.indexErrorMessage ?? "知识底座索引状态"}
            >
              {indexStatusLabel[asset.indexStatus] ?? asset.indexStatus}
            </span>
          )}
        </div>
        {asset.access.canDelete && asset.assetStatus !== "archived" && (
          <div className="dossier-actions">
            {confirmDeleteId === asset.id ? (
              <>
                <span className="dossier-warn">删除后退出检索 / 问答 / 预览，保留审计。确认？</span>
                <button
                  className="btn-small btn-small-danger"
                  disabled={deleteBusyId === asset.id}
                  onClick={() => onConfirmDelete(asset.id)}
                >
                  {deleteBusyId === asset.id ? "删除中…" : "确认删除"}
                </button>
                <button className="btn-small" onClick={onCancelDelete}>
                  取消
                </button>
              </>
            ) : (
              <button className="btn-small btn-small-danger" onClick={() => onAskDelete(asset.id)}>
                <Trash2 size={13} /> 删除 / 撤下
              </button>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
