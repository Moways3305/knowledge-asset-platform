import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/http";
import {
  createGenerationModel,
  deleteGenerationModel,
  fetchGenerationModels,
  testGenerationModel,
  updateGenerationDefaultModel,
  updateGenerationModel,
} from "../api/weknoraModels";
import type {
  GenerationModelCreateRequestDTO,
  GenerationModelOptionDTO,
} from "../types/weknoraAdmin";

const PROVIDERS = ["deepseek", "kimi", "qwen", "glm", "minimax", "openai", "custom"];

const emptyForm = (): GenerationModelCreateRequestDTO => ({
  display_name: "",
  provider: "deepseek",
  model_name: "",
  base_url: "",
  api_key: "",
  enabled: true,
  make_default: false,
});

export default function GenerationModelsSection({ canEdit }: { canEdit: boolean }) {
  const [models, setModels] = useState<GenerationModelOptionDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [editingRef, setEditingRef] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm());
  const [defaultRef, setDefaultRef] = useState("");
  const [testStates, setTestStates] = useState<Record<string, string>>({});
  const panelRef = useRef<HTMLElement>(null);

  const describe = (e: unknown, fallback: string) =>
    e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : fallback;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchGenerationModels();
      setModels(response.items);
      setDefaultRef(response.items.find((item) => item.is_default)?.model_ref ?? "");
    } catch (e) {
      setError(describe(e, "内容生成模型暂时无法加载"));
      setModels([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!formOpen) return;
    window.setTimeout(() => {
      if (typeof panelRef.current?.scrollIntoView === "function") {
        panelRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }, [formOpen, editingRef]);

  const openCreate = () => {
    setEditingRef(null);
    setForm(emptyForm());
    setError(null);
    setFormOpen(true);
  };

  const openEdit = (model: GenerationModelOptionDTO) => {
    setEditingRef(model.model_ref);
    setForm({
      display_name: model.display_name,
      provider: model.provider,
      model_name: model.model_name,
      base_url: "",
      api_key: "",
      enabled: model.enabled,
      make_default: false,
    });
    setError(null);
    setFormOpen(true);
  };

  const save = async () => {
    setError(null);
    if (!form.display_name.trim() || !form.model_name.trim()) {
      setError("请填写显示名称和模型名称");
      return;
    }
    if (!editingRef && (!form.base_url.trim() || !form.api_key.trim())) {
      setError("新增模型需要填写 API 地址和 API key");
      return;
    }
    if (form.base_url.trim() && !/^https?:\/\//i.test(form.base_url.trim())) {
      setError("API 地址必须以 http:// 或 https:// 开头");
      return;
    }
    setBusy(true);
    try {
      if (editingRef) {
        await updateGenerationModel(editingRef, {
          display_name: form.display_name.trim(),
          provider: form.provider,
          model_name: form.model_name.trim(),
          base_url: form.base_url.trim() || undefined,
          api_key: form.api_key.trim() || undefined,
          enabled: form.enabled,
        });
        setNote("内容生成模型已更新");
      } else {
        await createGenerationModel({
          ...form,
          display_name: form.display_name.trim(),
          model_name: form.model_name.trim(),
          base_url: form.base_url.trim(),
          api_key: form.api_key,
        });
        setNote("内容生成模型已创建");
      }
      setForm(emptyForm());
      setFormOpen(false);
      await load();
    } catch (e) {
      setError(describe(e, "保存内容生成模型失败"));
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (model: GenerationModelOptionDTO) => {
    setError(null);
    try {
      await updateGenerationModel(model.model_ref, {
        display_name: model.display_name,
        provider: model.provider,
        model_name: model.model_name,
        enabled: !model.enabled,
      });
      await load();
    } catch (e) {
      setError(describe(e, "更新模型状态失败"));
    }
  };

  const remove = async (model: GenerationModelOptionDTO) => {
    setError(null);
    try {
      await deleteGenerationModel(model.model_ref);
      setNote(`内容生成模型「${model.display_name}」已删除`);
      await load();
    } catch (e) {
      setError(describe(e, "删除内容生成模型失败"));
    }
  };

  const saveDefault = async () => {
    setBusy(true);
    setError(null);
    try {
      await updateGenerationDefaultModel({ model_ref: defaultRef || null });
      setNote(defaultRef ? "平台默认内容生成模型已保存" : "平台默认内容生成模型已清空");
      await load();
    } catch (e) {
      setError(describe(e, "保存默认内容生成模型失败"));
    } finally {
      setBusy(false);
    }
  };

  const runTest = async (model: GenerationModelOptionDTO) => {
    setTestStates((old) => ({ ...old, [model.model_ref]: "测试中…" }));
    try {
      const result = await testGenerationModel(model.model_ref);
      setTestStates((old) => ({
        ...old,
        [model.model_ref]: `${result.message}（${result.duration_ms} ms）`,
      }));
    } catch (e) {
      setTestStates((old) => ({
        ...old,
        [model.model_ref]: describe(e, "连接测试失败"),
      }));
    }
  };

  return (
    <>
      <section className="ws-section">
        <div className="ig-toolbar">
          <div>
            <h3 style={{ margin: 0 }}>内容生成模型</h3>
            <p className="au-note">
              仅用于上传后的标题、摘要、标签和内容建议，不参与 WeKnora 的 embedding、rerank 或
              KnowledgeQA 初始化。
            </p>
          </div>
          {canEdit && (
            <button className="btn-small-primary" onClick={openCreate}>
              新增内容生成模型
            </button>
          )}
        </div>
        {error && (
          <div
            className="ws-note-hint"
            role="alert"
            style={{ color: "var(--color-danger-fg, #b00)" }}
          >
            {error}
          </div>
        )}
        {note && (
          <div className="ws-note-hint" style={{ color: "var(--color-success-fg, #176)" }}>
            {note}
          </div>
        )}
        {loading ? (
          <div className="ig-empty-state">加载中…</div>
        ) : models.length === 0 ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">尚未配置内容生成模型</div>
            <p className="ig-empty-desc">上传仍可继续，摘要将等待生成或由人工补充。</p>
            {canEdit && (
              <button className="btn-small-primary" onClick={openCreate}>
                新增内容生成模型
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="ws-table-wrap">
              <table className="ws-table">
                <thead>
                  <tr>
                    <th>显示名称</th>
                    <th>provider / 模型</th>
                    <th>状态</th>
                    <th>连接状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((model) => (
                    <tr key={model.model_ref}>
                      <td>
                        {model.display_name}
                        {model.is_default && <span className="ws-cell-project">（平台默认）</span>}
                      </td>
                      <td>
                        {model.provider} · {model.model_name}
                      </td>
                      <td>{model.enabled ? "已启用" : "已停用"}</td>
                      <td>{testStates[model.model_ref] ?? "未测试"}</td>
                      <td className="ws-cell-actions">
                        {canEdit && (
                          <>
                            <button className="btn-small" onClick={() => void runTest(model)}>
                              测试连接
                            </button>
                            <button className="btn-small" onClick={() => openEdit(model)}>
                              编辑
                            </button>
                            <button className="btn-small" onClick={() => void toggle(model)}>
                              {model.enabled ? "停用" : "启用"}
                            </button>
                            <button
                              className="btn-small btn-small-danger"
                              onClick={() => void remove(model)}
                            >
                              删除
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="ws-form-grid" style={{ marginTop: 16 }}>
              <label className="ws-form-field">
                <span className="ws-form-label">平台默认内容生成模型</span>
                <select
                  className="ws-form-input"
                  aria-label="平台默认内容生成模型"
                  value={defaultRef}
                  disabled={!canEdit}
                  onChange={(e) => setDefaultRef(e.target.value)}
                >
                  <option value="">（清空默认）</option>
                  {models
                    .filter((model) => model.enabled)
                    .map((model) => (
                      <option key={model.model_ref} value={model.model_ref}>
                        {model.display_name}
                      </option>
                    ))}
                </select>
              </label>
            </div>
            {canEdit && (
              <div className="ws-form-actions">
                <button
                  className="btn-small-primary"
                  disabled={busy}
                  onClick={() => void saveDefault()}
                >
                  {busy ? "保存中…" : "保存默认模型"}
                </button>
              </div>
            )}
          </>
        )}
      </section>

      {formOpen && (
        <section className="ws-section" ref={panelRef}>
          <div className="ws-detail-panel">
            <div className="ws-detail-head">
              <span className="ws-detail-title">
                {editingRef ? "编辑内容生成模型" : "新增内容生成模型"}
              </span>
              <button className="btn-small" onClick={() => setFormOpen(false)} disabled={busy}>
                关闭
              </button>
            </div>
            <form className="ws-form-grid" autoComplete="off" onSubmit={(e) => e.preventDefault()}>
              <input
                name="generation_model_username_decoy"
                tabIndex={-1}
                autoComplete="username"
                aria-hidden="true"
                style={{ position: "absolute", left: "-10000px" }}
              />
              <input
                name="generation_model_password_decoy"
                type="password"
                tabIndex={-1}
                autoComplete="new-password"
                aria-hidden="true"
                style={{ position: "absolute", left: "-10000px" }}
              />
              <label className="ws-form-field">
                <span className="ws-form-label">显示名称</span>
                <input
                  className="ws-form-input"
                  value={form.display_name}
                  onChange={(e) => setForm({ ...form, display_name: e.target.value })}
                />
              </label>
              <label className="ws-form-field">
                <span className="ws-form-label">provider</span>
                <select
                  className="ws-form-input"
                  value={form.provider}
                  onChange={(e) => setForm({ ...form, provider: e.target.value })}
                >
                  {PROVIDERS.map((provider) => (
                    <option key={provider}>{provider}</option>
                  ))}
                </select>
              </label>
              <label className="ws-form-field">
                <span className="ws-form-label">模型名称</span>
                <input
                  className="ws-form-input"
                  value={form.model_name}
                  onChange={(e) => setForm({ ...form, model_name: e.target.value })}
                />
              </label>
              <label className="ws-form-field">
                <span className="ws-form-label">API 地址</span>
                <input
                  className="ws-form-input"
                  name="generation_model_endpoint"
                  autoComplete="off"
                  data-lpignore="true"
                  inputMode="url"
                  value={form.base_url}
                  placeholder={editingRef ? "留空表示保持原地址" : "https://api.example.com/v1"}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                />
              </label>
              <label className="ws-form-field">
                <span className="ws-form-label">API key</span>
                <input
                  className="ws-form-input"
                  name="generation_model_secret"
                  type="password"
                  autoComplete="new-password"
                  data-lpignore="true"
                  data-1p-ignore="true"
                  value={form.api_key}
                  placeholder={editingRef ? "留空表示保持原密钥" : "保存后不再显示"}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                />
              </label>
              <label className="ws-form-field">
                <span className="ws-form-label">启用状态</span>
                <select
                  className="ws-form-input"
                  value={form.enabled ? "enabled" : "disabled"}
                  onChange={(e) => setForm({ ...form, enabled: e.target.value === "enabled" })}
                >
                  <option value="enabled">已启用</option>
                  <option value="disabled">已停用</option>
                </select>
              </label>
              {!editingRef && (
                <label className="ws-form-field">
                  <span className="ws-form-label">默认模型</span>
                  <input
                    type="checkbox"
                    checked={form.make_default}
                    onChange={(e) => setForm({ ...form, make_default: e.target.checked })}
                  />
                  创建后设为平台默认
                </label>
              )}
            </form>
            <div className="ws-form-actions">
              <button className="btn-small-primary" disabled={busy} onClick={() => void save()}>
                {busy ? "保存中…" : "保存内容生成模型"}
              </button>
              <button className="btn-small" disabled={busy} onClick={() => setFormOpen(false)}>
                取消
              </button>
            </div>
          </div>
        </section>
      )}
    </>
  );
}
