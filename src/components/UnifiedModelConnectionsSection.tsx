import { useCallback, useEffect, useRef, useState } from "react";
import {
  createModelConnection,
  fetchModelConnections,
  fetchModelUsageAssignments,
  testModelConnection,
  updateModelConnection,
  updateModelUsageAssignments,
} from "../api/weknoraModels";
import type {
  ModelCapabilityType,
  ModelConnectionDTO,
  ModelConnectionMutateDTO,
  ModelUsageAssignmentsDTO,
  ModelUsageKey,
} from "../types/weknoraAdmin";
import { PageSection, PageToolbar, SettingsRow } from "./ProductLayout";

const PROVIDERS = ["deepseek", "kimi", "qwen", "glm", "minimax", "openai", "custom"];
const capabilityLabel: Record<ModelCapabilityType, string> = {
  chat: "对话",
  embedding: "嵌入",
  rerank: "重排",
};
const usageLabel: Record<ModelUsageKey, string> = {
  content_generation: "内容生成",
  knowledge_embedding: "知识库嵌入",
  knowledge_chat: "知识库问答",
  knowledge_rerank: "知识库重排",
};

const emptyForm = (): ModelConnectionMutateDTO => ({
  display_name: "",
  capability_type: "chat",
  provider: "deepseek",
  model_name: "",
  base_url: "",
  api_key: "",
  enabled: true,
});

const emptyUsages: ModelUsageAssignmentsDTO = {
  content_generation: null,
  knowledge_embedding: null,
  knowledge_chat: null,
  knowledge_rerank: null,
};

const autofillWarning = "检测到浏览器自动填充，已恢复表单原值。请手动确认并重新填写连接信息。";

export default function UnifiedModelConnectionsSection({ canEdit }: { canEdit: boolean }) {
  const [connections, setConnections] = useState<ModelConnectionDTO[]>([]);
  const [usages, setUsages] = useState<ModelUsageAssignmentsDTO>(emptyUsages);
  const [warning, setWarning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [editingRef, setEditingRef] = useState<string | null>(null);
  const [form, setForm] = useState<ModelConnectionMutateDTO>(emptyForm());
  const [tests, setTests] = useState<Record<string, string>>({});
  const panelRef = useRef<HTMLFormElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, assigned] = await Promise.all([
        fetchModelConnections(),
        fetchModelUsageAssignments(),
      ]);
      setConnections(list.items);
      setUsages(assigned);
      setWarning(list.warning);
    } catch {
      setConnections([]);
      setUsages(emptyUsages);
      setError("模型列表加载失败，请刷新或检查模型连接");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (formOpen) panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [formOpen]);

  const reconcileExternalValues = useCallback(
    (showWarning = true) => {
      const root = panelRef.current;
      if (!root) return false;
      const expected: Record<string, string> = {
        display_name: form.display_name,
        capability_type: form.capability_type,
        provider: form.provider,
        model_name: form.model_name,
        base_url: form.base_url ?? "",
        api_key: form.api_key ?? "",
        enabled: form.enabled ? "enabled" : "disabled",
      };
      let restored = false;
      for (const [field, value] of Object.entries(expected)) {
        const control = root.querySelector<HTMLInputElement | HTMLSelectElement>(
          `[data-model-field="${field}"]`,
        );
        if (control && control.value !== value) {
          control.value = value;
          restored = true;
        }
      }
      if (restored && showWarning) setError(autofillWarning);
      return restored;
    },
    [form],
  );

  useEffect(() => {
    if (!formOpen) return;
    const timer = window.setInterval(() => reconcileExternalValues(), 150);
    const handleAutofillSignal = () => reconcileExternalValues();
    const panel = panelRef.current;
    panel?.addEventListener("animationstart", handleAutofillSignal);
    return () => {
      window.clearInterval(timer);
      panel?.removeEventListener("animationstart", handleAutofillSignal);
    };
  }, [formOpen, reconcileExternalValues]);

  const openCreate = () => {
    setEditingRef(null);
    setForm(emptyForm());
    setError(null);
    setFormOpen(true);
  };

  const openEdit = (connection: ModelConnectionDTO) => {
    setEditingRef(connection.model_ref);
    setForm({
      display_name: connection.display_name,
      capability_type: connection.capability_type,
      provider: connection.provider ?? "custom",
      model_name: connection.model_name,
      base_url: "",
      api_key: "",
      enabled: connection.enabled,
    });
    setError(null);
    setFormOpen(true);
  };

  const saveConnection = async () => {
    if (reconcileExternalValues()) return;
    if (!form.display_name.trim() || !form.model_name.trim()) {
      setError("请填写显示名称和模型名称");
      return;
    }
    if (!editingRef && (!form.base_url?.trim() || !form.api_key?.trim())) {
      setError("新增模型连接需要填写 API 地址和 API key");
      return;
    }
    if (form.base_url?.trim() && !/^https?:\/\//i.test(form.base_url.trim())) {
      setError("API 地址必须以 http:// 或 https:// 开头");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload = { ...form };
      if (editingRef) {
        if (!payload.base_url?.trim()) delete payload.base_url;
        if (!payload.api_key?.trim()) delete payload.api_key;
        await updateModelConnection(editingRef, payload);
      } else {
        await createModelConnection(payload);
      }
      setNote(editingRef ? "模型连接已更新" : "模型连接已创建");
      setFormOpen(false);
      await load();
    } catch {
      setError("模型连接保存失败，请检查连接信息后重试");
    } finally {
      setBusy(false);
    }
  };

  const toggleConnection = async (connection: ModelConnectionDTO) => {
    setBusy(true);
    setError(null);
    try {
      await updateModelConnection(connection.model_ref, {
        display_name: connection.display_name,
        capability_type: connection.capability_type,
        provider: connection.provider ?? "custom",
        model_name: connection.model_name,
        enabled: !connection.enabled,
      });
      await load();
    } catch {
      setError("模型状态更新失败；如该模型正在用于平台默认用途，请先调整用途分配");
    } finally {
      setBusy(false);
    }
  };

  const runTest = async (connection: ModelConnectionDTO) => {
    setTests((old) => ({ ...old, [connection.model_ref]: "测试中…" }));
    try {
      const result = await testModelConnection(connection.model_ref);
      setTests((old) => ({
        ...old,
        [connection.model_ref]: `${result.success ? "连接正常" : "连接失败"} · ${result.duration_ms} ms`,
      }));
    } catch {
      setTests((old) => ({ ...old, [connection.model_ref]: "测试失败，请检查模型连接" }));
    }
  };

  const setUsage = (key: keyof ModelUsageAssignmentsDTO, modelRef: string) => {
    const selected = connections.find((item) => item.model_ref === modelRef) ?? null;
    setUsages((old) => ({
      ...old,
      [key]: selected
        ? {
            model_ref: selected.model_ref,
            display_name: selected.display_name,
            capability_type: selected.capability_type,
          }
        : null,
    }));
  };

  const saveUsages = async () => {
    setBusy(true);
    setError(null);
    try {
      const updated = await updateModelUsageAssignments({
        content_generation_ref: usages.content_generation?.model_ref,
        knowledge_embedding_ref: usages.knowledge_embedding?.model_ref,
        knowledge_chat_ref: usages.knowledge_chat?.model_ref,
        knowledge_rerank_ref: usages.knowledge_rerank?.model_ref,
      });
      setUsages(updated);
      setNote("模型用途已保存；已有知识库的嵌入模型保持原绑定");
    } catch {
      setError("模型用途保存失败，请确认所选模型已启用且能力匹配");
    } finally {
      setBusy(false);
    }
  };

  const usageRow = (
    key: keyof ModelUsageAssignmentsDTO,
    title: string,
    description: string,
    usage: ModelUsageKey,
    optional = false,
  ) => (
    <SettingsRow
      title={title}
      description={description}
      disabledReason={!canEdit ? "当前身份仅可查看，修改需系统管理员。" : undefined}
      control={
        <select
          aria-label={title}
          value={usages[key]?.model_ref ?? ""}
          disabled={!canEdit || loading}
          onChange={(event) => setUsage(key, event.target.value)}
        >
          <option value="">{optional ? "暂不设置" : "请选择模型连接"}</option>
          {connections
            .filter((item) => item.enabled && item.available_usages.includes(usage))
            .map((item) => (
              <option key={item.model_ref} value={item.model_ref}>
                {item.display_name} · {item.provider ?? "自定义"}
              </option>
            ))}
        </select>
      }
    />
  );

  return (
    <>
      <PageSection
        title="模型用途"
        description="同一个对话模型可同时用于内容生成和知识库问答，不需要重复录入密钥。"
      >
        {error && (
          <div className="product-inline-note is-danger" role="alert">
            {error}
          </div>
        )}
        {warning && <div className="product-inline-note is-warning">{warning}</div>}
        {note && <div className="product-inline-note">{note}</div>}
        <div className="product-settings-list">
          {usageRow(
            "content_generation",
            "内容生成",
            "上传后的标题、摘要、标签和内容建议。",
            "content_generation",
          )}
          {usageRow(
            "knowledge_embedding",
            "知识库默认嵌入",
            "创建新知识库时的向量模型；已有库保持原绑定。",
            "knowledge_embedding",
          )}
          {usageRow(
            "knowledge_chat",
            "知识库默认问答",
            "知识库初始化和问答能力使用的默认模型。",
            "knowledge_chat",
          )}
          {usageRow(
            "knowledge_rerank",
            "默认重排",
            "改善检索排序；不配置时使用知识库默认策略。",
            "knowledge_rerank",
            true,
          )}
        </div>
        {canEdit && (
          <PageToolbar
            end={
              <button
                className="btn-small-primary"
                onClick={() => void saveUsages()}
                disabled={busy || loading}
              >
                {busy ? "保存中…" : "保存模型用途"}
              </button>
            }
          />
        )}
      </PageSection>

      <PageSection
        title="模型连接"
        description="统一维护模型能力、Provider 和连接状态；API 地址与密钥保存后不再显示。"
        actions={
          canEdit ? (
            <button className="btn-small-primary" onClick={openCreate}>
              新增模型连接
            </button>
          ) : undefined
        }
      >
        {loading ? (
          <div className="ig-empty-state">正在加载模型连接…</div>
        ) : connections.length === 0 ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">尚未配置模型连接</div>
            <p className="ig-empty-desc">添加连接后，可在上方为内容生成和知识库分配用途。</p>
          </div>
        ) : (
          <div className="ws-table-wrap">
            <table className="ws-table">
              <thead>
                <tr>
                  <th>模型名称</th>
                  <th>能力</th>
                  <th>Provider</th>
                  <th>状态</th>
                  <th>可用于</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {connections.map((connection) => (
                  <tr key={connection.model_ref}>
                    <td>
                      {connection.display_name}
                      <div className="ws-cell-project">{connection.model_name}</div>
                    </td>
                    <td>{capabilityLabel[connection.capability_type]}</td>
                    <td>{connection.provider ?? "—"}</td>
                    <td>
                      <span
                        className={`ws-status-pill ${connection.enabled ? "ws-status-on" : "ws-status-off"}`}
                      >
                        {connection.enabled ? (tests[connection.model_ref] ?? "已启用") : "已停用"}
                      </span>
                    </td>
                    <td>
                      {connection.available_usages.map((usage) => usageLabel[usage]).join("、")}
                    </td>
                    <td className="ws-cell-actions">
                      {canEdit && (
                        <>
                          <button className="btn-small" onClick={() => void runTest(connection)}>
                            测试连接
                          </button>
                          <button className="btn-small" onClick={() => openEdit(connection)}>
                            编辑
                          </button>
                          <button
                            className="btn-small"
                            disabled={busy}
                            onClick={() => void toggleConnection(connection)}
                          >
                            {connection.enabled ? "停用" : "启用"}
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageSection>

      {formOpen && (
        <PageSection
          className="ws-section"
          title={editingRef ? "编辑模型连接" : "新增模型连接"}
          actions={
            <button className="btn-small" onClick={() => setFormOpen(false)} disabled={busy}>
              关闭
            </button>
          }
        >
          <form
            key={editingRef ?? "create"}
            className="ws-form-grid"
            autoComplete="off"
            onSubmit={(event) => event.preventDefault()}
            ref={panelRef}
          >
            <label className="ws-form-field">
              <span className="ws-form-label">显示名称</span>
              <input
                className="ws-form-input"
                data-model-field="display_name"
                autoComplete="off"
                value={form.display_name}
                onChange={(event) => setForm({ ...form, display_name: event.target.value })}
              />
            </label>
            <label className="ws-form-field">
              <span className="ws-form-label">模型能力</span>
              <select
                className="ws-form-input"
                data-model-field="capability_type"
                value={form.capability_type}
                disabled={Boolean(editingRef)}
                onChange={(event) =>
                  setForm({ ...form, capability_type: event.target.value as ModelCapabilityType })
                }
              >
                <option value="chat">对话</option>
                <option value="embedding">嵌入</option>
                <option value="rerank">重排</option>
              </select>
            </label>
            <label className="ws-form-field">
              <span className="ws-form-label">Provider</span>
              <select
                className="ws-form-input"
                data-model-field="provider"
                value={form.provider}
                onChange={(event) => setForm({ ...form, provider: event.target.value })}
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
                data-model-field="model_name"
                autoComplete="off"
                value={form.model_name}
                onChange={(event) => setForm({ ...form, model_name: event.target.value })}
              />
            </label>
            <label className="ws-form-field">
              <span className="ws-form-label">API 地址</span>
              <input
                className="ws-form-input"
                data-model-field="base_url"
                name="model_connection_endpoint"
                inputMode="url"
                autoComplete="off"
                data-lpignore="true"
                value={form.base_url ?? ""}
                placeholder={editingRef ? "留空表示保持原地址" : "https://api.example.com/v1"}
                onChange={(event) => setForm({ ...form, base_url: event.target.value })}
              />
            </label>
            <label className="ws-form-field">
              <span className="ws-form-label">API key</span>
              <input
                className="ws-form-input"
                data-model-field="api_key"
                name="model_connection_secret"
                type="password"
                autoComplete="new-password"
                data-lpignore="true"
                data-1p-ignore="true"
                value={form.api_key ?? ""}
                placeholder={editingRef ? "留空表示保持原密钥" : "保存后不再显示"}
                onChange={(event) => setForm({ ...form, api_key: event.target.value })}
              />
            </label>
            <label className="ws-form-field">
              <span className="ws-form-label">启用状态</span>
              <select
                className="ws-form-input"
                data-model-field="enabled"
                value={form.enabled ? "enabled" : "disabled"}
                onChange={(event) =>
                  setForm({ ...form, enabled: event.target.value === "enabled" })
                }
              >
                <option value="enabled">已启用</option>
                <option value="disabled">已停用</option>
              </select>
            </label>
          </form>
          <PageToolbar
            end={
              <>
                <button
                  className="btn-small-primary"
                  onClick={() => void saveConnection()}
                  disabled={busy}
                >
                  {busy ? "保存中…" : "保存模型连接"}
                </button>
                <button className="btn-small" onClick={() => setFormOpen(false)} disabled={busy}>
                  取消
                </button>
              </>
            }
          />
        </PageSection>
      )}
    </>
  );
}
