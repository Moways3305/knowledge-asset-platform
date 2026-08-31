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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [migration, setMigration] = useState<DirectoryMigrationWorkspaceDTO | null>(null);
  const [migrationOpen, setMigrationOpen] = useState(false);
  const [migrationBusy, setMigrationBusy] = useState(false);
  const [migrationSelection, setMigrationSelection] = useState<string[]>([]);
  const editRevision = useRef(0);

  const load = async () => {
    setError(null);
    try {
      setCenter(await fetchNamingRuleCenter());
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "目录治理配置暂时无法加载");
    }
  };

  useEffect(() => void load(), []);

  const config = center?.draft.config;
  const directories = useMemo(
    () =>
      [...(config?.directories ?? [])]
        .filter((directory) => directory.scope === scope)
        .sort((a, b) => a.sort_order - b.sort_order),
    [config?.directories, scope],
  );

  const updateDirectory = (key: string, patch: Partial<DirectoryOptionDTO>) => {
    if (!center || !config) return;
    editRevision.current += 1;
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
    if (!center || !config) return;
    setBusy(true);
    setError(null);
    const submittedRevision = editRevision.current;
    try {
      const draft = await saveNamingRuleDraft(center.published.version, config);
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
      setNotice("目录草稿已保存；发布前不会影响新入库资料。");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "目录草稿保存失败，当前输入已保留");
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    if (!center) return;
    setBusy(true);
    setError(null);
    try {
      setCenter(await publishNamingRuleDraft(center.published.version));
      editRevision.current = 0;
      setNotice("正式目录已发布，新上传和项目发布将立即使用本版本。");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "正式目录发布失败，请刷新后重试");
    } finally {
      setBusy(false);
    }
  };

  const openMigration = async () => {
    setMigrationOpen(true);
    setMigrationBusy(true);
    setError(null);
    try {
      setMigration(await fetchDirectoryMigration());
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "历史待治理队列暂时无法加载");
    } finally {
      setMigrationBusy(false);
    }
  };

  const migrateSelected = async () => {
    if (!migration || migrationSelection.length === 0) return;
    setMigrationBusy(true);
    try {
      await confirmDirectoryMigration(
        migration.items
          .filter((item) => migrationSelection.includes(item.id) && item.suggested_directory_key)
          .map((item) => ({ candidate_id: item.id, directory_key: item.suggested_directory_key! })),
      );
      setMigrationSelection([]);
      setMigration(await fetchDirectoryMigration());
      setNotice("已提交明确映射项；无明确候选的资料仍保留在待治理队列。");
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
            <Button variant="secondary" disabled={busy} onClick={() => void save()}>
              <Save size={16} /> 保存草稿
            </Button>
            <Button disabled={busy} onClick={() => void publish()}>
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
                <code>{directory.directory_key}</code>
              </div>
              <label>
                <span>目录名称</span>
                <input
                  value={directory.display_name}
                  onChange={(event) =>
                    updateDirectory(directory.directory_key, { display_name: event.target.value })
                  }
                />
              </label>
              <label>
                <span>目录说明</span>
                <input
                  value={directory.description ?? ""}
                  onChange={(event) =>
                    updateDirectory(directory.directory_key, { description: event.target.value })
                  }
                />
              </label>
              <label>
                <span>命名短码</span>
                <input
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
                总计 {migration.overview.total} · 待人工 {migration.overview.manual_required} ·
                无明确候选 {migration.overview.no_candidate}
              </p>
              <div className="naming-migration-list">
                {migration.items.map((item) => (
                  <label key={item.id}>
                    <input
                      type="checkbox"
                      disabled={!item.suggested_directory_key}
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
                    </span>
                  </label>
                ))}
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
