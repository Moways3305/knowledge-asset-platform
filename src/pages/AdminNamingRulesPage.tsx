import { useEffect, useMemo, useState } from "react";
import { BookType, Plus, RefreshCw, Send } from "lucide-react";
import { ApiError } from "../api/http";
import { fetchNamingRuleCenter, publishNamingRuleDraft, saveNamingRuleDraft } from "../api/naming";
import type { NamingCategoryConfigDTO, NamingRuleCenterDTO } from "../types/naming";
import "./AdminNamingRulesPage.css";

const levels = ["L1", "L2", "L3", "L4"];

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
    try {
      const draft = await saveNamingRuleDraft(center.published.version, config);
      setCenter({ ...center, draft });
      setNotice("草稿已保存，尚未影响新入库资料。");
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
                <label className="naming-inline-check">
                  <input
                    type="checkbox"
                    checked={row.enabled}
                    onChange={(e) => patchRow({ enabled: e.target.checked })}
                  />
                  启用
                </label>
              </article>
            );
          })}
        </div>
      </section>

      <section className="naming-section" aria-labelledby="category-title">
        <div className="naming-section-head">
          <div>
            <span>02</span>
            <h2 id="category-title">目录类别</h2>
          </div>
          <button
            className="btn-secondary"
            type="button"
            onClick={() =>
              updateConfig({
                ...config,
                categories: [
                  ...config.categories,
                  {
                    id: crypto.randomUUID(),
                    scope: "project",
                    primary: "项目资料",
                    secondary: "交付件",
                    prefix: "项目资料-交付件",
                    default_confidentiality: "L2",
                    enabled: true,
                    sort_order: config.categories.length * 10 + 10,
                  },
                ],
              })
            }
          >
            <Plus size={15} />
            新增类别
          </button>
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
              <div className="naming-category-row" key={category.id}>
                <select
                  aria-label="适用库范围"
                  value={category.scope}
                  onChange={(e) =>
                    patchCategory({ scope: e.target.value as "project" | "company" })
                  }
                >
                  <option value="project">项目库</option>
                  <option value="company">公司库</option>
                </select>
                <input
                  aria-label="一级类"
                  value={category.primary}
                  onChange={(e) => patchCategory({ primary: e.target.value })}
                />
                <input
                  aria-label="二级类"
                  value={category.secondary}
                  onChange={(e) => patchCategory({ secondary: e.target.value })}
                />
                <input
                  aria-label="规范前缀"
                  value={category.prefix}
                  onChange={(e) => patchCategory({ prefix: e.target.value })}
                />
                <select
                  aria-label="默认密级"
                  value={category.default_confidentiality}
                  onChange={(e) => patchCategory({ default_confidentiality: e.target.value })}
                >
                  {levels.map((level) => (
                    <option key={level}>{level}</option>
                  ))}
                </select>
                <input
                  aria-label="显示排序"
                  type="number"
                  min={0}
                  max={10000}
                  value={category.sort_order}
                  onChange={(e) => patchCategory({ sort_order: Number(e.target.value) })}
                />
                <label className="naming-inline-check">
                  <input
                    type="checkbox"
                    checked={category.enabled}
                    onChange={(e) => patchCategory({ enabled: e.target.checked })}
                  />
                  启用
                </label>
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
