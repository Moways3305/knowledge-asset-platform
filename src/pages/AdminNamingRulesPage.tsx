import { useEffect, useMemo, useRef, useState } from "react";
import { BookType, CircleHelp, Plus, RefreshCw, Send, Sparkles, Trash2 } from "lucide-react";
import { ApiError } from "../api/http";
import { fetchNamingRuleCenter, publishNamingRuleDraft, saveNamingRuleDraft } from "../api/naming";
import type { NamingCategoryConfigDTO, NamingRuleCenterDTO } from "../types/naming";
import "./AdminNamingRulesPage.css";

const levels = ["L1", "L2", "L3", "L4", "L5"];
const standardProjectCategories = [
  { name: "项目基础信息", confidentiality: "L4", order: 10 },
  { name: "辅导过程", confidentiality: "L3", order: 20 },
  { name: "交付成果", confidentiality: "L3", order: 30 },
  { name: "关键资料", confidentiality: "L5", order: 40 },
  { name: "项目复盘", confidentiality: "L3", order: 50 },
] as const;

function makeProjectCategory(
  name: string,
  defaultConfidentiality: string,
  sortOrder: number,
): NamingCategoryConfigDTO {
  return {
    id: crypto.randomUUID(),
    scope: "project",
    primary: "项目资料",
    secondary: name,
    prefix: name,
    default_confidentiality: defaultConfidentiality,
    enabled: true,
    sort_order: sortOrder,
  };
}

function convertCategoryScope(
  category: NamingCategoryConfigDTO,
  scope: "project" | "company",
): NamingCategoryConfigDTO {
  const secondary = category.secondary.trim() || "新类别";
  if (scope === "project") {
    return { ...category, scope, primary: "项目资料", secondary, prefix: secondary };
  }
  const primary = category.scope === "company" ? category.primary.trim() || "方法论" : "方法论";
  return { ...category, scope, primary, secondary, prefix: `${primary}-${secondary}` };
}

function example(scope: "project" | "company", category?: NamingCategoryConfigDTO): string {
  if (!category) return "先新增并启用一个目录类别";
  return scope === "project"
    ? `【PRJ-2026-${category.secondary}】示例主题_20260802_V1_L2.pdf`
    : `【${category.primary}-${category.secondary}】示例主题_全体顾问_20260802_V1_L2.pdf`;
}

export default function AdminNamingRulesPage() {
  const [center, setCenter] = useState<NamingRuleCenterDTO | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [categoryHelpOpen, setCategoryHelpOpen] = useState(false);
  const draftEditRevisionRef = useRef(0);

  const load = async () => {
    setError(null);
    try {
      setCenter(await fetchNamingRuleCenter());
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "命名规则暂时无法加载");
    }
  };
  useEffect(() => void load(), []);

  const config = center?.draft.config;
  const updateConfig = (next: NonNullable<typeof config>) => {
    if (!center) return;
    draftEditRevisionRef.current += 1;
    setCenter({ ...center, draft: { ...center.draft, config: next } });
    setNotice(null);
  };
  const projectCategory = config?.categories.find(
    (item) => item.scope === "project" && item.enabled,
  );
  const companyCategory = config?.categories.find(
    (item) => item.scope === "company" && item.enabled,
  );
  const dirtySummary = useMemo(
    () =>
      config
        ? `${config.project_codes.length} 个项目代码 · ${config.categories.length} 个目录类别`
        : "",
    [config],
  );

  if (!center || !config) {
    return (
      <main className="naming-center">
        <div className="naming-center-state">
          <BookType aria-hidden="true" />
          <h1>命名规则中心</h1>
          <p>{error ?? "正在读取已发布规则与草稿…"}</p>
          {error && <button onClick={() => void load()}>重新加载</button>}
        </div>
      </main>
    );
  }

  const save = async () => {
    setBusy(true);
    setError(null);
    const submittedEditRevision = draftEditRevisionRef.current;
    try {
      const normalizedConfig = {
        ...config,
        categories: config.categories.map((category) =>
          convertCategoryScope(category, category.scope),
        ),
      };
      const draft = await saveNamingRuleDraft(center.published.version, normalizedConfig);
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
          ? "保存完成；保存期间的后续编辑尚未保存。"
          : "草稿已保存，尚未影响新入库资料。",
      );
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "草稿保存失败");
    } finally {
      setBusy(false);
    }
  };
  const publish = async () => {
    setBusy(true);
    setError(null);
    try {
      setCenter(await publishNamingRuleDraft(center.published.version));
      setNotice("规则已发布，仅影响此后确认入库的资料。");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "规则发布失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="naming-center">
      <header className="naming-center-hero">
        <div>
          <span className="naming-center-kicker">Knowledge naming policy</span>
          <h1>命名规则中心</h1>
          <p>项目资料使用项目代码；草稿只有显式发布后才参与新确认入库。</p>
        </div>
        <div className="naming-release-card" aria-label="规则发布状态">
          <span>当前发布</span>
          <strong>v{center.published.version}</strong>
          <small>{center.published.config.enforced ? "正在执行" : "尚未强制"}</small>
        </div>
      </header>

      <div className="naming-toolbar">
        <div>
          <strong>草稿 v{center.draft.version}</strong>
          <span>{dirtySummary}</span>
        </div>
        <label className="naming-enforce-toggle">
          <input
            type="checkbox"
            checked={config.enforced}
            onChange={(event) => updateConfig({ ...config, enforced: event.target.checked })}
          />
          发布后强制项目/公司规范命名
        </label>
        <button className="btn-secondary" disabled={busy} onClick={() => void load()} type="button">
          <RefreshCw size={15} />
          刷新
        </button>
        <button className="btn-secondary" disabled={busy} onClick={() => void save()} type="button">
          保存草稿
        </button>
        <button
          className="btn-primary"
          disabled={busy}
          onClick={() => void publish()}
          type="button"
        >
          <Send size={15} />
          发布规则
        </button>
      </div>
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

      <section className="naming-section" aria-labelledby="project-code-title">
        <div className="naming-section-head">
          <div>
            <span>01</span>
            <h2 id="project-code-title">项目代码</h2>
          </div>
          <p>代码发布后进入规范名；客户名称不参与拼接。</p>
        </div>
        <div className="naming-grid naming-project-grid">
          {center.projects.map((project) => {
            const row = config.project_codes.find((item) => item.project_id === project.id) ?? {
              project_id: project.id,
              code: project.project_code ?? "",
              enabled: project.project_code_active,
              default_confidentiality: project.default_confidentiality,
              client_aliases: [],
              client_aliases_enabled: true,
            };
            const patchRow = (patch: Partial<typeof row>) => {
              const next = config.project_codes.filter((item) => item.project_id !== project.id);
              next.push({ ...row, ...patch });
              updateConfig({ ...config, project_codes: next });
            };
            return (
              <article className="naming-project-card" key={project.id}>
                <div>
                  <strong>{project.name}</strong>
                  <small>{project.status}</small>
                </div>
                <label>
                  项目代码
                  <input
                    value={row.code}
                    maxLength={20}
                    placeholder="如 BW-2601"
                    onChange={(e) => patchRow({ code: e.target.value.toUpperCase() })}
                  />
                </label>
                <label>
                  默认密级
                  <select
                    value={row.default_confidentiality}
                    onChange={(e) => patchRow({ default_confidentiality: e.target.value })}
                  >
                    {levels.map((level) => (
                      <option key={level}>{level}</option>
                    ))}
                  </select>
                </label>
                <label>
                  客户命名别名（顿号分隔）
                  <input
                    value={(row.client_aliases ?? []).join("、")}
                    maxLength={500}
                    placeholder="如 琥崧、琥崧智能"
                    onChange={(event) =>
                      patchRow({
                        client_aliases: event.target.value
                          .split(/[,，、\n]/)
                          .map((value) => value.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                </label>
                <label className="naming-inline-check">
                  <input
                    type="checkbox"
                    checked={row.enabled}
                    onChange={(e) => patchRow({ enabled: e.target.checked })}
                  />
                  启用
                </label>
                <label className="naming-inline-check">
                  <input
                    type="checkbox"
                    checked={row.client_aliases_enabled ?? true}
                    onChange={(event) => patchRow({ client_aliases_enabled: event.target.checked })}
                  />
                  启用客户别名防护
                </label>
              </article>
            );
          })}
        </div>
      </section>

      <section className="naming-section" aria-labelledby="category-title">
        <div className="naming-section-head">
          <div className="naming-section-title">
            <span>02</span>
            <h2 id="category-title">目录类别</h2>
            <div
              className="naming-category-help"
              onMouseEnter={() => setCategoryHelpOpen(true)}
              onMouseLeave={() => setCategoryHelpOpen(false)}
            >
              <button
                aria-label="查看目录类别填写说明"
                aria-describedby={categoryHelpOpen ? "category-help-tooltip" : undefined}
                className="naming-help-trigger"
                type="button"
                onFocus={() => setCategoryHelpOpen(true)}
                onBlur={() => setCategoryHelpOpen(false)}
              >
                <CircleHelp size={16} />
              </button>
              {categoryHelpOpen && (
                <div className="naming-help-popover" id="category-help-tooltip" role="tooltip">
                  <strong>项目库字段</strong>
                  <code>项目基础信息 | L4 | 10 | 启用</code>
                  <p>规范名类别片段取“项目基础信息”。</p>
                  <strong>公司库字段</strong>
                  <code>方法论 | 模型工具 | L2 | 10 | 启用</code>
                  <p>规范名类别片段取“方法论-模型工具”。</p>
                  <small>
                    排序数值越小越靠前。项目规范名使用项目代码、文件形成日期年份和二级分类；命名展示名仅供配置与展示，不是年份或项目代码。
                  </small>
                </div>
              )}
            </div>
          </div>
          <div className="naming-category-actions">
            <button
              className="btn-secondary"
              type="button"
              onClick={() => {
                const existing = new Set(
                  config.categories
                    .filter((item) => item.scope === "project")
                    .map((item) => item.secondary.trim()),
                );
                const missing = standardProjectCategories.filter(
                  (item) => !existing.has(item.name),
                );
                updateConfig({
                  ...config,
                  categories: [
                    ...config.categories,
                    ...missing.map((item) =>
                      makeProjectCategory(item.name, item.confidentiality, item.order),
                    ),
                  ],
                });
                setNotice(
                  missing.length === 0
                    ? "5 个标准类别均已存在，未重复新增。"
                    : `已新增 ${missing.length} 个项目库标准类别；已存在的类别未重复新增。`,
                );
              }}
            >
              <Sparkles size={15} />
              一键初始化项目库标准目录
            </button>
            <button
              className="btn-secondary"
              type="button"
              onClick={() =>
                updateConfig({
                  ...config,
                  categories: [
                    ...config.categories,
                    makeProjectCategory("新类别", "L2", config.categories.length * 10 + 10),
                  ],
                })
              }
            >
              <Plus size={15} />
              新增类别
            </button>
          </div>
        </div>
        <div className="naming-category-list">
          {config.categories.map((category, index) => {
            const patchCategory = (patch: Partial<NamingCategoryConfigDTO>) =>
              updateConfig({
                ...config,
                categories: config.categories.map((item, itemIndex) =>
                  itemIndex === index ? { ...item, ...patch } : item,
                ),
              });
            return (
              <div
                aria-label={`${category.scope === "project" ? "项目库" : "公司库"}目录类别 ${category.secondary}`}
                className={`naming-category-row is-${category.scope}`}
                key={category.id}
                role="group"
              >
                <select
                  aria-label="适用库范围"
                  title="选择该类别用于项目库或公司库"
                  value={category.scope}
                  onChange={(e) =>
                    patchCategory(
                      convertCategoryScope(category, e.target.value as "project" | "company"),
                    )
                  }
                >
                  <option value="project">项目库</option>
                  <option value="company">公司库</option>
                </select>
                {category.scope === "company" && (
                  <input
                    aria-label="一级分类"
                    placeholder="一级分类，如 方法论"
                    title="公司规范名中的一级分类"
                    value={category.primary}
                    onChange={(e) => {
                      const primary = e.target.value;
                      patchCategory({ primary, prefix: `${primary}-${category.secondary}` });
                    }}
                  />
                )}
                <input
                  aria-label={category.scope === "project" ? "类别名称" : "二级分类"}
                  placeholder={
                    category.scope === "project"
                      ? "类别名称，如 项目基础信息"
                      : "二级分类，如 模型工具"
                  }
                  title={
                    category.scope === "project"
                      ? "项目规范名中的二级分类片段"
                      : "公司规范名中的二级分类"
                  }
                  value={category.secondary}
                  onChange={(e) => {
                    const secondary = e.target.value;
                    patchCategory({
                      secondary,
                      prefix:
                        category.scope === "project"
                          ? secondary
                          : `${category.primary}-${secondary}`,
                    });
                  }}
                />
                <select
                  aria-label="默认密级"
                  title="新建该类资料时建议使用的默认密级"
                  value={category.default_confidentiality}
                  onChange={(e) => patchCategory({ default_confidentiality: e.target.value })}
                >
                  {levels.map((level) => (
                    <option key={level}>{level}</option>
                  ))}
                </select>
                <input
                  aria-label="显示排序"
                  title="排序数值越小越靠前"
                  placeholder="排序"
                  type="number"
                  min={0}
                  max={10000}
                  value={category.sort_order}
                  onChange={(e) => patchCategory({ sort_order: Number(e.target.value) })}
                />
                <label className="naming-inline-check">
                  <input
                    type="checkbox"
                    title="是否在发布后提供该目录类别"
                    checked={category.enabled}
                    onChange={(e) => patchCategory({ enabled: e.target.checked })}
                  />
                  启用
                </label>
                <button
                  aria-label={`删除目录类别 ${category.secondary}`}
                  className="naming-delete-category"
                  title="从当前草稿删除类别"
                  type="button"
                  onClick={() => {
                    const confirmed = window.confirm(
                      `将从当前命名规则草稿中删除「${category.secondary}」，发布后才对后续入库生效；历史已入库资料不会改名。`,
                    );
                    if (!confirmed) return;
                    updateConfig({
                      ...config,
                      categories: config.categories.filter((_, itemIndex) => itemIndex !== index),
                    });
                  }}
                >
                  <Trash2 size={15} />
                  <span>删除</span>
                </button>
              </div>
            );
          })}
        </div>
      </section>

      <section className="naming-section naming-preview-section" aria-labelledby="preview-title">
        <div className="naming-section-head">
          <div>
            <span>03</span>
            <h2 id="preview-title">规则预览</h2>
          </div>
          <p>示例不使用真实客户名称或文件内容。</p>
        </div>
        <div className="naming-preview-strip">
          <span>项目</span>
          <code>{example("project", projectCategory)}</code>
        </div>
        <div className="naming-preview-strip">
          <span>公司</span>
          <code>{example("company", companyCategory)}</code>
        </div>
      </section>
    </main>
  );
}
