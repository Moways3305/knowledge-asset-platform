import { useEffect, useMemo, useRef, useState } from "react";
import { ArchiveRestore, FolderCog, RefreshCw, Save, Send } from "lucide-react";
import { ApiError } from "../api/http";
import {
  confirmDirectoryMigration,
  fetchDirectoryMigration,
  fetchNamingRuleCenter,
  publishNamingRuleDraft,
  saveNamingRuleDraft,
} from "../api/naming";
import Button from "../components/Button";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import type {
  DirectoryMigrationWorkspaceDTO,
  DirectoryOptionDTO,
  NamingScope,
} from "../types/naming";
import "./AdminNamingRulesPage.css";

const levels = ["L1", "L2", "L3", "L4", "L5"];
const scopeLabel = (scope: NamingScope) => (scope === "company" ? "公司目录" : "项目目录");

export default function AdminNamingRulesPage() {
  const [center, setCenter] = useState<Awaited<ReturnType<typeof fetchNamingRuleCenter>> | null>(
    null,
  );
  const [scope, setScope] = useState<NamingScope>("company");
  const [newParent, setNewParent] = useState(
    () => new URLSearchParams(window.location.search).get("parent") ?? "",
  );
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [conflicted, setConflicted] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [loadingCenter, setLoadingCenter] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [migration, setMigration] = useState<DirectoryMigrationWorkspaceDTO | null>(null);
  const [migrationPage, setMigrationPage] = useState(1);
  const [migrationOpen, setMigrationOpen] = useState(false);
  const [migrationBusy, setMigrationBusy] = useState(false);
  const [migrationSelection, setMigrationSelection] = useState<string[]>([]);
  const selectableMigrationIds = (migration?.items ?? [])
    .filter(
      (item) =>
        item.suggested_directory_key && item.confidence === "clear" && item.status !== "migrated",
    )
    .map((item) => item.id);
  const editRevision = useRef(0);
  const writeInFlight = useRef(false);
  const loadRequest = useRef(0);

  const load = async () => {
    const request = ++loadRequest.current;
    setLoadingCenter(true);
    setError(null);
    try {
      const latest = await fetchNamingRuleCenter();
      if (request !== loadRequest.current) return;
      setCenter(latest);
      setConflicted(false);
      setNotice(null);
      setHasUnsavedChanges(false);
      editRevision.current = 0;
    } catch (reason) {
      if (request !== loadRequest.current) return;
      setError(reason instanceof ApiError ? reason.message : "目录治理配置暂时无法加载");
    } finally {
      if (request === loadRequest.current) setLoadingCenter(false);
    }
  };

  useEffect(() => {
    void load();
    return () => {
      loadRequest.current += 1;
    };
  }, []);

  const config = center?.draft.config;
  const companyParents = (config?.directories ?? []).filter(
    (item) => item.scope === "company" && !item.parent_key && item.enabled,
  );
  const addCompanyDirectory = () => {
    const parent = companyParents.find((item) => item.directory_key === newParent);
    const name = newName.trim();
    if (!center || !config || !parent) {
      setError("请选择启用的公司库分类");
      return;
    }
    if (
      !name ||
      name.length > 40 ||
      /[<>:"/\\|?*]/.test(name) ||
      [...name].some((char) => char.charCodeAt(0) < 32)
    ) {
      setError("目录名称须为1至40个字符，不能包含路径或控制字符");
      return;
    }
    if (
      (config.directories ?? []).some(
        (item) =>
          item.parent_key === parent.directory_key &&
          item.display_name.toLocaleLowerCase() === name.toLocaleLowerCase(),
      )
    ) {
      setError("同一分类下已存在同名三级目录");
      return;
    }
    editRevision.current += 1;
    setHasUnsavedChanges(true);
    setCenter({
      ...center,
      draft: {
        ...center.draft,
        config: {
          ...config,
          directories: [
            ...(config.directories ?? []),
            {
              directory_key: `company.custom_${crypto.randomUUID().replace(/-/g, "")}`,
              scope: "company",
              parent_key: parent.directory_key,
              display_name: name,
              naming_code: name,
              default_confidentiality: parent.default_confidentiality ?? "L2",
              sort_order: parent.sort_order,
              enabled: true,
            },
          ],
        },
      },
    });
    setNewName("");
    setError(null);
    setNotice("三级目录已加入当前编辑内容，请保存草稿并发布后使用。");
  };
  const directories = useMemo(
    () =>
      [...(config?.directories ?? [])]
        .filter((directory) => directory.scope === scope)
        .sort((a, b) => a.sort_order - b.sort_order),
    [config?.directories, scope],
  );

  const updateDirectory = (key: string, patch: Partial<DirectoryOptionDTO>) => {
    if (!center || !config || publishing || loadingCenter) return;
    editRevision.current += 1;
    setHasUnsavedChanges(true);
    setCenter({
      ...center,
      draft: {
        ...center.draft,
        config: {
          ...config,
          directories: (config.directories ?? []).map((directory) =>
            directory.directory_key === key ? { ...directory, ...patch } : directory,
          ),
        },
      },
    });
    setNotice(null);
  };

  const save = async () => {
    if (!center || !config || conflicted || loadingCenter || writeInFlight.current) return;
    writeInFlight.current = true;
    setBusy(true);
    setError(null);
    setNotice(null);
    const submittedRevision = editRevision.current;
    try {
      const draft = await saveNamingRuleDraft(
        center.published.version,
        config,
        center.draft.updated_at,
      );
      setCenter((current) =>
        current
          ? {
              ...current,
              draft:
                submittedRevision === editRevision.current
                  ? draft
                  : { ...draft, config: current.draft.config },
            }
          : current,
      );
      const stillUnsaved = submittedRevision !== editRevision.current;
      setHasUnsavedChanges(stillUnsaved);
      setNotice(
        stillUnsaved
          ? "已保存先前提交的草稿；当前页面还有未保存修改。"
          : "目录草稿已保存；发布前不会影响新入库资料。",
      );
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) setConflicted(true);
      setError(reason instanceof ApiError ? reason.message : "目录草稿保存失败，当前输入已保留");
    } finally {
      writeInFlight.current = false;
      setBusy(false);
    }
  };

  const publish = async () => {
    if (!center || conflicted || loadingCenter || hasUnsavedChanges || writeInFlight.current)
      return;
    writeInFlight.current = true;
    setPublishing(true);
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setCenter(await publishNamingRuleDraft(center.published.version, center.draft.updated_at));
      editRevision.current = 0;
      setNotice("正式目录已发布，新上传和项目发布将立即使用本版本。");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) setConflicted(true);
      setError(reason instanceof ApiError ? reason.message : "正式目录发布失败，请刷新后重试");
    } finally {
      setPublishing(false);
      writeInFlight.current = false;
      setBusy(false);
    }
  };

  const openMigration = async (page = 1) => {
    if (migrationBusy) return;
    setMigrationSelection([]);
    setMigrationOpen(true);
    setMigrationBusy(true);
    setError(null);
    try {
      setMigration(await fetchDirectoryMigration({ status: "pending", page }));
      setMigrationPage(page);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "历史待治理队列暂时无法加载");
    } finally {
      setMigrationBusy(false);
    }
  };

  const migrateSelected = async () => {
    if (!migration || migrationBusy || migrationSelection.length === 0) return;
    const items = migration.items
      .filter(
        (item) => migrationSelection.includes(item.id) && selectableMigrationIds.includes(item.id),
      )
      .map((item) => ({ candidate_id: item.id }));
    if (items.length === 0) return;
    setMigrationBusy(true);
    try {
      const result = await confirmDirectoryMigration(items);
      setMigrationSelection([]);
      setMigration(await fetchDirectoryMigration({ status: "pending", page: 1 }));
      setMigrationPage(1);
      setNotice(
        `迁移成功 ${result.migrated} 项 · 跳过 ${result.skipped} 项 · 失败 ${result.failed} 项。`,
      );
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "历史目录迁移失败，未迁移项已保留");
    } finally {
      setMigrationBusy(false);
    }
  };

  if (!center || !config) {
    return (
      <ProductPage className="naming-center">
        <PageHeader
          eyebrow="组织与知识治理"
          title="目录治理"
          description="正式目录是公司与项目知识的唯一归属体系。"
        />
        <div className="naming-center-state">
          <FolderCog aria-hidden="true" />
          <p>{error ?? "正在读取正式目录配置…"}</p>
          {error && <Button onClick={() => void load()}>重新加载</Button>}
        </div>
      </ProductPage>
    );
  }

  return (
    <ProductPage className="naming-center">
      <PageHeader
        eyebrow="组织与知识治理"
        title="目录治理"
        description="维护正式目录的显示、命名短码与默认密级；历史类别只保留用于审计，不再参与新资料归属。"
        actions={
          <>
            <Button variant="secondary" onClick={() => void openMigration()}>
              <ArchiveRestore size={16} /> 历史待治理
            </Button>
            <Button
              variant="secondary"
              disabled={busy || conflicted || loadingCenter}
              onClick={() => void save()}
            >
              <Save size={16} /> 保存草稿
            </Button>
            <Button
              disabled={busy || conflicted || loadingCenter || hasUnsavedChanges}
              onClick={() => void publish()}
            >
              <Send size={16} /> 发布正式目录
            </Button>
          </>
        }
      />

      {(error || notice) && (
        <div className={error ? "naming-center-error" : "naming-center-notice"} role="status">
          {error ?? notice}
        </div>
      )}

      {conflicted && (
        <div className="naming-center-error">
          <p>当前输入已保留。重新加载将替换当前输入，请先记录需要保留的修改，再核对最新草稿。</p>
          <Button variant="secondary" disabled={loadingCenter} onClick={() => void load()}>
            重新加载目录
          </Button>
        </div>
      )}

      {hasUnsavedChanges && !conflicted && (
        <p role="status">当前修改尚未保存，请先保存草稿再发布。</p>
      )}

      <section className="naming-overview" aria-label="目录版本概览">
        <div>
          <span>已发布版本</span>
          <strong>V{center.published.version}</strong>
        </div>
        <div>
          <span>当前草稿</span>
          <strong>V{center.draft.version}</strong>
        </div>
        <div>
          <span>正式目录</span>
          <strong>{(config.directories ?? []).length}</strong>
        </div>
        <div>
          <span>治理原则</span>
          <strong>一条资料 · 一个目录</strong>
        </div>
      </section>

      <div className="naming-scope-tabs" role="tablist" aria-label="目录范围">
        {(["company", "project"] as const).map((value) => (
          <button
            aria-selected={scope === value}
            className={scope === value ? "is-active" : ""}
            key={value}
            onClick={() => setScope(value)}
            role="tab"
            type="button"
          >
            {scopeLabel(value)}
          </button>
        ))}
      </div>

      <section className="naming-directory-governance" aria-label={scopeLabel(scope)}>
        {scope === "company" && (
          <form
            className="naming-project-settings"
            onSubmit={(event) => {
              event.preventDefault();
              addCompanyDirectory();
            }}
          >
            <h2>新建三级目录</h2>
            <p>公司库 / 标准分类 / 三级目录。发布后可用于上传、资料编辑和目录浏览。</p>
            <label>
              所属分类
              <select
                value={newParent}
                onChange={(event) => setNewParent(event.target.value)}
                disabled={busy || loadingCenter}
                required
              >
                <option value="">请选择分类</option>
                {companyParents.map((item) => (
                  <option key={item.directory_key} value={item.directory_key}>
                    {item.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              三级目录名称
              <input
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                maxLength={40}
                disabled={busy || loadingCenter}
                required
              />
            </label>
            <Button type="submit" disabled={busy || loadingCenter}>
              添加到草稿
            </Button>
          </form>
        )}
        <header>
          <div>
            <h2>{scopeLabel(scope)}</h2>
            <p>稳定键不可修改；名称、说明、排序、命名短码和默认密级随目录版本发布。</p>
          </div>
          <StatusBadge label={`${directories.length} 个目录`} tone="neutral" />
        </header>
        <div className="naming-directory-list">
          {directories.map((directory) => (
            <article className="naming-project-settings" key={directory.directory_key}>
              <div>
                <strong>{directory.display_name}</strong>
                {directory.parent_key && (
                  <span>
                    所属分类：
                    {companyParents.find((item) => item.directory_key === directory.parent_key)
                      ?.display_name ?? directory.parent_key}
                  </span>
                )}
                <code>{directory.directory_key}</code>
              </div>
              <label>
                <span>目录名称</span>
                <input
                  disabled={publishing || loadingCenter}
                  value={directory.display_name}
                  onChange={(event) =>
                    updateDirectory(directory.directory_key, { display_name: event.target.value })
                  }
                />
              </label>
              <label>
                <span>目录说明</span>
                <input
                  disabled={publishing || loadingCenter}
                  value={directory.description ?? ""}
                  onChange={(event) =>
                    updateDirectory(directory.directory_key, { description: event.target.value })
                  }
                />
              </label>
              <label>
                <span>命名短码</span>
                <input
                  disabled={publishing || loadingCenter}
                  value={directory.naming_code ?? ""}
                  placeholder="例如 方法论"
                  onChange={(event) =>
                    updateDirectory(directory.directory_key, { naming_code: event.target.value })
                  }
                />
              </label>
              <label>
                <span>默认密级</span>
                <select
                  disabled={publishing || loadingCenter}
                  value={directory.default_confidentiality ?? "L2"}
                  onChange={(event) =>
                    updateDirectory(directory.directory_key, {
                      default_confidentiality: event.target.value,
                    })
                  }
                >
                  {levels.map((level) => (
                    <option key={level}>{level}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>排序</span>
                <input
                  disabled={publishing || loadingCenter}
                  type="number"
                  min={0}
                  max={10000}
                  value={directory.sort_order}
                  onChange={(event) =>
                    updateDirectory(directory.directory_key, {
                      sort_order: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label className="naming-category-toggle">
                <input
                  disabled={publishing || loadingCenter}
                  type="checkbox"
                  checked={directory.enabled}
                  onChange={(event) =>
                    updateDirectory(directory.directory_key, { enabled: event.target.checked })
                  }
                />
                <span>启用目录</span>
              </label>
            </article>
          ))}
        </div>
      </section>

      {migrationOpen && (
        <section className="naming-migration-panel" aria-label="历史待治理队列">
          <header>
            <div>
              <h2>历史待治理队列</h2>
              <p>仅提交已有明确、可审计映射的资料；无候选项不会被静默猜测。</p>
            </div>
            <button
              aria-label="刷新历史待治理队列"
              onClick={() => void openMigration()}
              type="button"
            >
              <RefreshCw size={16} />
            </button>
          </header>
          {migrationBusy && <p>正在读取待治理资料…</p>}
          {migration && (
            <>
              <p>
                资产总计 {migration.overview.total} · 已归类 {migration.overview.migrated} · 待治理{" "}
                {migration.total} · 待人工 {migration.overview.manual_required} · 无明确候选{" "}
                {migration.overview.no_candidate}
              </p>
              <div>
                <Button
                  disabled={migrationBusy || selectableMigrationIds.length === 0}
                  onClick={() => setMigrationSelection(selectableMigrationIds)}
                >
                  全选本页可迁移项
                </Button>
                <Button
                  disabled={migrationBusy || migrationSelection.length === 0}
                  onClick={() => setMigrationSelection([])}
                >
                  取消全选
                </Button>
                <span>已选 {migrationSelection.length} 项</span>
              </div>
              <div className="naming-migration-list">
                {migration.items.map((item) => (
                  <label key={item.id}>
                    <input
                      type="checkbox"
                      disabled={migrationBusy || !selectableMigrationIds.includes(item.id)}
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
                      <small>{item.suggested_directory_name ?? "无明确目录候选，继续待治理"}</small>
                      {item.confidence !== "clear" && item.suggested_directory_key && (
                        <small>需人工确认目录，暂不可迁移</small>
                      )}
                    </span>
                  </label>
                ))}
              </div>
              <div aria-label="历史待治理分页">
                <button
                  type="button"
                  disabled={migrationBusy || migrationPage <= 1}
                  onClick={() => void openMigration(migrationPage - 1)}
                >
                  上一页
                </button>
                <span>
                  第 {migrationPage} / {Math.max(1, Math.ceil(migration.total / 50))} 页 · 本页{" "}
                  {migration.items.length} 项
                </span>
                <button
                  type="button"
                  disabled={migrationBusy || migrationPage * 50 >= migration.total}
                  onClick={() => void openMigration(migrationPage + 1)}
                >
                  下一页
                </button>
              </div>
              <Button
                disabled={migrationBusy || migrationSelection.length === 0}
                onClick={() => void migrateSelected()}
              >
                确认迁移 {migrationSelection.length} 项
              </Button>
            </>
          )}
        </section>
      )}
    </ProductPage>
  );
}
