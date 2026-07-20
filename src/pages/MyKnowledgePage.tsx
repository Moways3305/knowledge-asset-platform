import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import {
  BadgeCheck,
  BookOpenCheck,
  BriefcaseBusiness,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Database,
  Eye,
  FileText,
  Files,
  FolderCheck,
  FolderUp,
  LayoutTemplate,
  Lightbulb,
  MoreHorizontal,
  Pencil,
  Search,
  SlidersHorizontal,
  Trash2,
  Upload,
} from "lucide-react";
import { fetchAuthMe, type AuthMeVM } from "../api/auth";
import { ApiError } from "../api/http";
import { deleteKnowledgeAsset } from "../api/knowledge";
import {
  confirmPersonalAsset,
  createMyKnowledgeBase,
  fetchMyKnowledge,
  fetchMyKnowledgeBase,
  registerPersonalKnowledgeEvidence,
  renameMyKnowledgeBase,
  submitPersonalKnowledge,
  updatePersonalKnowledge,
  type PersonalKbDTO,
} from "../api/personal";
import ConfirmDialog from "../components/ConfirmDialog";
import ModelAdvancedSettings from "../components/ModelAdvancedSettings";
import { PageHeader, PageSection, ProductPage } from "../components/ProductLayout";
import { useModelSelection } from "../hooks/useModelSelection";
import type {
  PersonalKnowledgeItemVM,
  PersonalKnowledgeState,
  PersonalKnowledgeSummaryDTO,
} from "../types/myKnowledge";
import { formatBeijingTime } from "../utils/time";
import "./MyKnowledgePage.css";

const PAGE_SIZE = 20;
const SAFE_FALLBACK = "信息待确认";
const emptySummary: PersonalKnowledgeSummaryDTO = {
  total_assets: 0,
  awaiting_confirmation: 0,
  pending_project_review: 0,
  active_in_project: 0,
  created_this_month: 0,
};

const typeConfig = {
  methodology: { label: "方法论", icon: BookOpenCheck, tone: "blue" },
  deliverable: { label: "交付物", icon: BriefcaseBusiness, tone: "gold" },
  case: { label: "案例", icon: Files, tone: "green" },
  template: { label: "模板", icon: LayoutTemplate, tone: "violet" },
  insight: { label: "洞察", icon: Lightbulb, tone: "amber" },
} as const;

const stateConfig: Record<PersonalKnowledgeState, { label: string; tone: string }> = {
  awaiting_confirmation: { label: "待本人确认", tone: "warning" },
  ready_to_submit: { label: "可提交项目", tone: "ready" },
  pending_project_review: { label: "待项目经理审批", tone: "pending" },
  active_in_project: { label: "已进入项目", tone: "success" },
  project_rejected: { label: "项目未通过", tone: "danger" },
};

const evidenceCategoryLabels: Record<string, string> = {
  meeting_minutes: "会议纪要",
  wecom_record: "企微记录",
  client_email: "客户邮件",
  acceptance_doc: "验收单",
  delivery_adoption: "交付采纳",
};
const evidenceCategories = Object.keys(evidenceCategoryLabels);

type DialogKind =
  | "create-kb"
  | "rename-kb"
  | "confirm"
  | "submit"
  | "evidence"
  | "edit"
  | "delete"
  | null;
type LoadState = "loading" | "ready" | "error" | "forbidden";
type EvidenceType = "internal_sharing" | "client_validation";

function kbStatus(status?: string | null) {
  if (status === "active") return { label: "运行正常", tone: "success" };
  if (status === "init_failed") return { label: "初始化失败", tone: "danger" };
  return { label: SAFE_FALLBACK, tone: "neutral" };
}

function safeActionError(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.status === 403) return "当前身份无权执行此操作";
  if (
    error instanceof ApiError &&
    error.status === 409 &&
    error.deniedReason === "personal_asset_project_locked"
  ) {
    return "项目审核或项目使用中的资料不可直接修改";
  }
  return fallback;
}

function isProjectLocked(item: PersonalKnowledgeItemVM) {
  return ["pending_project_review", "active_in_project"].includes(item.personalState);
}

export default function MyKnowledgePage() {
  const [items, setItems] = useState<PersonalKnowledgeItemVM[]>([]);
  const [summary, setSummary] = useState(emptySummary);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [assetType, setAssetType] = useState("");
  const [personalState, setPersonalState] = useState<PersonalKnowledgeState | "">("");
  const [sortBy, setSortBy] = useState<"updated_at" | "created_at" | "title">("updated_at");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [filterOpen, setFilterOpen] = useState(false);
  const [menuId, setMenuId] = useState<string | null>(null);
  const [projects, setProjects] = useState<AuthMeVM["projects"]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [kbState, setKbState] = useState<LoadState>("loading");
  const [kb, setKb] = useState<PersonalKbDTO | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dialogKind, setDialogKind] = useState<DialogKind>(null);
  const [activeItem, setActiveItem] = useState<PersonalKnowledgeItemVM | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [kbName, setKbName] = useState("");
  const [targetProject, setTargetProject] = useState("");
  const [evidenceType, setEvidenceType] = useState<EvidenceType>("internal_sharing");
  const [evidenceCategory, setEvidenceCategory] = useState(evidenceCategories[0]);
  const [evidenceDescription, setEvidenceDescription] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [editType, setEditType] = useState("");
  const [editTags, setEditTags] = useState("");
  const [deleteReason, setDeleteReason] = useState("");
  const requestRef = useRef(0);
  const models = useModelSelection();

  const load = useCallback(async () => {
    const request = ++requestRef.current;
    setLoadState("loading");
    try {
      const result = await fetchMyKnowledge({
        page,
        pageSize: PAGE_SIZE,
        keyword: keyword || undefined,
        assetType: assetType || undefined,
        personalState: personalState || undefined,
        sortBy,
        sortDirection,
      });
      if (request !== requestRef.current) return;
      setItems(result.items);
      setSummary(result.summary);
      setTotal(result.total);
      setHasNext(result.hasNext);
      setLoadState("ready");
    } catch (error) {
      if (request !== requestRef.current) return;
      setItems([]);
      setTotal(0);
      setHasNext(false);
      setLoadState(error instanceof ApiError && error.status === 403 ? "forbidden" : "error");
    }
  }, [assetType, keyword, page, personalState, sortBy, sortDirection]);

  const loadKb = useCallback(async () => {
    try {
      setKb(await fetchMyKnowledgeBase());
      setKbState("ready");
    } catch (error) {
      setKb(null);
      setKbState(error instanceof ApiError && error.status === 403 ? "forbidden" : "error");
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      requestRef.current += 1;
    };
  }, [load]);

  useEffect(() => {
    void loadKb();
    void fetchAuthMe()
      .then((me) => setProjects(me.projects))
      .catch(() => setProjects([]));
  }, [loadKb]);

  useEffect(() => {
    const close = () => {
      setFilterOpen(false);
      setMenuId(null);
    };
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("click", close);
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("click", close);
      document.removeEventListener("keydown", keydown);
    };
  }, []);

  const openItemDialog = (kind: DialogKind, item: PersonalKnowledgeItemVM) => {
    setActiveItem(item);
    setDialogKind(kind);
    setTargetProject(projects[0]?.projectId ?? "");
    setEvidenceType("internal_sharing");
    setEvidenceCategory(evidenceCategories[0]);
    setEvidenceDescription("");
    setEditTitle(item.title);
    setEditType(item.assetType);
    setEditTags(item.tags.join("，"));
    setDeleteReason("");
    setActionError(null);
    setMenuId(null);
  };

  const closeDialog = () => {
    if (actionBusy) return;
    setDialogKind(null);
    setActiveItem(null);
    setActionError(null);
  };

  const refreshAfterAction = async (message: string) => {
    setDialogKind(null);
    setActiveItem(null);
    setNotice(message);
    await load();
  };

  const runItemAction = async (
    action: () => Promise<unknown>,
    message: string,
    fallback: string,
  ) => {
    setActionBusy(true);
    setActionError(null);
    try {
      await action();
      await refreshAfterAction(message);
    } catch (error) {
      setActionError(safeActionError(error, fallback));
    } finally {
      setActionBusy(false);
    }
  };

  const createKb = async (includeModels: boolean) => {
    if (includeModels && models.blockSubmit) {
      setActionError("默认模型尚未配置，请联系管理员完成配置");
      return;
    }
    setActionBusy(true);
    setActionError(null);
    try {
      const data = await createMyKnowledgeBase({
        displayName: kbName.trim() || undefined,
        embeddingModelRef: includeModels ? models.embeddingRef || undefined : undefined,
        rerankModelRef: includeModels ? models.rerankRef || undefined : undefined,
      });
      setKb(data);
      setKbState("ready");
      setDialogKind(null);
      setNotice(includeModels ? "个人知识库已创建" : "已重新发起初始化");
    } catch (error) {
      setActionError(safeActionError(error, "创建失败，请稍后重试"));
    } finally {
      setActionBusy(false);
    }
  };

  const renameKb = async () => {
    if (!kbName.trim()) {
      setActionError("请输入知识库名称");
      return;
    }
    setActionBusy(true);
    setActionError(null);
    try {
      const data = await renameMyKnowledgeBase(kbName.trim());
      setKb(data);
      setDialogKind(null);
      setNotice(data.weknora_sync_failed ? "名称已保存，检索服务同步稍后重试" : "知识库名称已更新");
    } catch (error) {
      setActionError(safeActionError(error, "改名失败，请稍后重试"));
    } finally {
      setActionBusy(false);
    }
  };

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    setPage(1);
    setKeyword(searchInput.trim());
  };

  const clearFilters = () => {
    setAssetType("");
    setPersonalState("");
    setSortBy("updated_at");
    setSortDirection("desc");
    setPage(1);
  };

  const filtered = Boolean(
    assetType || personalState || sortBy !== "updated_at" || sortDirection !== "desc",
  );
  const forbidden = loadState === "forbidden";
  const hasProjects = projects.length > 0;
  const stats = [
    {
      label: "资料总数",
      value: summary.total_assets,
      note:
        summary.created_this_month > 0
          ? `本月新增 ${summary.created_this_month} 份`
          : "个人资料总览",
      icon: Files,
      tone: "blue",
    },
    {
      label: "待本人确认",
      value: summary.awaiting_confirmation,
      note: "需要完成个人整理",
      icon: ClipboardCheck,
      tone: "gold",
    },
    {
      label: "待项目审批",
      value: summary.pending_project_review,
      note: "等待项目经理处理",
      icon: BadgeCheck,
      tone: "violet",
    },
    {
      label: "已进入项目",
      value: summary.active_in_project,
      note: "已进入项目资料区",
      icon: FolderCheck,
      tone: "green",
    },
  ];

  return (
    <ProductPage className="mk83-page">
      <PageHeader
        title="我的个人知识"
        description="管理个人资料，并将成熟内容提交到项目。"
        actions={
          <>
            <div className="mk83-filter-anchor" onClick={(event) => event.stopPropagation()}>
              <button
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
                    {filtered && <button onClick={clearFilters}>清除筛选</button>}
                  </div>
                  <label>
                    <span>资料类型</span>
                    <select
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
                  <label>
                    <span>个人状态</span>
                    <select
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
                  <label>
                    <span>排序方式</span>
                    <select
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
            <Link className="btn-small-primary mk83-header-action" to="/upload">
              <Upload size={16} aria-hidden="true" />
              上传资料
            </Link>
          </>
        }
      />

      {!forbidden && kbState === "ready" && kb?.exists && (
        <div className="mk83-kb-strip">
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
                className="btn-small-primary"
                disabled={actionBusy}
                onClick={() => void createKb(false)}
              >
                重新初始化
              </button>
            )}
            <button
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
        <div className="mk83-kb-empty">
          <Database size={20} aria-hidden="true" />
          <div>
            <strong>尚未创建个人知识库</strong>
            <span>创建后即可集中管理个人资料。</span>
          </div>
          <button
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

      {!forbidden && (
        <div className="mk83-stats" aria-label="个人知识统计">
          {stats.map((stat) => {
            const Icon = stat.icon;
            return (
              <article key={stat.label}>
                <div className={`mk83-stat-icon is-${stat.tone}`}>
                  <Icon aria-hidden="true" />
                </div>
                <div className="mk83-stat-copy">
                  <span>{stat.label}</span>
                  <strong>{stat.value}</strong>
                  <small>{stat.note}</small>
                </div>
              </article>
            );
          })}
        </div>
      )}
      {notice && (
        <div className="mk83-notice" role="status">
          {notice}
        </div>
      )}

      <PageSection
        className="mk83-library"
        title="个人资料"
        actions={<span className="mk83-count">共 {total} 条</span>}
      >
        {!forbidden && (
          <div className="mk83-toolbar">
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
            <button className="btn-small" onClick={() => void load()}>
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
            <table className="mk83-table">
              <thead>
                <tr>
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
                        <div className="mk83-asset-cell">
                          <span className={`mk83-type-icon is-${type?.tone ?? "neutral"}`}>
                            <Icon aria-hidden="true" />
                          </span>
                          <div>
                            <Link to={`/knowledge/${encodeURIComponent(item.id)}`}>
                              {item.title}
                            </Link>
                            <span>
                              {type?.label ?? SAFE_FALLBACK}
                              {item.tags.length ? ` · ${item.tags.slice(0, 2).join("、")}` : ""}
                              {item.projectSubmission?.target_project_name
                                ? ` · ${item.projectSubmission.target_project_name}`
                                : ""}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td>
                        <time>{formatBeijingTime(item.updatedAt)}</time>
                      </td>
                      <td>
                        <div className="mk83-state-stack">
                          <span className={`mk83-status mk83-status-${state.tone}`}>
                            {state.label}
                          </span>
                          {item.evidenceSummary && (
                            <small>已登记 {item.evidenceSummary.registered_count} 条候选证据</small>
                          )}
                        </div>
                      </td>
                      <td>
                        {primary === "confirm" && (
                          <button
                            className="btn-small-primary"
                            disabled={actionBusy}
                            onClick={() => openItemDialog("confirm", item)}
                          >
                            本人确认
                          </button>
                        )}
                        {primary === "submit" && (
                          <button
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
                          >
                            <Eye size={14} aria-hidden="true" />
                            查看详情
                          </Link>
                        )}
                      </td>
                      <td>
                        <div className="mk83-more" onClick={(event) => event.stopPropagation()}>
                          <button
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
                              <Link
                                role="menuitem"
                                to={`/knowledge/${encodeURIComponent(item.id)}`}
                              >
                                <Eye size={15} />
                                查看详情
                              </Link>
                              {hasProjects && (
                                <button
                                  role="menuitem"
                                  onClick={() => openItemDialog("evidence", item)}
                                >
                                  <ClipboardCheck size={15} />
                                  登记候选证据
                                </button>
                              )}
                              {!isProjectLocked(item) && (
                                <button
                                  role="menuitem"
                                  onClick={() => openItemDialog("edit", item)}
                                >
                                  <Pencil size={15} />
                                  编辑资料
                                </button>
                              )}
                              {item.access.canDelete && !isProjectLocked(item) && (
                                <button
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
          <div className="mk83-pagination">
            <span>
              第 {page} 页 · 共 {total} 条
            </span>
            <div>
              <button
                aria-label="上一页"
                className="btn-small"
                disabled={page === 1}
                onClick={() => setPage((value) => Math.max(1, value - 1))}
              >
                <ChevronLeft size={16} />
              </button>
              <button
                aria-label="下一页"
                className="btn-small"
                disabled={!hasNext}
                onClick={() => setPage((value) => value + 1)}
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}
      </PageSection>

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
        <label className="mk83-field">
          <span>知识库名称（可选）</span>
          <input
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
        <label className="mk83-field">
          <span>知识库名称</span>
          <input
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
          activeItem && targetProject
            ? void runItemAction(
                () => submitPersonalKnowledge(activeItem.id, { target_project_id: targetProject }),
                "已提交，等待项目经理确认",
                "提交失败，请稍后重试",
              )
            : setActionError("请选择目标项目")
        }
      >
        <label className="mk83-field">
          <span>目标项目</span>
          <select value={targetProject} onChange={(event) => setTargetProject(event.target.value)}>
            {projects.map((project) => (
              <option key={project.projectId} value={project.projectId}>
                {project.projectName}
              </option>
            ))}
          </select>
        </label>
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
          <label className="mk83-field">
            <span>目标项目</span>
            <select
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
          <label className="mk83-field">
            <span>证据类型</span>
            <select
              value={evidenceType}
              onChange={(event) => setEvidenceType(event.target.value as EvidenceType)}
            >
              <option value="internal_sharing">内部分享候选</option>
              <option value="client_validation">客户验证候选</option>
            </select>
          </label>
          <label className="mk83-field">
            <span>证据类别</span>
            <select
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
          <label className="mk83-field mk83-field-wide">
            <span>补充说明（可选）</span>
            <textarea
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
          <label className="mk83-field mk83-field-wide">
            <span>资料标题</span>
            <input
              value={editTitle}
              maxLength={500}
              onChange={(event) => setEditTitle(event.target.value)}
            />
          </label>
          <label className="mk83-field">
            <span>资料类型</span>
            <select value={editType} onChange={(event) => setEditType(event.target.value)}>
              {Object.entries(typeConfig).map(([key, value]) => (
                <option key={key} value={key}>
                  {value.label}
                </option>
              ))}
            </select>
          </label>
          <label className="mk83-field">
            <span>标签（逗号分隔）</span>
            <input value={editTags} onChange={(event) => setEditTags(event.target.value)} />
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
        <label className="mk83-field">
          <span>删除原因（可选）</span>
          <textarea
            value={deleteReason}
            maxLength={500}
            placeholder="例如：重复上传"
            onChange={(event) => setDeleteReason(event.target.value)}
          />
        </label>
      </ConfirmDialog>
    </ProductPage>
  );
}
