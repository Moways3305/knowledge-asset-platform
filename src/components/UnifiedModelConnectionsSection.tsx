import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown, Plus } from "lucide-react";
import {
  createModelConnection,
  fetchModelConnections,
  fetchModelUsageAssignments,
  testModelConnection,
  updateModelConnection,
  updateModelUsageAssignments,
} from "../api/modelConnections";
import type {
  ModelConnectionDTO,
  ModelConnectionMutateDTO,
  ModelUsageAssignmentsDTO,
  ModelUsageKey,
} from "../types/modelConnections";
import { ApiError } from "../api/http";

const PROVIDERS = ["deepseek", "kimi", "qwen", "glm", "minimax", "openai", "custom"];
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
  dependency_status: "missing",
  dependency_message: "未设置外部 LLM 默认连接，内容生成和默认项目问答将不可用。",
  remediation_hint: "选择一个已启用且测试通过的外部 LLM 连接并保存。",
};

const autofillWarning = "检测到浏览器自动填充，已恢复表单原值。请手动确认并重新填写连接信息。";

type TestNotice = { tone: "busy" | "success" | "danger"; message: string };

function safeActionError(err: unknown, fallback: string): string {
  if (!(err instanceof ApiError)) return fallback;
  const hint = err.detail?.remediation_hint;
  return typeof hint === "string" && hint.trim() ? `${fallback} ${hint}` : fallback;
}

function providerMark(provider: string | null): string {
  const normalized = provider?.trim();
  if (!normalized) return "LL";
  return normalized.slice(0, 2).toUpperCase();
}

function formatTestTime(connection: ModelConnectionDTO): string | null {
  const raw = connection.last_test_succeeded_at ?? connection.last_test_failed_at;
  if (!raw) return null;
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export default function UnifiedModelConnectionsSection({
  canEdit,
  refreshSignal = 0,
}: {
  canEdit: boolean;
  refreshSignal?: number;
}) {
  const [connections, setConnections] = useState<ModelConnectionDTO[]>([]);
  const [usages, setUsages] = useState<ModelUsageAssignmentsDTO>(emptyUsages);
  const [warning, setWarning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingRef, setEditingRef] = useState<string | null>(null);
  const [form, setForm] = useState<ModelConnectionMutateDTO>(emptyForm());
  const [tests, setTests] = useState<Record<string, TestNotice>>({});
  const panelRef = useRef<HTMLFormElement>(null);
  const effectiveCanEdit = canEdit && !forbidden;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setForbidden(false);
    try {
      const [list, assigned] = await Promise.all([
        fetchModelConnections(),
        fetchModelUsageAssignments(),
      ]);
      setConnections(list.items);
      setUsages(assigned);
      setWarning(list.warning);
    } catch (caught) {
      setConnections([]);
      setUsages(emptyUsages);
      setWarning(null);
      if (caught instanceof ApiError && caught.status === 403) {
        setForbidden(true);
        setError("当前身份没有模型管理权限，此区域保持只读。");
      } else {
        setError("外部 LLM 列表加载失败，请刷新或检查连接服务。");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshSignal]);

  useEffect(() => {
    if (formOpen) panelRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
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
      setError("请填写显示名称和模型名称。");
      return;
    }
    if (!editingRef && (!form.base_url?.trim() || !form.api_key?.trim())) {
      setError("新增外部 LLM 连接需要填写 API 地址和 API key。");
      return;
    }
    if (form.base_url?.trim() && !/^https?:\/\//i.test(form.base_url.trim())) {
      setError("API 地址必须以 http:// 或 https:// 开头。");
      return;
    }
    setBusyAction("form");
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
      setNote(editingRef ? "外部 LLM 连接已更新。" : "外部 LLM 连接已创建。");
      setFormOpen(false);
      await load();
    } catch (caught) {
      setError(safeActionError(caught, "外部 LLM 连接保存失败，请检查连接信息后重试。"));
    } finally {
      setBusyAction(null);
    }
  };

  const toggleConnection = async (connection: ModelConnectionDTO) => {
    const actionKey = `toggle:${connection.model_ref}`;
    setBusyAction(actionKey);
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
    } catch (caught) {
      setError(safeActionError(caught, "外部 LLM 状态更新失败，请先处理默认用途依赖后重试。"));
    } finally {
      setBusyAction(null);
    }
  };

  const runTest = async (connection: ModelConnectionDTO) => {
    const actionKey = `test:${connection.model_ref}`;
    setBusyAction(actionKey);
    setTests((old) => ({
      ...old,
      [connection.model_ref]: { tone: "busy", message: "正在测试连接…" },
    }));
    try {
      const result = await testModelConnection(connection.model_ref);
      setTests((old) => ({
        ...old,
        [connection.model_ref]: {
          tone: result.success ? "success" : "danger",
          message: `${result.message} ${result.remediation_hint} · ${result.duration_ms} ms`,
        },
      }));
    } catch (caught) {
      setTests((old) => ({
        ...old,
        [connection.model_ref]: {
          tone: "danger",
          message: safeActionError(caught, "连接测试未完成，请检查连接配置后重试。"),
        },
      }));
    } finally {
      setBusyAction(null);
    }
  };

  const setUsage = (modelRef: string) => {
    const selected = connections.find((item) => item.model_ref === modelRef) ?? null;
    setUsages((old) => ({
      ...old,
      external_llm_default: selected
        ? {
            model_ref: selected.model_ref,
            display_name: selected.display_name,
            capability_type: selected.capability_type,
          }
        : null,
    }));
  };

  const saveUsages = async () => {
    setBusyAction("usages");
    setError(null);
    try {
      const updated = await updateModelUsageAssignments({
        external_llm_default_ref: usages.external_llm_default?.model_ref,
      });
      setUsages(updated);
      setNote("外部 LLM 默认连接已保存；WeKnora 底座模型和知识库绑定未改变。");
    } catch (caught) {
      setError(safeActionError(caught, "外部 LLM 默认用途保存失败，请确认所选连接已启用。"));
    } finally {
      setBusyAction(null);
    }
  };

  const usageSelect = (label: string, usage: ModelUsageKey) => (
    <label className="mf-usage-field">
      <span>{label}</span>
      <select
        aria-label={label}
        value={usages.external_llm_default?.model_ref ?? ""}
        disabled={!effectiveCanEdit || loading || busyAction === "usages"}
        onChange={(event) => setUsage(event.target.value)}
      >
        <option value="">请选择外部 LLM 连接</option>
        {connections
          .filter((item) => item.enabled && item.available_usages.includes(usage))
          .map((item) => (
            <option key={item.model_ref} value={item.model_ref}>
              {item.display_name} · {item.provider ?? "自定义"}
            </option>
          ))}
      </select>
    </label>
  );

  return (
    <section className="mf-external-panel" aria-labelledby="external-llm-title">
      <div className="mf-panel-heading">
        <div>
          <span className="mf-panel-kicker">KAP DIRECT</span>
          <h3 id="external-llm-title">外部 LLM 连接</h3>
        </div>
        {effectiveCanEdit && (
          <button className="btn-small-primary mf-add-button" onClick={openCreate} type="button">
            <Plus size={14} aria-hidden="true" />
            新增外部 LLM
          </button>
        )}
      </div>

      {!canEdit && !forbidden && (
        <div className="mf-inline-message">当前身份仅可查看，修改需系统管理员。</div>
      )}
      {error && (
        <div className="mf-inline-message is-danger" role="alert">
          {error}
        </div>
      )}
      {warning && <div className="mf-inline-message is-warning">{warning}</div>}
      {note && <div className="mf-inline-message is-success">{note}</div>}

      <div className="mf-usage-card" aria-label="外部 LLM 默认用途">
        <div className="mf-usage-copy">
          <strong>默认用途</strong>
          <span>KAP 直接调用同一条 OpenAI-compatible 连接，不经过 WeKnora。</span>
        </div>
        <div className="mf-usage-grid">
          {usageSelect("内容生成默认模型", "content_generation")}
          {usageSelect("项目问答默认模型", "project_qa")}
        </div>
        {usages.dependency_status === "missing" && (
          <div className="mf-dependency-note">
            {usages.dependency_message} {usages.remediation_hint}
          </div>
        )}
        {effectiveCanEdit && (
          <div className="mf-usage-actions">
            <button
              className="btn-small-primary"
              onClick={() => void saveUsages()}
              disabled={loading || busyAction === "usages"}
              type="button"
            >
              {busyAction === "usages" ? "保存中…" : "保存默认用途"}
            </button>
          </div>
        )}
      </div>

      <div className="mf-connection-stack">
        {loading ? (
          <div className="mf-empty-state">正在加载外部 LLM 连接…</div>
        ) : connections.length === 0 ? (
          <div className="mf-empty-state">
            <strong>尚未配置外部 LLM 连接</strong>
            <span>新增连接后，可将其用于内容生成和项目问答。</span>
            {effectiveCanEdit && (
              <button className="btn-small-primary" onClick={openCreate} type="button">
                新增外部 LLM
              </button>
            )}
          </div>
        ) : (
          connections.map((connection, index) => {
            const time = formatTestTime(connection);
            const testNotice = tests[connection.model_ref];
            const status = !connection.enabled
              ? "已停用"
              : connection.health_status === "healthy"
                ? "连接正常"
                : connection.health_status === "unhealthy"
                  ? "连接异常"
                  : "未测试";
            return (
              <details className="mf-connection-card" key={connection.model_ref} open={index === 0}>
                <summary>
                  <span className="mf-provider-mark" aria-hidden="true">
                    {providerMark(connection.provider)}
                  </span>
                  <span className="mf-connection-title">
                    <strong>{connection.display_name}</strong>
                    <small>
                      {connection.provider ?? "自定义"} · {connection.model_name}
                    </small>
                  </span>
                  <span
                    className={`mf-health ${connection.enabled && connection.health_status === "healthy" ? "is-healthy" : connection.enabled && connection.health_status === "unhealthy" ? "is-unhealthy" : ""}`}
                  >
                    {status}
                    {time && <small>最近测试 {time}</small>}
                  </span>
                  <ChevronDown className="mf-chevron" size={16} aria-hidden="true" />
                </summary>
                <div className="mf-connection-body">
                  <dl className="mf-connection-facts">
                    <div>
                      <dt>Provider</dt>
                      <dd>{connection.provider ?? "自定义"}</dd>
                    </div>
                    <div>
                      <dt>模型名称</dt>
                      <dd>{connection.model_name}</dd>
                    </div>
                    <div>
                      <dt>API 地址 / API key</dt>
                      <dd>已安全保存，不回显</dd>
                    </div>
                    <div>
                      <dt>可用于</dt>
                      <dd>
                        {connection.available_usages.map((item) => usageLabel[item]).join("、")}
                      </dd>
                    </div>
                  </dl>
                  {testNotice && (
                    <div className={`mf-test-result is-${testNotice.tone}`} role="status">
                      {testNotice.message}
                    </div>
                  )}
                  {effectiveCanEdit && (
                    <div className="mf-card-actions">
                      <button
                        className="btn-small"
                        onClick={() => void runTest(connection)}
                        disabled={busyAction === `test:${connection.model_ref}`}
                        type="button"
                      >
                        {busyAction === `test:${connection.model_ref}` ? "测试中…" : "测试连接"}
                      </button>
                      <button
                        className="btn-small"
                        onClick={() => openEdit(connection)}
                        type="button"
                      >
                        编辑
                      </button>
                      <button
                        className="btn-small"
                        onClick={() => void toggleConnection(connection)}
                        disabled={busyAction === `toggle:${connection.model_ref}`}
                        type="button"
                      >
                        {busyAction === `toggle:${connection.model_ref}`
                          ? "处理中…"
                          : connection.enabled
                            ? "停用"
                            : "启用"}
                      </button>
                    </div>
                  )}
                </div>
              </details>
            );
          })
        )}
      </div>

      {formOpen && effectiveCanEdit && (
        <div className="mf-connection-editor">
          <div className="mf-editor-heading">
            <div>
              <strong>{editingRef ? "编辑外部 LLM" : "新增外部 LLM"}</strong>
              <span>地址和密钥仅单向写入；编辑时留空即保持原值。</span>
            </div>
            <button className="btn-small" onClick={() => setFormOpen(false)} type="button">
              关闭
            </button>
          </div>
          <form
            key={editingRef ?? "create"}
            className="ws-form-grid mf-form-grid"
            autoComplete="off"
            onSubmit={(event) => event.preventDefault()}
            ref={panelRef}
          >
            <FormField label="显示名称">
              <input
                data-model-field="display_name"
                autoComplete="off"
                value={form.display_name}
                onChange={(event) => setForm({ ...form, display_name: event.target.value })}
              />
            </FormField>
            <FormField label="模型能力">
              <select data-model-field="capability_type" value={form.capability_type} disabled>
                <option value="chat">对话（OpenAI 兼容）</option>
              </select>
            </FormField>
            <FormField label="Provider">
              <select
                data-model-field="provider"
                value={form.provider}
                onChange={(event) => setForm({ ...form, provider: event.target.value })}
              >
                {PROVIDERS.map((provider) => (
                  <option key={provider}>{provider}</option>
                ))}
              </select>
            </FormField>
            <FormField label="模型名称">
              <input
                data-model-field="model_name"
                autoComplete="off"
                value={form.model_name}
                onChange={(event) => setForm({ ...form, model_name: event.target.value })}
              />
            </FormField>
            <FormField label="API 地址">
              <input
                data-model-field="base_url"
                name="model_connection_endpoint"
                inputMode="url"
                autoComplete="off"
                data-lpignore="true"
                value={form.base_url ?? ""}
                placeholder={editingRef ? "留空表示保持原地址" : "https://api.example.com/v1"}
                onChange={(event) => setForm({ ...form, base_url: event.target.value })}
              />
            </FormField>
            <FormField label="API key">
              <input
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
            </FormField>
            <FormField label="启用状态">
              <select
                data-model-field="enabled"
                value={form.enabled ? "enabled" : "disabled"}
                onChange={(event) =>
                  setForm({ ...form, enabled: event.target.value === "enabled" })
                }
              >
                <option value="enabled">已启用</option>
                <option value="disabled">已停用</option>
              </select>
            </FormField>
          </form>
          <div className="mf-editor-actions">
            <button
              className="btn-small-primary"
              onClick={() => void saveConnection()}
              disabled={busyAction === "form"}
              type="button"
            >
              {busyAction === "form" ? "保存中…" : "保存外部 LLM"}
            </button>
            <button className="btn-small" onClick={() => setFormOpen(false)} type="button">
              取消
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function FormField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="ws-form-field">
      <span className="ws-form-label">{label}</span>
      {children}
    </label>
  );
}
