import { useCallback, useEffect, useRef, useState } from "react";
import {
  createModelConnection,
  fetchModelConnections,
  fetchModelUsageAssignments,
  testModelConnection,
  updateModelConnection,
  updateModelUsageAssignments,
} from "../api/modelConnections";
import type {
  ModelCapabilityType,
  ModelConnectionDTO,
  ModelConnectionMutateDTO,
  ModelUsageAssignmentsDTO,
  ModelUsageKey,
} from "../types/modelConnections";
import { PageSection, PageToolbar, SettingsRow } from "./ProductLayout";

const PROVIDERS = ["deepseek", "kimi", "qwen", "glm", "minimax", "openai", "custom"];
const capabilityLabel: Record<ModelCapabilityType, string> = {
  chat: "外部对话",
};
const usageLabel: Record<ModelUsageKey, string> = {
  content_generation: "内容生成",
  project_qa: "项目问答",
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
  external_llm_default: null,
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
      setError("外部 LLM 列表加载失败，请刷新或检查连接服务");
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
      setError("新增外部 LLM 连接需要填写 API 地址和 API key");
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
      setNote(editingRef ? "外部 LLM 连接已更新" : "外部 LLM 连接已创建");
      setFormOpen(false);
      await load();
    } catch {
      setError("外部 LLM 连接保存失败，请检查连接信息后重试");
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
      setTests((old) => ({ ...old, [connection.model_ref]: "测试失败，请检查外部 LLM 连接" }));
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
        external_llm_default_ref: usages.external_llm_default?.model_ref,
      });
      setUsages(updated);
      setNote("外部 LLM 默认连接已保存；WeKnora 底座模型和已有知识库绑定未改变");
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
          <option value="">{optional ? "暂不设置" : "请选择外部 LLM 连接"}</option>
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
        title="外部 LLM 默认用途"
        description="默认连接用于内容生成和项目问答；项目问答也可在安全选项中选择其他已启用外部 LLM。"
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
            "external_llm_default",
            "内容生成与项目问答默认模型",
            "KAP 直接调用该 OpenAI-compatible 连接，不经过 WeKnora。",
            "content_generation",
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
                {busy ? "保存中…" : "保存外部 LLM 默认连接"}
              </button>
            }
          />
        )}
      </PageSection>

      <PageSection
        title="外部 LLM 连接"
        description="仅维护 KAP 直接调用的 OpenAI-compatible 对话模型；API 地址与密钥保存后不再显示。"
        actions={
          canEdit ? (
            <button className="btn-small-primary" onClick={openCreate}>
              新增外部 LLM 连接
            </button>
          ) : undefined
        }
      >
        {loading ? (
          <div className="ig-empty-state">正在加载外部 LLM 连接…</div>
        ) : connections.length === 0 ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">尚未配置外部 LLM 连接</div>
            <p className="ig-empty-desc">添加连接后，可将其用于内容生成和项目问答。</p>
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
          title={editingRef ? "编辑外部 LLM 连接" : "新增外部 LLM 连接"}
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
                disabled
              >
                <option value="chat">对话（OpenAI 兼容）</option>
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
                  {busy ? "保存中…" : "保存外部 LLM 连接"}
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
