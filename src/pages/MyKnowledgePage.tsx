import {
  ClipboardCheck,
  Database,
  Eye,
  FileText,
  FolderUp,
  MoreHorizontal,
  Pencil,
  Search,
  SlidersHorizontal,
  Trash2,
  Upload,
} from "lucide-react";
import { Link } from "react-router-dom";
import { deleteKnowledgeAsset } from "../api/knowledge";
import {
  confirmPersonalAsset,
  previewPersonalKnowledgePublication,
  registerPersonalKnowledgeEvidence,
  submitPersonalKnowledge,
  updatePersonalKnowledge,
} from "../api/personal";
import { BulkSelectionRail, SelectionCheckbox } from "../components/BulkSelection";
import ConfirmDialog from "../components/ConfirmDialog";
import KnowledgeModuleFrame from "../components/KnowledgeModuleFrame";
import ModelAdvancedSettings from "../components/ModelAdvancedSettings";
import PagePagination from "../components/PagePagination";
import { PageHeader, PageSection, ProductPage } from "../components/ProductLayout";
import PublicationNamingFields, {
  createPublicationNamingValue,
} from "../components/PublicationNamingFields";
import type { PersonalKnowledgeState } from "../types/myKnowledge";
import { formatBeijingDate } from "../utils/time";
import "./MyKnowledgePage.css";
import {
  EvidenceType,
  PAGE_SIZE,
  SAFE_FALLBACK,
  evidenceCategories,
  evidenceCategoryLabels,
  isProjectLocked,
  kbStatus,
  stateConfig,
  typeConfig,
} from "./controllers/MyKnowledge/model";
import { useMyKnowledge } from "./controllers/MyKnowledge/useMyKnowledge";

export default function MyKnowledgePage() {
  const {
    forbidden,
    kbState,
    kb,
    actionBusy,
    createKb,
    setKbName,
    setDialogKind,
    notice,
    actionError,
    dialogKind,
    summary,
    personalState,
    setPersonalState,
    setPage,
    filtered,
    filterOpen,
    setFilterOpen,
    clearFilters,
    assetType,
    setAssetType,
    sortBy,
    sortDirection,
    setSortBy,
    setSortDirection,
    submitSearch,
    searchInput,
    setSearchInput,
    keyword,
    setKeyword,
    selectedItems,
    selectedPageItems,
    matchingSelectableItems,
    allMatchingSelected,
    matchingSelectionLoading,
    selectAllMatching,
    setSelectedItems,
    setAllMatchingSelected,
    selectedDeleteItems,
    setDeleteReason,
    setActionError,
    loadState,
    load,
    items,
    pageAllSelected,
    pageIndeterminate,
    selectablePageItems,
    loadMatchingSelectableItems,
    isBulkSelectable,
    openItemDialog,
    hasProjects,
    menuId,
    setMenuId,
    total,
    page,
    hasNext,
    closeDialog,
    kbName,
    models,
    renameKb,
    activeItem,
    runItemAction,
    targetProject,
    publicationPreview,
    publicationNaming,
    setTargetProject,
    setPublicationNaming,
    setPublicationPreview,
    projects,
    evidenceType,
    evidenceCategory,
    evidenceDescription,
    setEvidenceType,
    setEvidenceCategory,
    setEvidenceDescription,
    editTitle,
    editType,
    editTags,
    setEditTitle,
    setEditType,
    setEditTags,
    deleteReason,
    runPersonalBulkDelete,
  } = useMyKnowledge();

  return (
    <KnowledgeModuleFrame>
      <ProductPage className="mk83-page">
        <PageHeader
          title="我的知识"
          description="管理个人资料，并将成熟内容提交到项目。"
          actions={
            <>
              <Link className="btn-small-primary mk83-header-action" to="/upload">
                <Upload size={16} aria-hidden="true" />
                上传资料
              </Link>
            </>
          }
        />

        <div className="personal-library-layout">
          <aside className="personal-library-context" aria-label="个人知识库概况">
            {" "}
            {!forbidden && kbState === "ready" && kb?.exists && (
              <div className="personal-kb-summary">
                <Database size={18} aria-hidden="true" />
                <div>
                  <span>个人知识库</span>
                  <strong>{kb.display_name || "我的知识库"}</strong>
                </div>
                <span className={`mk83-status mk83-status-${kbStatus(kb.status).tone}`}>
                  {kbStatus(kb.status).label}
                </span>
                <div className="mk83-kb-actions">
                  {kb.status === "init_failed" && (
                    <button
                      type="button"
                      className="btn-small-primary"
                      disabled={actionBusy}
                      onClick={() => void createKb(false)}
                    >
                      重新初始化
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn-small"
                    onClick={() => {
                      setKbName(kb.display_name ?? "");
                      setDialogKind("rename-kb");
                    }}
                  >
                    修改名称
                  </button>
                </div>
              </div>
            )}
            {!forbidden && kbState === "ready" && kb && !kb.exists && (
              <div className="personal-kb-onboarding">
                <Database size={20} aria-hidden="true" />
                <div>
                  <strong>尚未创建个人知识库</strong>
                  <span>创建后即可集中管理个人资料。</span>
                </div>
                <button
                  type="button"
                  className="btn-small-primary"
                  onClick={() => {
                    setKbName("");
                    setDialogKind("create-kb");
                  }}
                >
                  创建知识库
                </button>
              </div>
            )}
          </aside>
          <div className="personal-library-results">
            {" "}
            {notice && (
              <div className="mk83-notice" role="status">
                {notice}
              </div>
            )}
            {actionError && !dialogKind && (
              <div className="mk83-notice is-error" role="alert">
                {actionError}
              </div>
            )}
            <PageSection className="mk83-library">
              {!forbidden && (
                <nav className="personal-state-tabs" aria-label="个人资料状态">
                  {(
                    [
                      ["", "全部资料", summary.total_assets],
                      ["awaiting_confirmation", "待本人确认", summary.awaiting_confirmation],
                      ["pending_project_review", "待项目审批", summary.pending_project_review],
                      ["active_in_project", "已进入项目", summary.active_in_project],
                    ] as const
                  ).map(([value, label, count]) => (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={personalState === value}
                      onClick={() => {
                        setPersonalState(value);
                        setPage(1);
                      }}
                    >
                      {label}
                      <span>{count}</span>
                    </button>
                  ))}
                </nav>
              )}
              {!forbidden && (
                <div className="mk83-toolbar">
                  <div className="mk83-filter-anchor" onClick={(event) => event.stopPropagation()}>
                    <button
                      type="button"
                      className={`btn-small mk83-header-action ${filtered ? "is-active" : ""}`}
                      aria-expanded={filterOpen}
                      onClick={() => setFilterOpen((value) => !value)}
                    >
                      <SlidersHorizontal size={16} aria-hidden="true" />
                      筛选
                    </button>
                    {filterOpen && (
                      <div className="mk83-filter-panel" role="dialog" aria-label="筛选个人资料">
                        <div className="mk83-filter-head">
                          <strong>筛选与排序</strong>
                          {filtered && (
                            <button type="button" onClick={clearFilters}>
                              清除筛选
                            </button>
                          )}
                        </div>
                        <label htmlFor="mk83-filter-asset-type">
                          <span>资料类型</span>
                          <select
                            id="mk83-filter-asset-type"
                            value={assetType}
                            onChange={(event) => {
                              setAssetType(event.target.value);
                              setPage(1);
                            }}
                          >
                            <option value="">全部类型</option>
                            {Object.entries(typeConfig).map(([key, value]) => (
                              <option key={key} value={key}>
                                {value.label}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label htmlFor="mk83-filter-personal-state">
                          <span>个人状态</span>
                          <select
                            id="mk83-filter-personal-state"
                            value={personalState}
                            onChange={(event) => {
                              setPersonalState(event.target.value as PersonalKnowledgeState | "");
                              setPage(1);
                            }}
                          >
                            <option value="">全部状态</option>
                            {Object.entries(stateConfig).map(([key, value]) => (
                              <option key={key} value={key}>
                                {value.label}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label htmlFor="mk83-filter-sort">
                          <span>排序方式</span>
                          <select
                            id="mk83-filter-sort"
                            value={`${sortBy}:${sortDirection}`}
                            onChange={(event) => {
                              const [field, direction] = event.target.value.split(":");
                              setSortBy(field as typeof sortBy);
                              setSortDirection(direction as typeof sortDirection);
                              setPage(1);
                            }}
                          >
                            <option value="updated_at:desc">最近更新</option>
                            <option value="updated_at:asc">较早更新</option>
                            <option value="created_at:desc">最近创建</option>
                            <option value="title:asc">标题升序</option>
                          </select>
                        </label>
                      </div>
                    )}
                  </div>

                  <form role="search" onSubmit={submitSearch}>
                    <Search size={17} aria-hidden="true" />
                    <input
                      aria-label="搜索个人资料"
                      value={searchInput}
                      onChange={(event) => setSearchInput(event.target.value)}
                      placeholder="搜索资料标题或标签"
                    />
                    <button type="submit">搜索</button>
                  </form>
                  {keyword && (
                    <button
                      className="mk83-clear-search"
                      onClick={() => {
                        setSearchInput("");
                        setKeyword("");
                        setPage(1);
                      }}
                    >
                      清除搜索
                    </button>
                  )}
                </div>
              )}
              <BulkSelectionRail
                selectedCount={selectedItems.length}
                pageSelectedCount={selectedPageItems.length}
                matchingCount={matchingSelectableItems?.length ?? selectedPageItems.length}
                allMatchingSelected={allMatchingSelected}
                matchingPending={matchingSelectionLoading}
                busy={actionBusy}
                onSelectAllMatching={
                  matchingSelectableItems &&
                  matchingSelectableItems.length > selectedPageItems.length
                    ? () => void selectAllMatching()
                    : undefined
                }
                onClear={() => {
                  setSelectedItems([]);
                  setAllMatchingSelected(false);
                }}
              >
                <button
                  className="btn-small"
                  disabled={selectedDeleteItems.length === 0 || actionBusy}
                  onClick={() => {
                    setDeleteReason("");
                    setActionError(null);
                    setDialogKind("bulk-delete");
                  }}
                  type="button"
                >
                  批量删除（{selectedDeleteItems.length}）
                </button>
              </BulkSelectionRail>
              {forbidden ? (
                <div className="mk83-state">
                  <strong>当前身份无法使用个人知识</strong>
                </div>
              ) : loadState === "loading" ? (
                <div className="mk83-state">
                  <strong>正在加载个人资料…</strong>
                </div>
              ) : loadState === "error" ? (
                <div className="mk83-state">
                  <strong>个人资料暂时无法加载</strong>
                  <span>请稍后重试。</span>
                  <button type="button" className="btn-small" onClick={() => void load()}>
                    重新加载
                  </button>
                </div>
              ) : items.length === 0 ? (
                <div className="mk83-state mk83-state-empty">
                  <FolderUp aria-hidden="true" />
                  <strong>{keyword || filtered ? "没有符合条件的资料" : "还没有个人资料"}</strong>
                  <span>
                    {keyword || filtered
                      ? "调整搜索词或清除筛选后再试。"
                      : "上传资料后，可在这里完成本人确认与项目提交。"}
                  </span>
                  {keyword || filtered ? (
                    <button
                      type="button"
                      className="btn-small"
                      onClick={() => {
                        setSearchInput("");
                        setKeyword("");
                        clearFilters();
                      }}
                    >
                      清除条件
                    </button>
                  ) : (
                    <Link className="btn-small-primary" to="/upload">
                      上传第一份资料
                    </Link>
                  )}
                </div>
              ) : (
                <div className="mk83-table-wrap">
                  <table data-responsive-table className="mk83-table">
                    <thead>
                      <tr>
                        <th>
                          <SelectionCheckbox
                            checked={pageAllSelected}
                            indeterminate={pageIndeterminate}
                            disabled={selectablePageItems.length === 0 || actionBusy}
                            label="全选当前页可操作个人资料"
                            onChange={() => {
                              if (pageAllSelected) {
                                const pageIds = new Set(selectablePageItems.map((item) => item.id));
                                setSelectedItems((current) =>
                                  current.filter((item) => !pageIds.has(item.id)),
                                );
                                setAllMatchingSelected(false);
                              } else {
                                setSelectedItems((current) => [
                                  ...current.filter(
                                    (item) =>
                                      !selectablePageItems.some(
                                        (pageItem) => pageItem.id === item.id,
                                      ),
                                  ),
                                  ...selectablePageItems,
                                ]);
                                if (matchingSelectableItems === null) {
                                  void loadMatchingSelectableItems();
                                }
                              }
                            }}
                          />
                        </th>
                        <th>资料</th>
                        <th>更新时间</th>
                        <th>个人状态</th>
                        <th>当前动作</th>
                        <th>
                          <span className="sr-only">更多操作</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((item) => {
                        const type = typeConfig[item.assetType as keyof typeof typeConfig];
                        const Icon = type?.icon ?? FileText;
                        const state = stateConfig[item.personalState] ?? {
                          label: SAFE_FALLBACK,
                          tone: "neutral",
                        };
                        const primary =
                          item.personalState === "awaiting_confirmation"
                            ? "confirm"
                            : ["ready_to_submit", "project_rejected"].includes(item.personalState)
                              ? "submit"
                              : null;
                        return (
                          <tr key={item.id}>
                            <td>
                              <SelectionCheckbox
                                checked={selectedItems.some((selected) => selected.id === item.id)}
                                disabled={!isBulkSelectable(item) || actionBusy}
                                label={`选择个人资料 ${item.title}`}
                                onChange={() => {
                                  setAllMatchingSelected(false);
                                  if (matchingSelectableItems === null) {
                                    void loadMatchingSelectableItems();
                                  }
                                  setSelectedItems((current) =>
                                    current.some((selected) => selected.id === item.id)
                                      ? current.filter((selected) => selected.id !== item.id)
                                      : [...current, item],
                                  );
                                }}
                              />
                            </td>
                            <td data-label="资料">
                              <div className="mk83-asset-cell">
                                <span className={`mk83-type-icon is-${type?.tone ?? "neutral"}`}>
                                  <Icon aria-hidden="true" />
                                </span>
                                <div>
                                  <Link
                                    to={`/knowledge/${encodeURIComponent(item.id)}`}
                                    state={{
                                      backTo: "/my/knowledge",
                                      backLabel: "返回个人知识",
                                      source: "personal",
                                    }}
                                  >
                                    {item.title}
                                  </Link>
                                  <span>
                                    {type?.label ?? SAFE_FALLBACK}
                                    {item.tags.length
                                      ? ` · ${item.tags.slice(0, 2).join("、")}`
                                      : ""}
                                    {item.projectSubmission?.target_project_name
                                      ? ` · ${item.projectSubmission.target_project_name}`
                                      : ""}
                                  </span>
                                </div>
                              </div>
                            </td>
                            <td data-label="更新时间">
                              <time>{formatBeijingDate(item.updatedAt)}</time>
                            </td>
                            <td data-label="个人状态">
                              <div className="mk83-state-stack">
                                <span className={`mk83-status mk83-status-${state.tone}`}>
                                  {state.label}
                                </span>
                                {item.evidenceSummary && (
                                  <small>
                                    已登记 {item.evidenceSummary.registered_count} 条候选证据
                                  </small>
                                )}
                              </div>
                            </td>
                            <td data-label="当前动作">
                              {primary === "confirm" && (
                                <button
                                  type="button"
                                  className="btn-small-primary"
                                  disabled={actionBusy}
                                  onClick={() => openItemDialog("confirm", item)}
                                >
                                  本人确认
                                </button>
                              )}
                              {primary === "submit" && (
                                <button
                                  type="button"
                                  className="btn-small-primary"
                                  disabled={!hasProjects || actionBusy}
                                  title={!hasProjects ? "暂无可提交的项目" : undefined}
                                  onClick={() => openItemDialog("submit", item)}
                                >
                                  提交项目
                                </button>
                              )}
                              {!primary && (
                                <Link
                                  className="btn-small"
                                  to={`/knowledge/${encodeURIComponent(item.id)}`}
                                  state={{
                                    backTo: "/my/knowledge",
                                    backLabel: "返回个人知识",
                                    source: "personal",
                                  }}
                                >
                                  <Eye size={14} aria-hidden="true" />
                                  查看详情
                                </Link>
                              )}
                            </td>
                            <td>
                              <div
                                className="mk83-more"
                                onClick={(event) => event.stopPropagation()}
                              >
                                <button
                                  type="button"
                                  className="mk83-more-button"
                                  aria-label={`更多操作：${item.title}`}
                                  title="更多操作"
                                  aria-expanded={menuId === item.id}
                                  onClick={() =>
                                    setMenuId((current) => (current === item.id ? null : item.id))
                                  }
                                >
                                  <MoreHorizontal aria-hidden="true" />
                                </button>
                                {menuId === item.id && (
                                  <div className="mk83-more-menu" role="menu">
                                    {primary && (
                                      <Link
                                        role="menuitem"
                                        to={`/knowledge/${encodeURIComponent(item.id)}`}
                                        state={{
                                          backTo: "/my/knowledge",
                                          backLabel: "返回个人知识",
                                          source: "personal",
                                        }}
                                      >
                                        <Eye size={15} />
                                        查看详情
                                      </Link>
                                    )}
                                    {hasProjects && (
                                      <button
                                        type="button"
                                        role="menuitem"
                                        onClick={() => openItemDialog("evidence", item)}
                                      >
                                        <ClipboardCheck size={15} />
                                        登记候选证据
                                      </button>
                                    )}
                                    {!isProjectLocked(item) && (
                                      <button
                                        type="button"
                                        role="menuitem"
                                        onClick={() => openItemDialog("edit", item)}
                                      >
                                        <Pencil size={15} />
                                        编辑资料
                                      </button>
                                    )}
                                    {item.access.canDelete && !isProjectLocked(item) && (
                                      <button
                                        type="button"
                                        role="menuitem"
                                        className="is-danger"
                                        onClick={() => openItemDialog("delete", item)}
                                      >
                                        <Trash2 size={15} />
                                        删除资料
                                      </button>
                                    )}
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              {!forbidden && loadState === "ready" && total > 0 && (
                <PagePagination
                  className="mk83-pagination"
                  ariaLabel="个人知识分页"
                  page={page}
                  totalPages={Math.max(1, Math.ceil(total / PAGE_SIZE))}
                  hasNext={hasNext}
                  onPageChange={setPage}
                  summary={
                    <>
                      第 {page} 页 · 共 {total} 条
                    </>
                  }
                />
              )}
            </PageSection>
          </div>
        </div>

        <ConfirmDialog
          open={dialogKind === "create-kb"}
          title="创建个人知识库"
          description="可使用推荐配置直接创建，也可在高级设置中选择可用模型。"
          confirmText="创建"
          busy={actionBusy}
          busyText="创建中…"
          error={actionError}
          errorDescription={actionError}
          onCancel={closeDialog}
          onConfirm={() => void createKb(true)}
        >
          <label className="mk83-field" htmlFor="mk83-create-kb-name">
            <span>知识库名称（可选）</span>
            <input
              id="mk83-create-kb-name"
              value={kbName}
              maxLength={100}
              placeholder="我的知识库"
              onChange={(event) => setKbName(event.target.value)}
            />
          </label>
          <ModelAdvancedSettings models={models} />
        </ConfirmDialog>
        <ConfirmDialog
          open={dialogKind === "rename-kb"}
          title="修改知识库名称"
          confirmText="保存"
          busy={actionBusy}
          error={actionError}
          errorDescription={actionError}
          onCancel={closeDialog}
          onConfirm={() => void renameKb()}
        >
          <label className="mk83-field" htmlFor="mk83-rename-kb-name">
            <span>知识库名称</span>
            <input
              id="mk83-rename-kb-name"
              value={kbName}
              maxLength={100}
              onChange={(event) => setKbName(event.target.value)}
            />
          </label>
        </ConfirmDialog>
        <ConfirmDialog
          open={dialogKind === "confirm"}
          title="确认为个人知识资产"
          description={
            activeItem
              ? `确认“${activeItem.title}”已整理完成？此操作不会将资料公开或加入项目。`
              : undefined
          }
          confirmText="确认资产"
          busy={actionBusy}
          error={actionError}
          errorDescription={actionError}
          onCancel={closeDialog}
          onConfirm={() =>
            activeItem &&
            void runItemAction(
              () => confirmPersonalAsset(activeItem.id),
              "已确认为个人知识资产",
              "确认失败，请稍后重试",
            )
          }
        />
        <ConfirmDialog
          open={dialogKind === "submit"}
          title="提交到项目"
          description="提交后将等待项目经理确认，通过前不会进入项目资料区。"
          confirmText="提交"
          busy={actionBusy}
          error={actionError}
          errorDescription={actionError}
          onCancel={closeDialog}
          onConfirm={() =>
            activeItem && targetProject && publicationPreview?.canonical_name
              ? void runItemAction(
                  () =>
                    submitPersonalKnowledge(activeItem.id, {
                      target_project_id: targetProject,
                      ...publicationNaming,
                    }),
                  "已提交，等待项目经理确认",
                  "提交失败，请稍后重试",
                )
              : setActionError(targetProject ? "请先预览并确认目标文件名" : "请选择目标项目")
          }
        >
          <label className="mk83-field" htmlFor="mk83-submit-target-project">
            <span>目标项目</span>
            <select
              id="mk83-submit-target-project"
              value={targetProject}
              onChange={(event) => {
                setTargetProject(event.target.value);
                setPublicationNaming(createPublicationNamingValue(activeItem?.title ?? ""));
                setPublicationPreview(null);
              }}
            >
              <option value="">请选择目标项目</option>
              {projects.map((project) => (
                <option key={project.projectId} value={project.projectId}>
                  {project.projectName}
                </option>
              ))}
            </select>
          </label>
          {activeItem && targetProject && (
            <PublicationNamingFields
              scope="project"
              projectId={targetProject}
              value={publicationNaming}
              disabled={actionBusy}
              onChange={setPublicationNaming}
              onPreviewed={setPublicationPreview}
              onPreview={(value) =>
                previewPersonalKnowledgePublication(activeItem.id, {
                  target_project_id: targetProject,
                  ...value,
                })
              }
            />
          )}
        </ConfirmDialog>
        <ConfirmDialog
          open={dialogKind === "evidence"}
          title="登记候选证据"
          description="这里只登记证据线索，不代表分享、客户验证或项目采纳已经成立。"
          confirmText="登记候选"
          busy={actionBusy}
          error={actionError}
          errorDescription={actionError}
          onCancel={closeDialog}
          onConfirm={() =>
            activeItem && targetProject
              ? void runItemAction(
                  () =>
                    registerPersonalKnowledgeEvidence(activeItem.id, {
                      target_project_id: targetProject,
                      evidence_type: evidenceType,
                      evidence_category: evidenceCategory,
                      description: evidenceDescription.trim() || undefined,
                    }),
                  "候选证据已登记，等待项目经理审核",
                  "登记失败，请稍后重试",
                )
              : setActionError("请选择目标项目")
          }
        >
          <div className="mk83-dialog-grid">
            <label className="mk83-field" htmlFor="mk83-evidence-target-project">
              <span>目标项目</span>
              <select
                id="mk83-evidence-target-project"
                value={targetProject}
                onChange={(event) => setTargetProject(event.target.value)}
              >
                {projects.map((project) => (
                  <option key={project.projectId} value={project.projectId}>
                    {project.projectName}
                  </option>
                ))}
              </select>
            </label>
            <label className="mk83-field" htmlFor="mk83-evidence-type">
              <span>证据类型</span>
              <select
                id="mk83-evidence-type"
                value={evidenceType}
                onChange={(event) => setEvidenceType(event.target.value as EvidenceType)}
              >
                <option value="internal_sharing">内部分享候选</option>
                <option value="client_validation">客户验证候选</option>
              </select>
            </label>
            <label className="mk83-field" htmlFor="mk83-evidence-category">
              <span>证据类别</span>
              <select
                id="mk83-evidence-category"
                value={evidenceCategory}
                onChange={(event) => setEvidenceCategory(event.target.value)}
              >
                {evidenceCategories.map((category) => (
                  <option key={category} value={category}>
                    {evidenceCategoryLabels[category]}
                  </option>
                ))}
              </select>
            </label>
            <label className="mk83-field mk83-field-wide" htmlFor="mk83-evidence-description">
              <span>补充说明（可选）</span>
              <textarea
                id="mk83-evidence-description"
                value={evidenceDescription}
                maxLength={500}
                onChange={(event) => setEvidenceDescription(event.target.value)}
              />
            </label>
          </div>
        </ConfirmDialog>
        <ConfirmDialog
          open={dialogKind === "edit"}
          title="编辑个人资料"
          description="仅修改标题、类型和安全标签。项目审核或使用中的资料不可直接修改。"
          confirmText="保存修改"
          busy={actionBusy}
          error={actionError}
          errorDescription={actionError}
          onCancel={closeDialog}
          onConfirm={() =>
            activeItem && editTitle.trim()
              ? void runItemAction(
                  () =>
                    updatePersonalKnowledge(activeItem.id, {
                      title: editTitle.trim(),
                      asset_type: editType,
                      tags: editTags
                        .split(/[，,]/)
                        .map((tag) => tag.trim())
                        .filter(Boolean),
                    }),
                  "资料信息已更新",
                  "保存失败，请稍后重试",
                )
              : setActionError("请输入资料标题")
          }
        >
          <div className="mk83-dialog-grid">
            <label className="mk83-field mk83-field-wide" htmlFor="mk83-edit-title">
              <span>资料标题</span>
              <input
                id="mk83-edit-title"
                value={editTitle}
                maxLength={500}
                onChange={(event) => setEditTitle(event.target.value)}
              />
            </label>
            <label className="mk83-field" htmlFor="mk83-edit-type">
              <span>资料类型</span>
              <select
                id="mk83-edit-type"
                value={editType}
                onChange={(event) => setEditType(event.target.value)}
              >
                {Object.entries(typeConfig).map(([key, value]) => (
                  <option key={key} value={key}>
                    {value.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="mk83-field" htmlFor="mk83-edit-tags">
              <span>标签（逗号分隔）</span>
              <input
                id="mk83-edit-tags"
                value={editTags}
                onChange={(event) => setEditTags(event.target.value)}
              />
            </label>
          </div>
        </ConfirmDialog>
        <ConfirmDialog
          open={dialogKind === "delete"}
          title="删除个人资料"
          description={
            activeItem
              ? `删除“${activeItem.title}”后将无法继续使用。项目审核或使用中的资料不能删除。`
              : undefined
          }
          confirmText="确认删除"
          danger
          busy={actionBusy}
          error={actionError}
          errorDescription={actionError}
          onCancel={closeDialog}
          onConfirm={() =>
            activeItem &&
            void runItemAction(
              () => deleteKnowledgeAsset(activeItem.id, deleteReason.trim()),
              "个人资料已删除",
              "删除失败，请稍后重试",
            )
          }
        >
          <label className="mk83-field" htmlFor="mk83-delete-reason">
            <span>删除原因（可选）</span>
            <textarea
              id="mk83-delete-reason"
              value={deleteReason}
              maxLength={500}
              placeholder="例如：重复上传"
              onChange={(event) => setDeleteReason(event.target.value)}
            />
          </label>
        </ConfirmDialog>
        <ConfirmDialog
          open={dialogKind === "bulk-delete"}
          title={`批量删除 ${selectedDeleteItems.length} 项个人资料`}
          description={`删除后这些资料将立即退出列表、检索、问答和原文授权；项目审核、引用或保留约束项会被安全跳过。另有 ${selectedItems.length - selectedDeleteItems.length} 项当前不可删除，不会提交。`}
          confirmText="确认批量删除"
          danger
          busy={actionBusy}
          error={actionError}
          errorDescription={actionError}
          onCancel={closeDialog}
          onConfirm={() => void runPersonalBulkDelete()}
        >
          <label className="mk83-field" htmlFor="mk83-bulk-delete-reason">
            <span>删除原因（可选）</span>
            <textarea
              id="mk83-bulk-delete-reason"
              value={deleteReason}
              maxLength={500}
              placeholder="例如：重复上传"
              onChange={(event) => setDeleteReason(event.target.value)}
            />
          </label>
        </ConfirmDialog>
      </ProductPage>
    </KnowledgeModuleFrame>
  );
}
