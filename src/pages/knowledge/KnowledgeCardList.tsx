import { Link } from "react-router-dom";
import {
  Search,
  AlertTriangle,
  FileSearch,
  CheckCircle2,
  KeyRound,
  Radar,
  Sparkles,
} from "lucide-react";
import type { KnowledgeCardVM, KnowledgeScope } from "../../types/knowledge";
import type { SearchResponseDTO } from "../../types/search";
import {
  accessLayerLabel,
  assetTypeLabel,
  intentLabel,
  spineByLevel,
  zoneLabel,
} from "../../utils/knowledgeLabels";
import { formatBeijingTime } from "../../utils/time";
import KnowledgeCard from "../../components/KnowledgeCard";

// 结果区：语义搜索模式（答案 + 引用 + 搜索卡）与浏览模式（KnowledgeCard 列表）的
// 全部三态渲染。从 KnowledgeListPage 抽取，结构与既有一致。
interface KnowledgeCardListProps {
  searchMode: boolean;
  // 搜索模式
  searchLoading: boolean;
  searchError: string | null;
  searchResult: SearchResponseDTO | null;
  runSearch: () => void;
  // 浏览模式
  loading: boolean;
  error: string | null;
  filtered: KnowledgeCardVM[];
  activeScope: KnowledgeScope;
  canCreateProject: boolean;
  openProjectForm: () => void;
  resetFilters: () => void;
  hasActiveFilters: boolean;
  // 浏览卡删除（两步内联确认）
  confirmDeleteId: string | null;
  deleteBusyId: string | null;
  onAskDelete: (id: string) => void;
  onCancelDelete: () => void;
  onConfirmDelete: (id: string) => void;
}

export default function KnowledgeCardList(props: KnowledgeCardListProps) {
  const {
    searchMode,
    searchLoading,
    searchError,
    searchResult,
    runSearch,
    loading,
    error,
    filtered,
    activeScope,
    canCreateProject,
    openProjectForm,
    resetFilters,
    hasActiveFilters,
    confirmDeleteId,
    deleteBusyId,
    onAskDelete,
    onCancelDelete,
    onConfirmDelete,
  } = props;

  const cards = searchResult?.cards ?? [];
  const citations = searchResult?.citations ?? [];

  if (searchMode) {
    if (searchLoading) {
      return (
        <div className="kb-state">
          <div className="kb-state-icon">
            <Search size={20} />
          </div>
          <div className="kb-state-title">检索中…</div>
        </div>
      );
    }
    if (searchError) {
      return (
        <div className="kb-state">
          <div className="kb-state-icon is-error">
            <AlertTriangle size={20} />
          </div>
          <div className="kb-state-title">检索失败</div>
          <p className="kb-state-desc">{searchError}</p>
          <button className="btn-secondary" onClick={runSearch}>
            重试
          </button>
        </div>
      );
    }
    return (
      <>
        {searchResult?.answer && (
          <div className="kb-answer">
            <div className="kb-answer-head">
              <Sparkles size={13} />
              <span className="kb-intent">
                {intentLabel[searchResult.intent] ?? searchResult.intent}
              </span>
              <span>AI 答案 / 检索摘要</span>
            </div>
            <p className="kb-answer-text">{searchResult.answer}</p>
            {citations.length > 0 && (
              <div className="kb-citations">
                <div className="kb-citations-title">引用来源</div>
                <ul className="kb-citation-list">
                  {citations.map((c) => (
                    <li key={c.citation_order}>
                      <Link to={`/knowledge/${c.asset_id}`} className="kb-citation-title">
                        [{c.citation_order}] {c.asset_title}
                      </Link>
                      <span className="kb-citation-meta">
                        {accessLayerLabel[c.used_access_layer] ?? c.used_access_layer} ·{" "}
                        {zoneLabel(c.cited_zone)}
                      </span>
                      {c.snippet && <p className="kb-citation-snippet">{c.snippet}</p>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {cards.length > 0 ? (
          <div className="kb-list">
            {cards.map((card) => (
              <article key={card.asset_id} className="dossier">
                <div className={`dossier-spine ${spineByLevel(card.confidentiality_level)}`} />
                <div className="dossier-body">
                  <div className="dossier-head">
                    <Link to={`/knowledge/${card.asset_id}`} className="dossier-title">
                      {card.title}
                    </Link>
                    <div className="dossier-badges">
                      <span className="dchip dchip-type">
                        {assetTypeLabel[card.asset_type] ?? card.asset_type}
                      </span>
                      <span className="dchip dchip-conf">{card.confidentiality_level}</span>
                      <span className="dchip dchip-zone">{zoneLabel(card.zone)}</span>
                    </div>
                  </div>
                  <p className="dossier-summary">
                    {card.one_liner || card.detailed || "（无摘要权限）"}
                  </p>
                  <div className="dossier-tags">
                    {card.tags.map((t) => (
                      <span key={t} className="tag">
                        {t}
                      </span>
                    ))}
                  </div>
                  <div className="dossier-meta">
                    {card.project_name && <span>{card.project_name}</span>}
                    {card.phase && <span>{card.phase}</span>}
                    <span className="u-num">相关度 {card.relevance_score.toFixed(2)}</span>
                    {card.updated_at && <span>{formatBeijingTime(card.updated_at)}</span>}
                  </div>
                  <div className="dossier-orig">
                    {card.can_view_original ? (
                      <span className="ok">
                        <CheckCircle2 size={13} /> 可访问原文（经授权 / 项目权限）
                      </span>
                    ) : (
                      <Link to={`/knowledge/${card.asset_id}`} className="need">
                        <KeyRound size={13} /> 摘要层结果 · 原文需申请
                      </Link>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="kb-state">
            <div className="kb-state-icon">
              <FileSearch size={20} />
            </div>
            <div className="kb-state-title">未检索到相关知识资产</div>
            <p className="kb-state-desc">
              换个问法或关键词，切换知识库范围，或调整业务阶段过滤后重试。无结果也可能是你对相关知识没有发现权限。
            </p>
          </div>
        )}

        {searchResult?.trace_id && (
          <div className="kb-trace">检索追踪 ID：{searchResult.trace_id}</div>
        )}
      </>
    );
  }

  // ════════ 浏览模式列表 ════════
  if (loading) {
    return (
      <div className="kb-state">
        <div className="kb-state-icon">
          <Radar size={20} />
        </div>
        <div className="kb-state-title">加载中…</div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="kb-state">
        <div className="kb-state-icon is-error">
          <AlertTriangle size={20} />
        </div>
        <div className="kb-state-title">加载失败</div>
        <p className="kb-state-desc">{error}（请确认后端服务已启动）</p>
      </div>
    );
  }
  if (filtered.length > 0) {
    return (
      <div className="kb-list">
        {filtered.map((asset) => (
          <KnowledgeCard
            key={asset.id}
            asset={asset}
            confirmDeleteId={confirmDeleteId}
            deleteBusyId={deleteBusyId}
            onAskDelete={onAskDelete}
            onCancelDelete={onCancelDelete}
            onConfirmDelete={onConfirmDelete}
          />
        ))}
      </div>
    );
  }
  return (
    <div className="kb-state">
      <div className="kb-state-icon">
        <FileSearch size={20} />
      </div>
      <div className="kb-state-title">
        {activeScope === "project" ? "该范围暂无项目知识资产" : "未找到匹配的知识资产"}
      </div>
      <p className="kb-state-desc">
        当前筛选条件下没有结果。尝试切换知识库范围或清除筛选条件，或在上方输入问题进行语义检索。
      </p>
      {activeScope === "project" && canCreateProject && (
        <button className="btn-secondary" onClick={openProjectForm}>
          新建项目知识库
        </button>
      )}
      {hasActiveFilters && (
        <button className="btn-secondary" onClick={resetFilters}>
          清除所有筛选
        </button>
      )}
    </div>
  );
}
