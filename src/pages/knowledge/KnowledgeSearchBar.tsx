import { Search } from "lucide-react";
import type { FrontVisibility } from "../../types/knowledge";
import { assetTypeLabel, visibilityLabel } from "../../utils/knowledgeLabels";

// 检索栏 + 浏览筛选。committedQuery 非空进入语义搜索模式（searchMode）；
// 浏览筛选项（项目 / 类型 / 可见性）在搜索模式下仅作浏览用途、不驱动后端检索。
interface KnowledgeSearchBarProps {
  search: string;
  setSearch: (v: string) => void;
  runSearch: () => void;
  clearSearch: () => void;
  searchMode: boolean;
  filterProject: string;
  setFilterProject: (v: string) => void;
  filterBizStage: string;
  setFilterBizStage: (v: string) => void;
  filterAssetType: string;
  setFilterAssetType: (v: string) => void;
  filterVisibility: string;
  setFilterVisibility: (v: string) => void;
  projectOptions: string[];
  bizStageOptions: string[];
  assetTypeOptions: string[];
  visibilityOptions: FrontVisibility[];
  hasActiveFilters: boolean;
  resetFilters: () => void;
}

export default function KnowledgeSearchBar(props: KnowledgeSearchBarProps) {
  const {
    search,
    setSearch,
    runSearch,
    clearSearch,
    searchMode,
    filterProject,
    setFilterProject,
    filterBizStage,
    setFilterBizStage,
    filterAssetType,
    setFilterAssetType,
    filterVisibility,
    setFilterVisibility,
    projectOptions,
    bizStageOptions,
    assetTypeOptions,
    visibilityOptions,
    hasActiveFilters,
    resetFilters,
  } = props;

  return (
    <>
      <div className="kb-search">
        <div className="kb-search-field">
          <Search size={17} className="kb-search-icon" />
          <input
            type="text"
            placeholder="语义检索：输入问题或关键词，回车检索（WeKnora 召回 + 权限裁剪）"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") runSearch();
            }}
          />
        </div>
        <button className="btn-primary" onClick={runSearch} disabled={!search.trim()}>
          搜索
        </button>
        {searchMode && (
          <button className="btn-secondary" onClick={clearSearch}>
            返回浏览
          </button>
        )}
      </div>

      <div className="kb-filters">
        <div className="kb-filter">
          <label>项目{searchMode ? "（仅浏览）" : ""}</label>
          <select
            value={filterProject}
            disabled={searchMode}
            onChange={(e) => setFilterProject(e.target.value)}
          >
            <option value="">全部</option>
            {projectOptions.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </div>
        <div className="kb-filter">
          <label>业务阶段{searchMode ? "（检索过滤）" : ""}</label>
          <select value={filterBizStage} onChange={(e) => setFilterBizStage(e.target.value)}>
            <option value="">全部</option>
            {bizStageOptions.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </div>
        <div className="kb-filter">
          <label>资料类型{searchMode ? "（仅浏览）" : ""}</label>
          <select
            value={filterAssetType}
            disabled={searchMode}
            onChange={(e) => setFilterAssetType(e.target.value)}
          >
            <option value="">全部</option>
            {assetTypeOptions.map((o) => (
              <option key={o} value={o}>
                {assetTypeLabel[o] ?? o}
              </option>
            ))}
          </select>
        </div>
        <div className="kb-filter">
          <label>可见性{searchMode ? "（仅浏览）" : ""}</label>
          <select
            value={filterVisibility}
            disabled={searchMode}
            onChange={(e) => setFilterVisibility(e.target.value)}
          >
            <option value="">全部</option>
            {visibilityOptions.map((o) => (
              <option key={o} value={o}>
                {visibilityLabel[o]}
              </option>
            ))}
          </select>
        </div>
        {hasActiveFilters && !searchMode && (
          <button className="btn-reset-filter" onClick={resetFilters}>
            清除筛选
          </button>
        )}
      </div>
    </>
  );
}
