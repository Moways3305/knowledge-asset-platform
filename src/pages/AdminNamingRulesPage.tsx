import { useEffect, useMemo, useRef, useState } from "react";
import {
  BookType,
  ChevronRight,
  FolderCog,
  Plus,
  RefreshCw,
  Search,
  Send,
  Sparkles,
} from "lucide-react";
import { ApiError } from "../api/http";
import {
  confirmDirectoryMigration,
  fetchDirectoryMigration,
  fetchNamingRuleCenter,
  publishNamingRuleDraft,
  saveNamingRuleDraft,
} from "../api/naming";
import Button from "../components/Button";
import DangerConfirmDialog from "../components/DangerConfirmDialog";
import DetailDrawer from "../components/DetailDrawer";
import TaskModal from "../components/TaskModal";
import WizardModal from "../components/WizardModal";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import type {
  NamingAssetType,
  NamingCategoryConfigDTO,
  NamingRuleCenterDTO,
  NamingScope,
  DirectoryMigrationWorkspaceDTO,
} from "../types/naming";
import "./AdminNamingRulesPage.css";

const levels = ["L1", "L2", "L3", "L4", "L5"];
const pageSize = 8;
const assetTypeLabels: Record<NamingAssetType, string> = {
  deliverable: "交付物",
  methodology: "方法论",
  case: "案例",
  template: "模板",
  insight: "洞察",
  unclassified: "未分类",
};
const standardProjectCategories = [
  ["项目基础信息", "deliverable", "L4", 10],
  ["辅导过程", "deliverable", "L3", 20],
  ["交付成果", "deliverable", "L3", 30],
  ["关键资料", "unclassified", "L5", 40],
  ["项目复盘", "insight", "L3", 50],
] as const;
const standardCompanyCategories = [
  ["方法论", "模型工具", "methodology", "L2", 10],
  ["方法论", "案例研究", "case", "L2", 20],
  ["方法论", "模板", "template", "L2", 30],
  ["洞察", "研究洞察", "insight", "L2", 40],
  ["制度规范", "交付件", "deliverable", "L3", 50],
] as const;

type CategoryDraft = Pick<
  NamingCategoryConfigDTO,
  | "primary"
  | "secondary"
  | "description"
  | "asset_type"
  | "default_confidentiality"
  | "enabled"
  | "sort_order"
>;

const blankCategory = (scope: NamingScope): CategoryDraft => ({
  primary: scope === "project" ? "项目资料" : "方法论",
  secondary: "",
  description: "",
  asset_type: null,
  default_confidentiality: "L2",
  enabled: true,
  sort_order: 100,
});

function categoryPath(category: NamingCategoryConfigDTO) {
  return category.scope === "company"
    ? `${category.primary} / ${category.secondary}`
    : category.secondary;
}

function scopeName(scope: NamingScope) {
  return scope === "company" ? "公司规范" : "全项目通用规范";
}

export default function AdminNamingRulesPage() {
  const [center, setCenter] = useState<NamingRuleCenterDTO | null>(null);
  const [scope, setScope] = useState<NamingScope>("company");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [managerOpen, setManagerOpen] = useState(false);
  const [projectCodesOpen, setProjectCodesOpen] = useState(false);
  const [migrationOpen, setMigrationOpen] = useState(false);
  const [migration, setMigration] = useState<DirectoryMigrationWorkspaceDTO | null>(null);
  const [migrationStatus, setMigrationStatus] = useState("");
  const [migrationBusy, setMigrationBusy] = useState(false);
  const [migrationSelection, setMigrationSelection] = useState<string[]>([]);
  const [migrationManualChoices, setMigrationManualChoices] = useState<Record<string, string>>({});
  const [editor, setEditor] = useState<{
    category: NamingCategoryConfigDTO | null;
    value: CategoryDraft;
  } | null>(null);
  const [detail, setDetail] = useState<NamingCategoryConfigDTO | null>(null);
  const [removing, setRemoving] = useState<NamingCategoryConfigDTO | null>(null);
  const [initializeOpen, setInitializeOpen] = useState(false);
  const [initializeStep, setInitializeStep] = useState(0);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const draftEditRevisionRef = useRef(0);

  const load = async () => {
    setError(null);
    try {
      setCenter(await fetchNamingRuleCenter());
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "命名规则暂时无法加载");
    }
  };

  const loadMigration = async (nextStatus = migrationStatus) => {
    setMigrationBusy(true);
    try {
      setMigration(await fetchDirectoryMigration({ status: nextStatus || undefined }));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "历史目录迁移暂时无法加载");
    } finally {
      setMigrationBusy(false);
    }
  };
  useEffect(() => void load(), []);

  const config = center?.draft.config;
  const currentScopeName = scopeName(scope);
  const categories = useMemo(() => {
    if (!config) return [];
    return config.categories
      .filter((item) => item.scope === scope)
      .sort(
        (a, b) =>
          a.sort_order - b.sort_order || categoryPath(a).localeCompare(categoryPath(b), "zh-CN"),
      );
  }, [config, scope]);
  const filteredCategories = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return normalized
      ? categories.filter((item) =>
          `${categoryPath(item)} ${item.description ?? ""}`
            .toLocaleLowerCase()
            .includes(normalized),
        )
      : categories;
  }, [categories, query]);
  const pageCount = Math.max(1, Math.ceil(filteredCategories.length / pageSize));
  const visibleCategories = filteredCategories.slice((page - 1) * pageSize, page * pageSize);
  const enabledCount = categories.filter((item) => item.enabled).length;

  useEffect(() => setPage(1), [query, scope]);
  useEffect(() => {
    setManagerOpen(false);
    setEditor(null);
    setDetail(null);
    setRemoving(null);
    setInitializeOpen(false);
  }, [scope]);

  const updateConfig = (next: NonNullable<typeof config>) => {
    if (!center) return;
    draftEditRevisionRef.current += 1;
    setCenter({ ...center, draft: { ...center.draft, config: next } });
    setNotice(null);
  };

  if (!center || !config) {
    return (
      <ProductPage className="naming-center">
        <PageHeader
          eyebrow="组织与知识治理"
          title="命名规则中心"
          description="维护公司与全项目共用的目录类别；只有发布后的规则才会生效。"
        />
        <div className="naming-center-state">
          <BookType aria-hidden="true" />
          <p>{error ?? "正在读取已发布规则与草稿…"}</p>
          {error && <Button onClick={() => void load()}>重新加载</Button>}
        </div>
      </ProductPage>
    );
  }

  const save = async () => {
    setBusy(true);
    setError(null);
    const submittedEditRevision = draftEditRevisionRef.current;
    try {
      const draft = await saveNamingRuleDraft(center.published.version, config);
      const hasNewerEdits = draftEditRevisionRef.current !== submittedEditRevision;
      setCenter((current) =>
        current
          ? {
              ...current,
              draft: hasNewerEdits ? { ...draft, config: current.draft.config } : draft,
            }
          : current,
      );
      setNotice(
        hasNewerEdits
          ? "保存请求成功；请求期间的后续编辑仍待保存。"
          : "草稿已保存，尚未发布，不影响新入库资料。",
      );
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "草稿保存失败，请保留当前内容后重试");
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    const missingCategory = config.categories.find((item) => item.enabled && !item.asset_type);
    if (missingCategory) {
      setError(`目录类别「${categoryPath(missingCategory)}」尚未配置资产分类，不能发布。`);
      setManagerOpen(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setCenter(await publishNamingRuleDraft(center.published.version));
      setNotice("发布请求已完成；新版本仅影响此后确认入库的资料。");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "发布失败，草稿仍保留，可修正后重试");
    } finally {
      setBusy(false);
    }
  };

  const saveCategory = () => {
    if (!editor) return;
    const value = editor.value;
    const normalized: NamingCategoryConfigDTO = {
      id: editor.category?.id ?? crypto.randomUUID(),
      scope,
      primary: scope === "project" ? "项目资料" : value.primary.trim(),
      secondary: value.secondary.trim(),
      prefix:
        scope === "project"
          ? value.secondary.trim()
          : `${value.primary.trim()}-${value.secondary.trim()}`,
      description: value.description?.trim() || null,
      asset_type: value.asset_type,
      default_confidentiality: value.default_confidentiality,
      enabled: value.enabled,
      sort_order: value.sort_order,
    };
    updateConfig({
      ...config,
      categories: editor.category
        ? config.categories.map((item) => (item.id === editor.category?.id ? normalized : item))
        : [...config.categories, normalized],
    });
    setEditor(null);
    setNotice(`「${categoryPath(normalized)}」已写入本地草稿，请保存草稿后再发布。`);
  };

  const initialize = () => {
    const existing = new Set(categories.map((item) => categoryPath(item)));
    const additions: NamingCategoryConfigDTO[] =
      scope === "project"
        ? standardProjectCategories
            .filter(([name]) => !existing.has(name))
            .map(([name, assetType, level, order]) => ({
              id: crypto.randomUUID(),
              scope,
              primary: "项目资料",
              secondary: name,
              prefix: name,
              asset_type: assetType,
              default_confidentiality: level,
              enabled: true,
              sort_order: order,
            }))
        : standardCompanyCategories
            .filter(([primary, secondary]) => !existing.has(`${primary} / ${secondary}`))
            .map(([primary, secondary, assetType, level, order]) => ({
              id: crypto.randomUUID(),
              scope,
              primary,
              secondary,
              prefix: `${primary}-${secondary}`,
              asset_type: assetType,
              default_confidentiality: level,
              enabled: true,
              sort_order: order,
            }));
    updateConfig({ ...config, categories: [...config.categories, ...additions] });
    setInitializeOpen(false);
    setInitializeStep(0);
    setNotice(
      additions.length
        ? `已将 ${additions.length} 个标准类别加入${currentScopeName}的本地草稿；尚未保存或发布。`
        : `${currentScopeName}的标准类别均已存在，未重复加入。`,
    );
  };

  const projectCodeFor = (project: NamingRuleCenterDTO["projects"][number]) =>
    config.project_codes.find((item) => item.project_id === project.id) ?? {
      project_id: project.id,
      code: project.project_code ?? "",
      enabled: project.project_code_active,
      default_confidentiality: project.default_confidentiality,
      client_aliases: [],
      client_aliases_enabled: true,
    };
  const patchProjectCode = (
    project: NamingRuleCenterDTO["projects"][number],
    patch: Partial<ReturnType<typeof projectCodeFor>>,
  ) => {
    const projectCode = projectCodeFor(project);
    updateConfig({
      ...config,
      project_codes: [
        ...config.project_codes.filter((item) => item.project_id !== project.id),
        { ...projectCode, ...patch },
      ],
    });
  };
  const previewCategory = categories.find((item) => item.enabled);
  const missingAssetTypeCategories = categories.filter((item) => item.enabled && !item.asset_type);
  const preview =
    scope === "project"
      ? previewCategory
        ? `【项目代码-2026-${previewCategory.secondary}】示例主题_20260810_V1_L2.pdf`
        : "启用一个全项目通用类别后可预览"
      : previewCategory
        ? `【${previewCategory.primary}-${previewCategory.secondary}】示例主题_全体顾问_20260810_V1_L2.pdf`
        : "启用一个公司类别后可预览";

  return (
    <ProductPage className="naming-center">
      <PageHeader
        eyebrow="组织与知识治理"
        title="命名规则中心"
        description="维护公司与全项目共用的目录类别；草稿只有显式发布后才会生效。"
        scope={currentScopeName}
        status={
          <StatusBadge
            label={missingAssetTypeCategories.length > 0 ? "规则待补全" : "草稿待发布"}
            tone={missingAssetTypeCategories.length > 0 ? "warning" : "info"}
          />
        }
      />
      <div className="naming-version-cluster" aria-label="规则版本状态">
        <div>
          <span>当前发布</span>
          <strong>v{center.published.version}</strong>
          <small>{center.published.config.enforced ? "正在执行" : "尚未强制"}</small>
        </div>
        <div>
          <span>工作草稿</span>
          <strong>v{center.draft.version}</strong>
          <small>{center.draft.status === "draft" ? "等待发布" : center.draft.status}</small>
        </div>
      </div>

      <section className="naming-scope-console" aria-labelledby="scope-heading">
        <div className="naming-scope-rail">
          <span>当前管理范围</span>
          <strong id="scope-heading">{currentScopeName}</strong>
          <small>
            {scope === "company"
              ? "公司级类别不会出现在项目资料中"
              : "一次维护，所有项目使用同一类别集合"}
          </small>
        </div>
        <div className="naming-scope-controls">
          <div className="naming-segmented" role="group" aria-label="规则范围">
            <button
              className={scope === "company" ? "is-active" : ""}
              aria-pressed={scope === "company"}
              onClick={() => setScope("company")}
            >
              公司规范
            </button>
            <button
              className={scope === "project" ? "is-active" : ""}
              aria-pressed={scope === "project"}
              onClick={() => setScope("project")}
            >
              全项目通用规范
            </button>
          </div>
          <p className="naming-scope-note">
            {scope === "company" ? "用于公司知识库" : `适用于 ${center.projects.length} 个项目`}
          </p>
        </div>
      </section>

      {notice && (
        <p className="naming-notice" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="naming-error" role="alert">
          {error}
        </p>
      )}
      {missingAssetTypeCategories.length > 0 && (
        <p className="naming-error" role="status">
          当前范围有 {missingAssetTypeCategories.length} 个启用类别缺少资产分类，发布已阻断；请在
          “管理目录类别”中逐项补齐。
        </p>
      )}

      <>
        <section className="naming-overview" aria-label={`${currentScopeName}摘要`}>
          <div>
            <span>目录类别</span>
            <strong>{categories.length}</strong>
            <small>仅当前范围</small>
          </div>
          <div>
            <span>已启用</span>
            <strong>{enabledCount}</strong>
            <small>{categories.length - enabledCount} 个停用</small>
          </div>
          <div>
            <span>草稿更新</span>
            <strong>{new Date(center.draft.updated_at).toLocaleDateString("zh-CN")}</strong>
            <small>v{center.draft.version} · 尚未发布</small>
          </div>
        </section>

        <section className="naming-action-deck">
          <div className="naming-preview-card">
            <span>规范名预览</span>
            <code>{preview}</code>
            <small>预览只使用当前范围内第一个已启用类别</small>
          </div>
          <div className="naming-primary-actions">
            <Button
              onClick={() => {
                setMigrationOpen(true);
                void loadMigration();
              }}
            >
              历史目录迁移
            </Button>
            <Button icon={<FolderCog size={16} />} onClick={() => setManagerOpen(true)}>
              管理目录类别
            </Button>
            {scope === "project" && (
              <Button onClick={() => setProjectCodesOpen(true)}>管理项目代码</Button>
            )}
            <Button
              icon={<Sparkles size={16} />}
              onClick={() => {
                setInitializeStep(0);
                setInitializeOpen(true);
              }}
            >
              初始化标准目录
            </Button>
            <Button icon={<RefreshCw size={16} />} disabled={busy} onClick={() => void load()}>
              刷新
            </Button>
            <Button disabled={busy} onClick={() => void save()}>
              保存草稿
            </Button>
            <Button
              variant="primary"
              icon={<Send size={16} />}
              disabled={busy}
              onClick={() => void publish()}
            >
              发布规则
            </Button>
          </div>
          <label className="naming-enforce-toggle">
            <input
              type="checkbox"
              checked={config.enforced}
              onChange={(event) => updateConfig({ ...config, enforced: event.target.checked })}
            />
            发布后强制项目/公司规范命名
          </label>
        </section>
      </>

      <DetailDrawer
        open={migrationOpen}
        title="历史目录迁移"
        description="只为当前 active 版本写入正式目录元数据；不会重传、重建索引、改变资料/资产状态或创建审核。"
        busy={migrationBusy}
        onClose={() => setMigrationOpen(false)}
        footer={
          <>
            <Button onClick={() => setMigrationOpen(false)}>关闭</Button>
            <span className="task-modal-footer-spacer" />
            <Button disabled={migrationBusy} onClick={() => void loadMigration()}>
              刷新候选
            </Button>
            <Button
              variant="primary"
              disabled={migrationBusy || migrationSelection.length === 0}
              onClick={() => {
                setMigrationBusy(true);
                void confirmDirectoryMigration(
                  migrationSelection.map((id) => ({ candidate_id: id })),
                )
                  .then((result) => {
                    setNotice(
                      `目录迁移完成：迁入 ${result.migrated}，跳过 ${result.skipped}，失败 ${result.failed}。`,
                    );
                    setMigrationSelection([]);
                    return loadMigration();
                  })
                  .catch(() => setError("目录迁移未完成，候选仍保留，可重试。"))
                  .finally(() => setMigrationBusy(false));
              }}
            >
              确认明确匹配（{migrationSelection.length}）
            </Button>
          </>
        }
      >
        {migration && (
          <div className="naming-migration-workspace">
            <div className="naming-migration-overview">
              <div>
                <span>总数</span>
                <strong>{migration.overview.total}</strong>
              </div>
              <div>
                <span>已迁入</span>
                <strong>{migration.overview.migrated}</strong>
              </div>
              <div>
                <span>明确匹配</span>
                <strong>{migration.overview.clear_match}</strong>
              </div>
              <div>
                <span>需人工</span>
                <strong>{migration.overview.manual_required}</strong>
              </div>
              <div>
                <span>无候选</span>
                <strong>{migration.overview.no_candidate}</strong>
              </div>
              <div>
                <span>失败</span>
                <strong>{migration.overview.failed}</strong>
              </div>
            </div>
            <p className="naming-migration-rule">
              唯一有效来源：当前发布目录规则 v{migration.overview.rule_version ?? "—"}
            </p>
            <label className="naming-migration-filter">
              <span>候选状态</span>
              <select
                value={migrationStatus}
                onChange={(event) => {
                  const next = event.target.value;
                  setMigrationStatus(next);
                  void loadMigration(next);
                }}
              >
                <option value="">全部</option>
                <option value="clear_match">明确匹配</option>
                <option value="manual_required">需人工选择</option>
                <option value="no_candidate">无有效候选</option>
                <option value="failed">失败可重试</option>
              </select>
            </label>
            <div className="naming-migration-list">
              {migration.items.map((item) => (
                <article key={item.id}>
                  <label>
                    <input
                      type="checkbox"
                      disabled={item.status !== "clear_match"}
                      checked={migrationSelection.includes(item.id)}
                      onChange={(event) =>
                        setMigrationSelection((current) =>
                          event.target.checked
                            ? [...current, item.id]
                            : current.filter((id) => id !== item.id),
                        )
                      }
                    />
                    <span>
                      <strong>{item.asset_title}</strong>
                      <small>
                        {item.project_name || item.scope} · 旧类别 {item.old_category || "未记录"}
                      </small>
                    </span>
                  </label>
                  {item.status === "clear_match" ? (
                    <span>{item.suggested_directory_name || "未分类 / 待治理"}</span>
                  ) : item.status !== "migrated" ? (
                    <div className="naming-migration-manual">
                      <select
                        aria-label={`为 ${item.asset_title} 选择目录`}
                        value={migrationManualChoices[item.id] || ""}
                        onChange={(event) =>
                          setMigrationManualChoices((current) => ({
                            ...current,
                            [item.id]: event.target.value,
                          }))
                        }
                      >
                        <option value="">人工选择目录</option>
                        {migration.directories
                          .filter((directory) => directory.scope === item.scope)
                          .map((directory) => (
                            <option key={directory.directory_key} value={directory.directory_key}>
                              {directory.display_name}
                            </option>
                          ))}
                      </select>
                      <Button
                        disabled={migrationBusy || !migrationManualChoices[item.id]}
                        onClick={() => {
                          setMigrationBusy(true);
                          void confirmDirectoryMigration([
                            {
                              candidate_id: item.id,
                              directory_key: migrationManualChoices[item.id],
                            },
                          ])
                            .then(() => loadMigration())
                            .catch(() => setError("人工目录确认未完成，可重试。"))
                            .finally(() => setMigrationBusy(false));
                        }}
                      >
                        确认选择
                      </Button>
                    </div>
                  ) : (
                    <span>已迁入</span>
                  )}
                </article>
              ))}
            </div>
          </div>
        )}
      </DetailDrawer>

      <TaskModal
        open={projectCodesOpen}
        title="管理项目代码"
        description="项目代码和默认密级是各项目自身事实；目录类别仍由全项目通用规范统一提供。"
        eyebrow="项目事实设置"
        size="large"
        onClose={() => setProjectCodesOpen(false)}
        footer={
          <>
            <span className="naming-modal-count">共 {center.projects.length} 个项目</span>
            <span className="task-modal-footer-spacer" />
            <Button onClick={() => setProjectCodesOpen(false)}>完成</Button>
          </>
        }
      >
        <div className="naming-project-code-list">
          {center.projects.map((project) => {
            const projectCode = projectCodeFor(project);
            return (
              <article className="naming-project-settings" key={project.id}>
                <div>
                  <span>项目事实</span>
                  <h3>{project.name}</h3>
                  <p>仅代码、默认密级和启用状态按项目独立配置。</p>
                </div>
                <label>
                  项目代码
                  <input
                    value={projectCode.code}
                    maxLength={20}
                    placeholder="如 BW-2601"
                    onChange={(event) =>
                      patchProjectCode(project, { code: event.target.value.toUpperCase() })
                    }
                  />
                </label>
                <label>
                  默认密级
                  <select
                    value={projectCode.default_confidentiality}
                    onChange={(event) =>
                      patchProjectCode(project, {
                        default_confidentiality: event.target.value,
                      })
                    }
                  >
                    {levels.map((level) => (
                      <option key={level}>{level}</option>
                    ))}
                  </select>
                </label>
                <label className="naming-check">
                  <input
                    type="checkbox"
                    checked={projectCode.enabled}
                    onChange={(event) =>
                      patchProjectCode(project, { enabled: event.target.checked })
                    }
                  />
                  启用项目代码
                </label>
              </article>
            );
          })}
        </div>
      </TaskModal>

      <TaskModal
        open={managerOpen}
        title="管理目录类别"
        description={`只显示${currentScopeName}的类别；切换范围会自动关闭此窗口。`}
        eyebrow={currentScopeName}
        size="large"
        onClose={() => setManagerOpen(false)}
        footer={
          <>
            <span className="naming-modal-count">共 {filteredCategories.length} 个类别</span>
            <span className="task-modal-footer-spacer" />
            <Button onClick={() => setManagerOpen(false)}>完成</Button>
          </>
        }
      >
        <div className="naming-manager-tools">
          <label>
            <Search size={15} aria-hidden="true" />
            <span className="sr-only">搜索目录类别</span>
            <input
              aria-label="搜索目录类别"
              value={query}
              placeholder="搜索路径或说明"
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <Button
            variant="primary"
            icon={<Plus size={15} />}
            onClick={() => setEditor({ category: null, value: blankCategory(scope) })}
          >
            新增类别
          </Button>
        </div>
        {visibleCategories.length ? (
          <div className="naming-category-list" role="list">
            {visibleCategories.map((category) => (
              <div key={category.id} role="listitem">
                <button className="naming-category-row" onClick={() => setDetail(category)}>
                  <span className="naming-category-path">
                    <strong>{categoryPath(category)}</strong>
                    <small>{category.description || "暂无说明"}</small>
                  </span>
                  <span className={`naming-state ${category.enabled ? "is-enabled" : ""}`}>
                    {category.enabled && !category.asset_type
                      ? "缺少资产分类"
                      : category.enabled
                        ? "已启用"
                        : "已停用"}
                  </span>
                  <span className="naming-category-meta">
                    {category.default_confidentiality} · 排序 {category.sort_order}
                  </span>
                  <ChevronRight size={17} aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="naming-list-empty">
            <FolderCog aria-hidden="true" />
            <strong>{query ? "没有匹配的类别" : "当前范围还没有目录类别"}</strong>
            <p>{query ? "尝试更换关键词。" : "可以新增类别，或使用标准目录初始化。"}</p>
          </div>
        )}
        {pageCount > 1 && (
          <nav className="naming-pagination" aria-label="目录类别分页">
            <Button
              size="small"
              disabled={page === 1}
              onClick={() => setPage((value) => value - 1)}
            >
              上一页
            </Button>
            <span>
              第 {page} / {pageCount} 页
            </span>
            <Button
              size="small"
              disabled={page === pageCount}
              onClick={() => setPage((value) => value + 1)}
            >
              下一页
            </Button>
          </nav>
        )}
      </TaskModal>

      <TaskModal
        open={Boolean(editor)}
        title={editor?.category ? "编辑目录类别" : "新增目录类别"}
        description={`归属范围：${currentScopeName}。类别范围在此窗口中不可切换。`}
        eyebrow={currentScopeName}
        onClose={() => setEditor(null)}
        size="small"
        footer={
          <>
            <Button onClick={() => setEditor(null)}>取消</Button>
            <span className="task-modal-footer-spacer" />
            <Button
              variant="primary"
              disabled={
                !editor?.value.secondary.trim() ||
                (scope === "company" && !editor.value.primary.trim()) ||
                (editor?.value.enabled && !editor.value.asset_type)
              }
              onClick={saveCategory}
            >
              写入草稿
            </Button>
          </>
        }
      >
        {editor && (
          <div className="naming-category-form">
            <div className="naming-scope-seal">
              <span>只读归属</span>
              <strong>{currentScopeName}</strong>
            </div>
            {scope === "company" && (
              <label>
                一级分类
                <input
                  value={editor.value.primary}
                  maxLength={40}
                  onChange={(event) =>
                    setEditor({
                      ...editor,
                      value: { ...editor.value, primary: event.target.value },
                    })
                  }
                />
              </label>
            )}
            <label>
              {scope === "company" ? "二级分类" : "类别名称"}
              <input
                data-autofocus
                value={editor.value.secondary}
                maxLength={40}
                placeholder={scope === "company" ? "如 模型工具" : "如 交付成果"}
                onChange={(event) =>
                  setEditor({
                    ...editor,
                    value: { ...editor.value, secondary: event.target.value },
                  })
                }
              />
            </label>
            <label>
              类别说明
              <textarea
                value={editor.value.description ?? ""}
                maxLength={300}
                rows={3}
                onChange={(event) =>
                  setEditor({
                    ...editor,
                    value: { ...editor.value, description: event.target.value },
                  })
                }
              />
            </label>
            <label>
              资产分类
              <select
                aria-label="资产分类"
                value={editor.value.asset_type ?? ""}
                aria-invalid={editor.value.enabled && !editor.value.asset_type}
                onChange={(event) =>
                  setEditor({
                    ...editor,
                    value: {
                      ...editor.value,
                      asset_type: (event.target.value || null) as NamingAssetType | null,
                    },
                  })
                }
              >
                <option value="">请选择资产分类</option>
                {Object.entries(assetTypeLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              {editor.value.enabled && !editor.value.asset_type && (
                <small className="naming-field-error">启用类别必须配置资产分类。</small>
              )}
            </label>
            <div className="naming-form-pair">
              <label>
                默认密级
                <select
                  value={editor.value.default_confidentiality}
                  onChange={(event) =>
                    setEditor({
                      ...editor,
                      value: { ...editor.value, default_confidentiality: event.target.value },
                    })
                  }
                >
                  {levels.map((level) => (
                    <option key={level}>{level}</option>
                  ))}
                </select>
              </label>
              <label>
                显示排序
                <input
                  type="number"
                  min={0}
                  max={10000}
                  value={editor.value.sort_order}
                  onChange={(event) =>
                    setEditor({
                      ...editor,
                      value: { ...editor.value, sort_order: Number(event.target.value) },
                    })
                  }
                />
              </label>
            </div>
            <label className="naming-check">
              <input
                type="checkbox"
                checked={editor.value.enabled}
                onChange={(event) =>
                  setEditor({
                    ...editor,
                    value: { ...editor.value, enabled: event.target.checked },
                  })
                }
              />
              发布后启用此类别
            </label>
          </div>
        )}
      </TaskModal>

      <DetailDrawer
        open={Boolean(detail)}
        title={detail ? categoryPath(detail) : "目录类别"}
        description={`${currentScopeName}的目录类别`}
        onClose={() => setDetail(null)}
        footer={
          detail && (
            <>
              <Button
                variant="danger"
                onClick={() => {
                  setRemoving(detail);
                  setDetail(null);
                }}
              >
                删除
              </Button>
              <span className="task-modal-footer-spacer" />
              <Button
                variant="primary"
                onClick={() => {
                  setEditor({
                    category: detail,
                    value: {
                      primary: detail.primary,
                      secondary: detail.secondary,
                      description: detail.description ?? "",
                      asset_type: detail.asset_type,
                      default_confidentiality: detail.default_confidentiality,
                      enabled: detail.enabled,
                      sort_order: detail.sort_order,
                    },
                  });
                  setDetail(null);
                }}
              >
                编辑类别
              </Button>
            </>
          )
        }
      >
        {detail && (
          <div className="naming-detail-grid">
            <div className="naming-scope-seal">
              <span>适用范围</span>
              <strong>{currentScopeName}</strong>
            </div>
            <dl>
              <div>
                <dt>资产分类</dt>
                <dd>
                  {detail.asset_type ? assetTypeLabels[detail.asset_type] : "缺失，发布前必须补齐"}
                </dd>
              </div>
              <div>
                <dt>完整路径</dt>
                <dd>{categoryPath(detail)}</dd>
              </div>
              <div>
                <dt>状态</dt>
                <dd>{detail.enabled ? "已启用" : "已停用"}</dd>
              </div>
              <div>
                <dt>默认密级</dt>
                <dd>{detail.default_confidentiality}</dd>
              </div>
              <div>
                <dt>显示排序</dt>
                <dd>{detail.sort_order}</dd>
              </div>
              <div>
                <dt>类别说明</dt>
                <dd>{detail.description || "暂无说明"}</dd>
              </div>
            </dl>
          </div>
        )}
      </DetailDrawer>

      <DangerConfirmDialog
        open={Boolean(removing)}
        title={removing ? `删除「${categoryPath(removing)}」？` : "删除目录类别"}
        description={`该类别属于${currentScopeName}，删除后无法从当前草稿恢复。`}
        confirmText="删除类别"
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          if (!removing) return;
          updateConfig({
            ...config,
            categories: config.categories.filter((item) => item.id !== removing.id),
          });
          setNotice(
            `已从${currentScopeName}的本地草稿删除「${categoryPath(removing)}」；保存草稿后才会写入。`,
          );
          setRemoving(null);
        }}
      >
        <div className="naming-danger-copy">
          <strong>删除前请确认</strong>
          <p>
            若该类别仍被业务流程使用，保存或发布可能被后端阻止。届时请保留草稿，根据错误提示停用类别或调整引用。
          </p>
        </div>
      </DangerConfirmDialog>

      <WizardModal
        open={initializeOpen}
        title="初始化标准目录"
        description={`本次只处理${currentScopeName}，不会覆盖已存在的类别。`}
        steps={[
          { label: "确认范围", description: currentScopeName },
          { label: "提交草稿", description: "受理不等于发布" },
        ]}
        currentStep={initializeStep}
        onBack={() => setInitializeStep(0)}
        onNext={() => setInitializeStep(1)}
        onCancel={() => {
          setInitializeOpen(false);
          setInitializeStep(0);
        }}
        onComplete={initialize}
        completeText="加入本地草稿"
      >
        {initializeStep === 0 ? (
          <div className="naming-wizard-copy">
            <div className="naming-scope-seal">
              <span>影响范围</span>
              <strong>{currentScopeName}</strong>
            </div>
            <p>系统将补齐缺失的标准类别；同路径类别不会重复新增，也不会修改其他公司或项目范围。</p>
          </div>
        ) : (
          <div className="naming-wizard-copy">
            <strong>这一步不会直接发布</strong>
            <p>
              提交后只代表标准类别已加入浏览器中的工作草稿。你仍需等待“保存草稿”请求成功，并显式发布，规则才会生效。
            </p>
          </div>
        )}
      </WizardModal>
    </ProductPage>
  );
}
