import {
  BriefcaseBusiness,
  Building2,
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  Search,
  SlidersHorizontal,
  Upload,
  UserRound,
} from "lucide-react";
import { Link } from "react-router-dom";
import { can } from "../auth/permissions";
import AccessExplanationDrawer from "../components/AccessExplanationDrawer";
import { ActionGroup } from "../components/ActionLayout";
import Button from "../components/Button";
import CreateKnowledgeDirectoryButton from "../components/CreateKnowledgeDirectoryButton";
import DataTable from "../components/DataTable";
import DetailDrawer from "../components/DetailDrawer";
import KnowledgeMetadataEditor from "../components/KnowledgeMetadataEditor";
import LoadingError from "../components/LoadingError";
import ModuleNavigation from "../components/ModuleNavigation";
import PagePagination from "../components/PagePagination";
import {
  EmptyState,
  FilterBar,
  PageHeader,
  PageSection,
  ProductPage,
} from "../components/ProductLayout";
import TaskModal from "../components/TaskModal";
import { summaryPendingLabel } from "../components/knowledgeSummaryState";
import type { AssetStatus, ConfidentialityLevel } from "../types/knowledge";
import { assetStatusLabel, scopeLabels } from "../utils/knowledgeLabels";
import "./KnowledgeListPage.css";
import {
  ASSET_STATUSES,
  CONFIDENTIALITY_LEVELS,
  confidentialityLabels,
} from "./controllers/KnowledgeList/model";
import { useKnowledgeList } from "./controllers/KnowledgeList/useKnowledgeList";

export default function KnowledgeListPage() {
  const {
    status,
    capabilities,
    showGlobalSearch,
    selectScope,
    scope,
    mobileDirectoryOpen,
    setMobileDirectoryOpen,
    directoryError,
    projectCatalogError,
    validProjectId,
    selectProject,
    availableProjects,
    directory,
    setProjectCatalogRetry,
    projectCatalogLoaded,
    directoryLoading,
    setDirectoryRetryKey,
    visibleDirectoryItems,
    selectDirectory,
    childDirectoryItems,
    authMe,
    selectedProject,
    directoryAncestors,
    contentSearch,
    hasLoaded,
    loading,
    error,
    result,
    globalSearchMode,
    setContentSearch,
    runSemanticSearch,
    semanticQuery,
    setSemanticQuery,
    semanticBusy,
    includeArchived,
    setIncludeArchived,
    semanticError,
    semanticResult,
    detailState,
    submitKeyword,
    keywordInput,
    setKeywordInput,
    keyword,
    clearKeyword,
    mobileFiltersOpen,
    setMobileFiltersOpen,
    advancedFilterCount,
    assetStatus,
    setAssetStatus,
    setPage,
    confidentialityLevel,
    setConfidentialityLevel,
    hasActiveFilters,
    resetFilters,
    requestNote,
    setRetryKey,
    tableOverflow,
    tableAtEnd,
    tableShellRef,
    topScrollerRef,
    tableScrollWidth,
    columns,
    initialLoading,
    totalPages,
    firstItem,
    lastItem,
    summaryAssetId,
    summaryDetail,
    requestBusy,
    closeDetail,
    setRequestAsset,
    setRequestReason,
    summaryLoading,
    summaryError,
    setExplainAsset,
    explainAsset,
    setRequestError,
    requestAsset,
    submitOriginalRequest,
    requestReason,
    requestError,
  } = useKnowledgeList();

  return (
    <ProductPage className="kbl-page">
      {status !== "loading" && !capabilities.isBusinessUser ? (
        <PageSection>
          <LoadingError
            forbidden
            forbiddenTitle="当前身份不浏览业务知识"
            forbiddenDesc="系统管理身份仅使用运营管理入口，不显示任何业务知识资产或资产数量。"
          />
        </PageSection>
      ) : (
        <>
          <div className={`kbl-workspace${showGlobalSearch ? " is-global-search" : ""}`}>
            <aside className="kbl-navigation" aria-label="资料范围与目录">
              <ModuleNavigation embedded />
              <nav className="kbl-library-nav" aria-label="资料范围">
                <button
                  type="button"
                  aria-current={showGlobalSearch ? "page" : undefined}
                  onClick={() => selectScope("")}
                >
                  <Search size={17} aria-hidden="true" /> 全库搜索
                </button>
                <button
                  type="button"
                  aria-current={scope === "company" ? "page" : undefined}
                  onClick={() => selectScope("company")}
                >
                  <Building2 size={17} aria-hidden="true" /> 公司库
                </button>
                <button
                  type="button"
                  aria-current={scope === "project" ? "page" : undefined}
                  onClick={() => selectScope("project")}
                >
                  <BriefcaseBusiness size={17} aria-hidden="true" /> 项目库
                </button>
                <button
                  type="button"
                  aria-current={scope === "personal" ? "page" : undefined}
                  onClick={() => selectScope("personal")}
                >
                  <UserRound size={17} aria-hidden="true" /> 个人库
                </button>
              </nav>

              {scope && (
                <button
                  type="button"
                  className="kbl-mobile-directory-toggle"
                  aria-expanded={mobileDirectoryOpen}
                  aria-controls="knowledge-directory-navigation"
                  onClick={() => setMobileDirectoryOpen((value) => !value)}
                >
                  <Folder size={16} aria-hidden="true" />
                  <span>
                    {mobileDirectoryOpen
                      ? "收起目录"
                      : scope === "project"
                        ? "选择项目与目录"
                        : "选择目录"}
                  </span>
                  {(directoryError || (scope === "project" && projectCatalogError)) && (
                    <small>加载失败，请重试</small>
                  )}
                  <ChevronRight size={16} aria-hidden="true" />
                </button>
              )}
              {scope ? (
                <div
                  id="knowledge-directory-navigation"
                  className={`kbl-directory-navigation${mobileDirectoryOpen ? " is-mobile-open" : ""}`}
                >
                  {scope === "project" && (
                    <label className="kbl-project-picker">
                      <span>当前项目</span>
                      <select
                        aria-label="项目"
                        value={validProjectId}
                        onChange={(event) => selectProject(event.target.value)}
                      >
                        <option value="">请选择项目</option>
                        {availableProjects.map((project) => (
                          <option key={project.projectId} value={project.projectId}>
                            {project.projectName} · {project.accessLabel}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <div className="kbl-directory-heading">
                    <h3>{scope === "project" && !validProjectId ? "可见项目" : "目录"}</h3>
                    {directory?.parent_key && (
                      <Link
                        to={`/knowledge?scope=${directory.scope}&directory_key=${encodeURIComponent(directory.parent_key)}${directory.project_id ? `&project_id=${encodeURIComponent(directory.project_id)}` : ""}`}
                      >
                        返回上级分类
                      </Link>
                    )}
                  </div>
                  {scope === "project" && projectCatalogError ? (
                    <div className="kbl-navigation-note" role="alert">
                      <p>项目列表暂时无法加载，当前路径已保留。</p>
                      <Button
                        size="small"
                        onClick={() => setProjectCatalogRetry((value) => value + 1)}
                      >
                        重新加载项目
                      </Button>
                    </div>
                  ) : scope === "project" && !projectCatalogLoaded ? (
                    <p className="kbl-navigation-note" role="status">
                      正在读取可进入的项目…
                    </p>
                  ) : directoryLoading ? (
                    <p className="kbl-navigation-note" role="status">
                      正在读取可进入的目录…
                    </p>
                  ) : directoryError ? (
                    <div className="kbl-navigation-note" role="alert">
                      <p>目录暂时无法加载，请重试。</p>
                      <Button
                        size="small"
                        onClick={() => setDirectoryRetryKey((value) => value + 1)}
                      >
                        重新加载目录
                      </Button>
                    </div>
                  ) : scope === "project" && !validProjectId ? (
                    <div className="kbl-project-list">
                      {availableProjects.map((project) => (
                        <button
                          type="button"
                          key={project.projectId}
                          onClick={() => selectProject(project.projectId)}
                        >
                          <strong>{project.projectName}</strong>
                          <span>{project.accessLabel}</span>
                        </button>
                      ))}
                      {projectCatalogLoaded && availableProjects.length === 0 && (
                        <p className="kbl-navigation-note">暂无可进入的项目。</p>
                      )}
                    </div>
                  ) : (
                    <nav className="kbl-directory-tree" aria-label="知识目录">
                      {visibleDirectoryItems.map((item) => (
                        <div key={`${item.directory_key}-${item.project_id ?? "global"}`}>
                          <button
                            type="button"
                            aria-current={
                              directory?.directory_key === item.directory_key ? "page" : undefined
                            }
                            onClick={() => selectDirectory(item)}
                            title={item.display_path}
                          >
                            <Folder size={16} aria-hidden="true" />
                            <span>{item.name}</span>
                          </button>
                          {(directory?.directory_key === item.directory_key ||
                            directory?.parent_key === item.directory_key) &&
                            childDirectoryItems.length > 0 && (
                              <div className="kbl-child-directories">
                                {childDirectoryItems.map((child) => (
                                  <button
                                    type="button"
                                    key={child.directory_key}
                                    aria-current={
                                      directory?.directory_key === child.directory_key
                                        ? "page"
                                        : undefined
                                    }
                                    onClick={() => selectDirectory(child)}
                                    title={child.display_path}
                                  >
                                    <Folder size={15} aria-hidden="true" />
                                    <span>{child.name}</span>
                                  </button>
                                ))}
                              </div>
                            )}
                        </div>
                      ))}
                      {visibleDirectoryItems.length === 0 && (
                        <p className="kbl-navigation-note">当前范围暂无可进入的目录。</p>
                      )}
                    </nav>
                  )}
                </div>
              ) : (
                <p className="kbl-navigation-note">
                  选择资料库可按目录浏览。全库搜索只返回当前身份有权发现的资料。
                </p>
              )}
            </aside>
            <div className="kbl-results-workspace">
              <PageHeader
                title="知识资产库"
                description="汇集公司、项目与个人知识，让经验更容易找到和复用。"
                actions={
                  <ActionGroup label="知识库操作" className="knowledge-directory-create-actions">
                    {scope === "company" && capabilities.isGovernance && (
                      <CreateKnowledgeDirectoryButton
                        scope="company"
                        initialParent={directory?.parent_key ?? directory?.directory_key}
                      />
                    )}
                    {scope === "project" &&
                      validProjectId &&
                      authMe?.projects.some(
                        (project) =>
                          project.projectId === validProjectId &&
                          project.projectRole === "project_manager",
                      ) && (
                        <CreateKnowledgeDirectoryButton
                          scope="project"
                          projectId={validProjectId}
                          initialParent={directory?.parent_key ?? directory?.directory_key}
                        />
                      )}
                    {can.viewUpload(capabilities) ? (
                      <Link
                        className="product-button is-primary"
                        to={
                          validProjectId
                            ? `/upload?project_id=${encodeURIComponent(validProjectId)}`
                            : "/upload"
                        }
                      >
                        <Upload size={16} aria-hidden="true" />
                        上传资产
                      </Link>
                    ) : null}
                  </ActionGroup>
                }
              />
              <nav className="kbl-breadcrumbs" aria-label="知识资产目录路径">
                <button type="button" onClick={() => selectScope("")}>
                  知识资产库
                </button>
                <ChevronRight size={14} aria-hidden="true" />
                {scope ? (
                  <button
                    type="button"
                    onClick={() => selectScope(scope)}
                    aria-current={!selectedProject && !directory ? "page" : undefined}
                  >
                    {scope === "company" ? "公司库" : scope === "project" ? "项目库" : "个人库"}
                  </button>
                ) : (
                  <span aria-current="page">全库搜索</span>
                )}
                {selectedProject && (
                  <>
                    <ChevronRight size={14} aria-hidden="true" />
                    <button
                      type="button"
                      onClick={() => selectProject(selectedProject.projectId)}
                      aria-current={!directory ? "page" : undefined}
                    >
                      {selectedProject.projectName}
                    </button>
                  </>
                )}
                {directoryAncestors.map((ancestor) => (
                  <span className="kbl-breadcrumb-segment" key={ancestor.directory_key}>
                    <ChevronRight size={14} aria-hidden="true" />
                    <button type="button" onClick={() => selectDirectory(ancestor)}>
                      {ancestor.name}
                    </button>
                  </span>
                ))}
                {directory && (
                  <>
                    <ChevronRight size={14} aria-hidden="true" />
                    <span aria-current="page">{directory.name}</span>
                  </>
                )}
              </nav>
              {!showGlobalSearch && (
                <div className="kbl-content-heading">
                  <div className="kbl-content-title">
                    <span className="kbl-folder-mark" aria-hidden="true">
                      {showGlobalSearch ? <Search size={24} /> : <FolderOpen size={24} />}
                    </span>
                    <div>
                      <h2>
                        {directory?.name ??
                          (showGlobalSearch
                            ? "查找知识与经验"
                            : (selectedProject?.projectName ??
                              (scope === "company"
                                ? "公司知识"
                                : scope === "personal"
                                  ? "个人知识"
                                  : "项目知识")))}
                      </h2>
                      <p>
                        {directory
                          ? "在当前目录查找资料，点击标题快速查看摘要。"
                          : showGlobalSearch
                            ? "从有权访问的正文与摘要中查找所需内容。"
                            : "选择分类，进入对应的资料目录。"}
                      </p>
                    </div>
                  </div>
                  {directory && !contentSearch && hasLoaded && !loading && !error && (
                    <span className="kbl-result-count">{result.total} 份资料</span>
                  )}
                </div>
              )}
              {scope && !directory && !globalSearchMode && (
                <section className="kbl-directory-landing" aria-label="浏览资料目录">
                  {scope === "project" && projectCatalogError ? (
                    <EmptyState
                      title="项目列表暂时无法加载"
                      description="请在目录导航中重新加载项目，或选择其他资料库。"
                    />
                  ) : scope === "project" && !projectCatalogLoaded ? (
                    <p role="status">正在读取可进入的项目…</p>
                  ) : directoryLoading ? (
                    <p role="status">正在加载目录…</p>
                  ) : directoryError ? (
                    <LoadingError
                      error="目录暂时无法加载，请重试。"
                      onRetry={() => setDirectoryRetryKey((value) => value + 1)}
                    />
                  ) : scope === "project" && !validProjectId ? (
                    <div className="kbl-directory-cards">
                      {availableProjects.map((project) => (
                        <Link
                          key={project.projectId}
                          to={`/knowledge?scope=project&project_id=${encodeURIComponent(project.projectId)}`}
                          aria-label={`进入项目 ${project.projectName}`}
                        >
                          <BriefcaseBusiness size={25} aria-hidden="true" />
                          <span>
                            <strong>{project.projectName}</strong>
                            <small>{project.accessLabel}</small>
                          </span>
                          <ChevronRight size={16} aria-hidden="true" />
                        </Link>
                      ))}
                      {projectCatalogLoaded && availableProjects.length === 0 && (
                        <EmptyState
                          title="暂无可进入的项目"
                          description="加入项目后，可在这里查看项目资料。"
                        />
                      )}
                    </div>
                  ) : visibleDirectoryItems.length ? (
                    <div className="kbl-directory-cards">
                      {visibleDirectoryItems.map((item) => (
                        <Link
                          key={`${item.directory_key}-${item.project_id ?? "global"}`}
                          to={`/knowledge?scope=${item.scope}&directory_key=${encodeURIComponent(item.directory_key)}${item.project_id ? `&project_id=${encodeURIComponent(item.project_id)}` : ""}`}
                          aria-label={`进入目录 ${item.name}`}
                        >
                          <Folder size={26} aria-hidden="true" />
                          <span>
                            <strong>{item.name}</strong>
                            <small>浏览目录资料</small>
                          </span>
                          <ChevronRight size={16} aria-hidden="true" />
                        </Link>
                      ))}
                    </div>
                  ) : (
                    <EmptyState
                      title="暂无可进入的目录"
                      description="可切换资料库，或使用全库搜索查找可见资料。"
                    />
                  )}
                </section>
              )}
              <div className="kbl-query-tools">
                {directory && (
                  <div className="kbl-search-mode" role="group" aria-label="检索方式">
                    <button
                      type="button"
                      aria-pressed={!contentSearch}
                      onClick={() => setContentSearch(false)}
                    >
                      标题与标签
                    </button>
                    <button
                      type="button"
                      aria-pressed={contentSearch}
                      onClick={() => setContentSearch(true)}
                    >
                      正文与摘要
                    </button>
                  </div>
                )}
                {((directory && contentSearch) || showGlobalSearch) && (
                  <PageSection className="kbl-semantic-section">
                    <div className="kbl-semantic-heading">
                      <div>
                        <h2>{showGlobalSearch ? "全库搜索" : "正文与摘要检索"}</h2>
                        <p>
                          {showGlobalSearch
                            ? "搜索当前身份可见的正文与摘要；跨项目原文仍需逐项申请。"
                            : "仅检索当前目录内可访问的正文与摘要；内容检索使用目录范围和归档选项，不应用列表的其他筛选。"}
                        </p>
                      </div>
                    </div>
                    <form
                      onSubmit={(event) => {
                        event.preventDefault();
                        void runSemanticSearch();
                      }}
                      className="kbl-semantic-form"
                    >
                      <label htmlFor="semantic-query">正文关键词或内容描述</label>
                      <div>
                        <input
                          id="semantic-query"
                          value={semanticQuery}
                          onChange={(event) => setSemanticQuery(event.target.value)}
                          placeholder="输入正文编号、关键词或内容描述"
                        />
                        <Button
                          variant="primary"
                          type="submit"
                          disabled={semanticBusy || !semanticQuery.trim()}
                        >
                          {semanticBusy ? "检索中…" : "检索内容"}
                        </Button>
                      </div>
                      <label className="kbl-archive-toggle">
                        <input
                          type="checkbox"
                          checked={includeArchived}
                          onChange={(event) => setIncludeArchived(event.target.checked)}
                        />
                        <span>包含归档</span>
                      </label>
                    </form>
                    {semanticError && (
                      <div role="alert" className="kbl-drawer-message is-error">
                        {semanticError}{" "}
                        <button type="button" onClick={() => void runSemanticSearch()}>
                          重试
                        </button>
                      </div>
                    )}
                    {semanticResult &&
                      (semanticResult.cards.length || semanticResult.answer ? (
                        <div className="kbl-semantic-results">
                          {semanticResult.answer && (
                            <article className="kbl-semantic-answer">
                              <span>安全回答</span>
                              <p>{semanticResult.answer}</p>
                            </article>
                          )}
                          {semanticResult.cards.map((card) => (
                            <article key={card.asset_id}>
                              <h3>
                                <Link
                                  to={`/knowledge/${encodeURIComponent(card.asset_id)}`}
                                  state={detailState}
                                >
                                  {card.title}
                                </Link>
                              </h3>
                              <p>{card.one_liner || card.detailed || "暂无可展示的安全摘要"}</p>
                              <span>相关度 {Math.round(card.relevance_score * 100)}%</span>
                            </article>
                          ))}
                          {semanticResult.citations.length > 0 && (
                            <section className="kbl-semantic-citations" aria-label="安全引用">
                              <h3>引用</h3>
                              <ol>
                                {semanticResult.citations.map((citation) => (
                                  <li key={`${citation.asset_id}-${citation.citation_order}`}>
                                    <strong>{citation.asset_title}</strong>
                                    {citation.snippet && <p>{citation.snippet}</p>}
                                    <small>
                                      {citation.used_access_layer === "original"
                                        ? "授权原文证据"
                                        : "安全摘要证据"}
                                    </small>
                                  </li>
                                ))}
                              </ol>
                            </section>
                          )}
                        </div>
                      ) : (
                        <EmptyState
                          title="当前检索没有匹配结果"
                          description="这只表示当前身份和检索范围内没有可返回结果，不代表系统中不存在相关资料。"
                        />
                      ))}
                  </PageSection>
                )}
                {directory && !contentSearch && (
                  <form className="kbl-filter-form" onSubmit={submitKeyword}>
                    <FilterBar ariaLabel="知识资产筛选">
                      <div className="kbl-filter-search-row">
                        <div className="kbl-keyword-field">
                          <Search size={16} aria-hidden="true" />
                          <label className="sr-only" htmlFor="knowledge-keyword">
                            关键词
                          </label>
                          <input
                            id="knowledge-keyword"
                            value={keywordInput}
                            onChange={(event) => setKeywordInput(event.target.value)}
                            placeholder="按标题或标签搜索"
                          />
                        </div>
                        <button className="product-button is-primary is-small" type="submit">
                          搜索
                        </button>
                        {(keywordInput || keyword) && (
                          <button
                            className="product-button is-secondary is-small"
                            type="button"
                            onClick={clearKeyword}
                          >
                            清除
                          </button>
                        )}
                        <button
                          className="product-button is-secondary is-small kbl-mobile-filter-toggle"
                          type="button"
                          aria-expanded={mobileFiltersOpen}
                          aria-controls="knowledge-advanced-filters"
                          onClick={() => setMobileFiltersOpen((value) => !value)}
                        >
                          <SlidersHorizontal size={15} aria-hidden="true" /> 筛选
                          {advancedFilterCount ? ` (${advancedFilterCount})` : ""}
                        </button>
                      </div>
                      <div
                        id="knowledge-advanced-filters"
                        className={`kbl-advanced-filters${mobileFiltersOpen ? " is-mobile-open" : ""}`}
                      >
                        <label className="kbl-select-field">
                          <span className="sr-only">资产状态</span>
                          <select
                            aria-label="资产状态"
                            value={assetStatus}
                            onChange={(event) => {
                              setAssetStatus(event.target.value as AssetStatus | "");
                              setPage(1);
                            }}
                          >
                            <option value="">状态：全部</option>
                            {ASSET_STATUSES.map((value) => (
                              <option key={value} value={value}>
                                状态：{assetStatusLabel[value]}
                              </option>
                            ))}
                          </select>
                        </label>

                        <label className="kbl-select-field">
                          <span className="sr-only">保密等级</span>
                          <select
                            aria-label="保密等级"
                            value={confidentialityLevel}
                            onChange={(event) => {
                              setConfidentialityLevel(
                                event.target.value as ConfidentialityLevel | "",
                              );
                              setPage(1);
                            }}
                          >
                            <option value="">保密：全部</option>
                            {CONFIDENTIALITY_LEVELS.map((value) => (
                              <option key={value} value={value}>
                                保密：{value}
                              </option>
                            ))}
                          </select>
                        </label>

                        <label className="kbl-archive-toggle">
                          <input
                            type="checkbox"
                            checked={includeArchived}
                            onChange={(event) => {
                              setIncludeArchived(event.target.checked);
                              setPage(1);
                            }}
                          />
                          <span>包含归档</span>
                        </label>
                        <button
                          className="product-button is-ghost is-small"
                          type="button"
                          disabled={!hasActiveFilters}
                          onClick={resetFilters}
                        >
                          重置
                        </button>
                      </div>
                    </FilterBar>
                  </form>
                )}
              </div>

              {requestNote && (
                <div className="kbl-request-feedback" role="status">
                  <span>{requestNote}</span>
                  <Link to="/original-access?box=mine">查看申请进度</Link>
                </div>
              )}

              {directory && !contentSearch && (
                <PageSection className="kbl-list-section">
                  <div className="kbl-scope-summary" aria-label="当前生效范围与筛选">
                    <strong>当前浏览范围</strong>
                    <span>{scope ? scopeLabels[scope] : "全部可见范围"}</span>
                    {validProjectId && (
                      <span>
                        {
                          availableProjects.find((item) => item.projectId === validProjectId)
                            ?.projectName
                        }
                      </span>
                    )}
                    {keyword && <span>关键词：{keyword}</span>}
                    {assetStatus && <span>状态：{assetStatusLabel[assetStatus]}</span>}
                    {confidentialityLevel && <span>保密：{confidentialityLevel}</span>}
                    {includeArchived && <span>包含归档</span>}
                    {!hasActiveFilters && <small>未添加额外筛选</small>}
                  </div>
                  {error ? (
                    <LoadingError
                      error={error}
                      errorTitle="知识资产加载失败"
                      onRetry={() => setRetryKey((value) => value + 1)}
                    />
                  ) : (
                    <>
                      <div className="kbl-table-status" role="status" aria-live="polite">
                        {loading && hasLoaded ? "正在更新列表…" : ""}
                      </div>
                      <div
                        className={`kbl-table-shell ${tableOverflow && !tableAtEnd ? "has-more" : ""}`}
                        ref={tableShellRef}
                      >
                        {tableOverflow && (
                          <div className="kbl-scroll-guide">
                            <span>向右滚动查看更多列</span>
                            <div
                              className="kbl-top-scroll"
                              ref={topScrollerRef}
                              aria-label="知识资产表横向滚动"
                              tabIndex={0}
                              onScroll={(event) => {
                                const tableWrap =
                                  tableShellRef.current?.querySelector<HTMLElement>(
                                    ".kbl-table-wrap",
                                  );
                                if (tableWrap)
                                  tableWrap.scrollLeft = event.currentTarget.scrollLeft;
                              }}
                            >
                              <div style={{ width: tableScrollWidth }} />
                            </div>
                          </div>
                        )}
                        <DataTable
                          columns={columns}
                          rows={result.items}
                          rowKey={(asset) => asset.id}
                          loading={initialLoading}
                          loadingText="正在加载知识资产…"
                          emptyText={
                            <EmptyState
                              title={hasActiveFilters ? "当前条件没有匹配资料" : "暂无可复用资料"}
                              description={
                                hasActiveFilters
                                  ? "仅表示当前可见范围内没有匹配项；不会确认不可见资料是否存在。"
                                  : "部分资料可能因项目或保密权限不在当前可见范围内。"
                              }
                              action={
                                hasActiveFilters ? (
                                  <button
                                    className="product-button is-secondary is-small"
                                    type="button"
                                    onClick={resetFilters}
                                  >
                                    清除筛选
                                  </button>
                                ) : undefined
                              }
                            />
                          }
                          wrapClassName={`product-table-wrap kbl-table-wrap ${loading ? "is-updating" : ""}`}
                          tableClassName="product-data-table kbl-table"
                          ariaLabel="知识资产列表"
                        />
                      </div>

                      {hasLoaded && result.total > 0 && (
                        <PagePagination
                          className="kbl-pagination"
                          ariaLabel="知识资产分页"
                          page={result.page}
                          totalPages={totalPages}
                          hasNext={result.hasNext}
                          disabled={loading}
                          onPageChange={setPage}
                          summary={
                            <>
                              显示 {firstItem}-{lastItem} 条，共 {result.total} 条
                            </>
                          }
                        />
                      )}
                    </>
                  )}
                </PageSection>
              )}
            </div>
          </div>
        </>
      )}

      <DetailDrawer
        open={summaryAssetId !== null}
        title={summaryDetail?.title ?? "知识详情"}
        description={
          summaryDetail?.access.crossProjectSummary
            ? "其他项目 · 摘要可见。此处不授予项目空间权限，也不展示原文或项目治理信息。"
            : "查看资料摘要与核心信息，关闭后继续浏览当前列表。"
        }
        busy={requestBusy}
        onClose={closeDetail}
        footer={
          summaryDetail ? (
            summaryDetail.access.original ? (
              <Link
                className="product-button is-primary"
                to={`/knowledge/${summaryDetail.id}`}
                state={detailState}
              >
                {summaryDetail.access.crossProjectSummary
                  ? "原文访问已开放，查看详情"
                  : "打开完整详情"}
              </Link>
            ) : summaryDetail.access.existingRequestStatus === "pending" ? (
              <Link className="product-button is-secondary" to="/original-access?box=mine">
                原文申请审批中
              </Link>
            ) : summaryDetail.access.canRequestOriginal ? (
              <button
                className="product-button is-primary"
                type="button"
                disabled={requestBusy}
                onClick={() => {
                  setRequestAsset(summaryDetail);
                  setRequestReason("");
                }}
              >
                {requestBusy ? "提交中…" : "申请原文"}
              </button>
            ) : undefined
          ) : undefined
        }
      >
        {summaryDetail && (
          <KnowledgeMetadataEditor
            key={summaryDetail.id}
            asset={summaryDetail}
            onSaved={() => {
              closeDetail();
              setRetryKey((value) => value + 1);
            }}
          />
        )}
        {summaryLoading ? (
          <p role="status">正在加载安全摘要…</p>
        ) : summaryError ? (
          <div className="kbl-drawer-message is-error" role="alert">
            {summaryError}
          </div>
        ) : summaryDetail ? (
          <div className="kbl-summary-drawer">
            <div className="kbl-summary-reading-heading">
              <FileText size={18} aria-hidden="true" />
              <h3>内容摘要</h3>
            </div>
            <div className="kbl-summary-drawer-meta">
              <span>
                {summaryDetail.scope === "project"
                  ? summaryDetail.projectName || "项目知识"
                  : summaryDetail.scope === "company"
                    ? "公司知识"
                    : "个人知识"}
              </span>
              <span>{confidentialityLabels[summaryDetail.confidentialityLevel]}</span>
            </div>
            {!summaryDetail.access.summary ? (
              <p>当前身份不可查看内容摘要。</p>
            ) : summaryDetail.detailed ||
              summaryDetail.oneLiner ||
              summaryDetail.keyPoints.length ? (
              <div>
                {(summaryDetail.detailed || summaryDetail.oneLiner) && (
                  <p>{summaryDetail.detailed || summaryDetail.oneLiner}</p>
                )}
                {summaryDetail.keyPoints.length > 0 && (
                  <ul>
                    {summaryDetail.keyPoints.map((point, index) => (
                      <li key={index}>{point}</li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <EmptyState
                title={summaryPendingLabel(summaryDetail)}
                description="摘要暂未就绪，不代表文件解析失败。原文访问仍按现有权限控制。"
              />
            )}
            <section className="kbl-summary-core" aria-labelledby="summary-core-title">
              <h3 id="summary-core-title">核心信息</h3>
              <dl>
                <div>
                  <dt>资料范围</dt>
                  <dd>
                    {summaryDetail.scope === "company"
                      ? "公司知识"
                      : summaryDetail.scope === "personal"
                        ? "个人知识"
                        : "项目知识"}
                  </dd>
                </div>
                {summaryDetail.scope === "project" && (
                  <div>
                    <dt>来源项目</dt>
                    <dd>{summaryDetail.projectName || "暂无"}</dd>
                  </div>
                )}
                <div>
                  <dt>正式目录</dt>
                  <dd>{summaryDetail.directoryPath || "待治理"}</dd>
                </div>
                <div>
                  <dt>保密等级</dt>
                  <dd>{confidentialityLabels[summaryDetail.confidentialityLevel]}</dd>
                </div>
                <div>
                  <dt>当前状态</dt>
                  <dd>{assetStatusLabel[summaryDetail.assetStatus] ?? "暂无"}</dd>
                </div>
                <div>
                  <dt>规范名版本</dt>
                  <dd>{summaryDetail.safeVersion || "暂无"}</dd>
                </div>
                <div>
                  <dt>更新时间</dt>
                  <dd>{summaryDetail.updatedAt || "暂无"}</dd>
                </div>
                <div>
                  <dt>问答 / 检索</dt>
                  <dd>
                    {summaryDetail.qaAvailable == null && summaryDetail.retrievalAvailable == null
                      ? "暂无"
                      : `${summaryDetail.qaAvailable ? "问答可用" : "问答不可用"} · ${summaryDetail.retrievalAvailable ? "检索可用" : "检索不可用"}`}
                    {(summaryDetail.qaAvailable === false ||
                      summaryDetail.retrievalAvailable === false) && (
                      <button
                        className="kbl-explain-link"
                        type="button"
                        onClick={() => setExplainAsset(summaryDetail)}
                      >
                        为什么？
                      </button>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>维护人</dt>
                  <dd>{summaryDetail.maintainerName || "暂无"}</dd>
                </div>
              </dl>
            </section>
            {summaryDetail.tags.length > 0 && (
              <div className="kbl-summary-drawer-tags" aria-label="知识标签">
                {summaryDetail.tags.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
            )}
          </div>
        ) : null}
      </DetailDrawer>
      <AccessExplanationDrawer
        open={explainAsset !== null}
        asset={explainAsset}
        capabilities={capabilities}
        onClose={() => setExplainAsset(null)}
        onRequest={() => {
          setRequestError(null);
          setRequestAsset(explainAsset);
          setExplainAsset(null);
        }}
      />
      <TaskModal
        open={requestAsset !== null}
        size="small"
        title="申请原文"
        description="申请当前资料的受控原文；提交前不会改变资料、授权或审批状态。"
        busy={requestBusy}
        onClose={() => {
          if (!requestBusy) {
            setRequestAsset(null);
            setRequestReason("");
            setRequestError(null);
          }
        }}
        footer={
          <>
            <button
              type="button"
              className="product-button is-secondary"
              disabled={requestBusy}
              onClick={() => {
                setRequestAsset(null);
                setRequestReason("");
                setRequestError(null);
              }}
            >
              取消
            </button>
            <button
              type="button"
              className="product-button is-primary"
              disabled={requestBusy}
              onClick={() => void submitOriginalRequest()}
            >
              {requestBusy ? "提交中…" : "提交申请"}
            </button>
          </>
        }
      >
        <label className="kbl-request-field">
          <span>申请理由（可选）</span>
          <textarea
            rows={4}
            value={requestReason}
            onChange={(event) => setRequestReason(event.target.value)}
            placeholder="说明需要使用原文的业务场景"
          />
        </label>
        {requestError && (
          <p className="kbl-request-error" role="alert">
            {requestError}
          </p>
        )}
      </TaskModal>
    </ProductPage>
  );
}
