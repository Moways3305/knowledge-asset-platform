import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown, Plus } from "lucide-react";
import {
  createWeknoraModel,
  deleteWeknoraModel,
  fetchWeknoraModels,
  fetchWeknoraProviders,
  updateWeknoraModel,
  checkWeknoraModel,
} from "../api/admin";
import type { ModelDTO, WeknoraModelMutateDTO, WeknoraProviderDTO } from "../types/weknoraAdmin";
import { ApiError } from "../api/http";
import ConfirmDialog from "./ConfirmDialog";
import TaskModal from "./TaskModal";
import ProviderSelect, { type ProviderSelectOption } from "./ProviderSelect";
import { ProviderLogo } from "./providerIcons";
import {
  getProviderCatalogDescription,
  getProviderCatalogModels,
} from "../constants/providerModelCatalog";

const MODEL_TYPES = ["chat", "embedding", "rerank", "vllm", "asr"];
const modelTypeLabel: Record<string, string> = {
  chat: "对话",
  embedding: "嵌入",
  rerank: "重排",
  vllm: "多模态",
  asr: "语音识别",
};

const emptyForm = (): WeknoraModelMutateDTO => ({
  name: "",
  type: "chat",
  source: "remote",
  provider: "",
  base_url: "",
  api_key: "",
  description: "",
  enabled: true,
});

const autofillWarning = "检测到浏览器自动填充，已恢复表单原值。请手动确认并重新填写模型信息。";

type TestNotice = { tone: "busy" | "success" | "danger"; message: string };

function safeActionError(err: unknown, fallback: string): string {
  if (!(err instanceof ApiError)) return fallback;
  const hint = err.detail?.remediation_hint;
  if (typeof hint === "string" && hint.trim()) return `${fallback} ${hint}`;
  // 422 多为字段校验错误，消息安全且可帮助用户定位问题
  if (err.status === 422) return err.message?.trim() || fallback;
  return fallback;
}

export default function WeknoraModelsSection({
  canEdit,
  refreshSignal = 0,
}: {
  canEdit: boolean;
  refreshSignal?: number;
}) {
  const [models, setModels] = useState<ModelDTO[]>([]);
  const [providers, setProviders] = useState<WeknoraProviderDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [cardStackOpen, setCardStackOpen] = useState(true);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [deleteTarget, setDeleteTarget] = useState<ModelDTO | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingRef, setEditingRef] = useState<string | null>(null);
  const [form, setForm] = useState<WeknoraModelMutateDTO>(emptyForm());
  const [tests, setTests] = useState<Record<string, TestNotice>>({});
  const panelRef = useRef<HTMLFormElement>(null);
  const providerAutofillRef = useRef<string | null>(null);
  const nameListId = useId();
  const effectiveCanEdit = canEdit && !forbidden;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setForbidden(false);
    try {
      const [items, providerItems] = await Promise.all([
        fetchWeknoraModels(),
        fetchWeknoraProviders(),
      ]);
      setModels(items);
      setProviders(providerItems);
    } catch (caught) {
      setModels([]);
      setProviders([]);
      if (caught instanceof ApiError && caught.status === 403) {
        setForbidden(true);
        setError("当前身份没有 WeKnora 模型管理权限，此区域保持只读。");
      } else {
        setError("WeKnora 模型列表加载失败，请刷新或检查连接服务。");
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
        name: form.name,
        type: form.type,
        source: form.source ?? "remote",
        provider: form.provider ?? "",
        base_url: form.base_url ?? "",
        api_key: form.api_key ?? "",
        description: form.description ?? "",
        enabled: form.enabled ? "enabled" : "disabled",
      };
      let restored = false;
      for (const [field, value] of Object.entries(expected)) {
        const control = root.querySelector<HTMLInputElement | HTMLSelectElement>(
          `[data-weknora-field="${field}"]`,
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
    providerAutofillRef.current = null;
    setError(null);
    setFormOpen(true);
  };

  const openEdit = (model: ModelDTO) => {
    setEditingRef(model.model_ref);
    providerAutofillRef.current = null;
    setForm({
      name: model.name,
      type: model.type,
      source: model.source ?? undefined,
      provider: model.provider ?? "",
      base_url: "",
      api_key: "",
      description: model.description ?? "",
      dimension: model.dimension,
      enabled: model.enabled,
    });
    setError(null);
    setFormOpen(true);
  };

  const saveModel = async () => {
    if (reconcileExternalValues()) return;
    if (!form.name.trim()) {
      setError("请填写模型名称。");
      return;
    }
    if (!editingRef && (!form.base_url?.trim() || !form.api_key?.trim())) {
      setError("新增 WeKnora 模型需要填写 API 地址和 API key。");
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
      if (!payload.provider?.trim()) payload.provider = null;
      if (!payload.description?.trim()) payload.description = null;
      if (!payload.dimension) payload.dimension = null;
      if (editingRef) {
        if (!payload.base_url?.trim()) delete payload.base_url;
        if (!payload.api_key?.trim()) delete payload.api_key;
        const result = await updateWeknoraModel(editingRef, payload);
        if (result.credential_status !== "configured" && payload.source === "remote") {
          throw new Error("credential status unconfirmed");
        }
      } else {
        const result = await createWeknoraModel(payload);
        if (result.credential_status !== "configured" && payload.source === "remote") {
          throw new Error("credential status unconfirmed");
        }
      }
      setNote(
        payload.source === "remote"
          ? "凭据已确认保存，请继续执行连通性测试。"
          : "模型配置已保存，请继续执行连通性测试。",
      );
      setFormOpen(false);
      await load();
      setCardStackOpen(true);
    } catch (caught) {
      setError(safeActionError(caught, "WeKnora 模型保存失败，请检查模型信息后重试。"));
    } finally {
      setBusyAction(null);
    }
  };

  const applyProvider = (providerValue: string) => {
    const provider = providers.find((item) => item.value === providerValue);
    const defaultUrl = provider?.default_urls?.[form.type] ?? "";
    const previousBaseUrl = form.base_url?.trim() ?? "";
    const wasAutofilled = providerAutofillRef.current !== null;
    // 只有当前地址为空、或仍是上次自动带出的地址时，才覆盖为新默认地址；
    // 用户手动改过的地址保持不变。
    if (defaultUrl && (!previousBaseUrl || wasAutofilled)) {
      setForm((current) => ({ ...current, provider: providerValue, base_url: defaultUrl }));
      providerAutofillRef.current = defaultUrl;
    } else {
      setForm((current) => ({ ...current, provider: providerValue }));
      providerAutofillRef.current = null;
    }
  };

  const providerOptions = useMemo<ProviderSelectOption[]>(() => {
    const visible = providers.filter((item) => item.model_types.includes(form.type));
    const options: ProviderSelectOption[] = visible.map((item) => ({
      value: item.value,
      label: item.label,
      description:
        getProviderCatalogDescription(item.value, form.type) ?? item.description ?? undefined,
      icon: <ProviderLogo provider={item.value} label={item.label} />,
    }));
    const current = form.provider ?? "";
    if (current && !options.some((option) => option.value === current)) {
      options.unshift({
        value: current,
        label: current,
        icon: <ProviderLogo provider={current} label={current} />,
      });
    }
    return options;
  }, [form.provider, form.type, providers]);

  const nameSuggestions = !editingRef
    ? getProviderCatalogModels(form.provider ?? "", form.type)
    : [];

  const deleteModel = async (model: ModelDTO) => {
    const actionKey = `delete:${model.model_ref}`;
    setBusyAction(actionKey);
    setError(null);
    try {
      await deleteWeknoraModel(model.model_ref);
      setNote("模型已删除。");
      await load();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setError("该模型正被知识库使用，请先更换默认模型后再删除。");
      } else {
        setError(safeActionError(caught, "删除失败，请稍后重试。"));
      }
    } finally {
      setBusyAction(null);
    }
  };

  const runTest = async (model: ModelDTO) => {
    const actionKey = `test:${model.model_ref}`;
    setBusyAction(actionKey);
    setTests((old) => ({
      ...old,
      [model.model_ref]: { tone: "busy", message: "正在测试模型连通性…" },
    }));
    try {
      const result = await checkWeknoraModel({
        model_ref: model.model_ref,
      });
      setTests((old) => ({
        ...old,
        [model.model_ref]: {
          tone: result.success ? "success" : "danger",
          message: result.message,
        },
      }));
    } catch (caught) {
      setTests((old) => ({
        ...old,
        [model.model_ref]: {
          tone: "danger",
          message: safeActionError(caught, "模型连通性测试未完成，请检查配置后重试。"),
        },
      }));
    } finally {
      setBusyAction(null);
    }
  };

  const visibleModels = models.filter((model) => {
    const query = search.trim().toLowerCase();
    const matchesQuery =
      !query ||
      `${model.name} ${model.provider ?? ""} ${modelTypeLabel[model.type] ?? model.type}`
        .toLowerCase()
        .includes(query);
    const matchesType = typeFilter === "all" || model.type === typeFilter;
    const matchesStatus =
      statusFilter === "all" ||
      (statusFilter === "enabled" && model.enabled) ||
      (statusFilter === "disabled" && !model.enabled);
    return matchesQuery && matchesType && matchesStatus;
  });

  return (
    <section className="mf-external-panel" aria-labelledby="weknora-models-title">
      <div className="mf-panel-heading">
        <div>
          <span className="mf-panel-kicker">KAP DIRECT</span>
          <h3 id="weknora-models-title">WeKnora 模型配置</h3>
        </div>
        {effectiveCanEdit && (
          <button className="btn-small-primary mf-add-button" onClick={openCreate} type="button">
            <Plus size={14} aria-hidden="true" />
            新增 WeKnora 模型
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
      {note && <div className="mf-inline-message is-success">{note}</div>}

      <div className="mf-drawer-filters" aria-label="WeKnora 模型筛选">
        <input
          aria-label="搜索 WeKnora 模型"
          placeholder="搜索名称、供应商或类型"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          aria-label="WeKnora 模型类型"
          value={typeFilter}
          onChange={(event) => setTypeFilter(event.target.value)}
        >
          <option value="all">全部类型</option>
          <option value="chat">LLM</option>
          <option value="embedding">嵌入</option>
          <option value="rerank">重排</option>
          <option value="multimodal">多模态</option>
        </select>
        <select
          aria-label="WeKnora 模型状态"
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
        >
          <option value="all">全部状态</option>
          <option value="enabled">已启用</option>
          <option value="disabled">已停用</option>
        </select>
      </div>

      {loading ? (
        <div className="mf-empty-state">正在加载 WeKnora 模型…</div>
      ) : models.length === 0 ? (
        <div className="mf-empty-state">
          <strong>尚未配置 WeKnora 模型</strong>
          <span>新增模型后，WeKnora 知识库底座可使用。</span>
          {effectiveCanEdit && (
            <button className="btn-small-primary" onClick={openCreate} type="button">
              新增 WeKnora 模型
            </button>
          )}
        </div>
      ) : (
        <>
          <button
            className="btn-small mf-collapse-toggle"
            onClick={() => setCardStackOpen(!cardStackOpen)}
            type="button"
            aria-expanded={cardStackOpen}
          >
            <ChevronDown
              size={16}
              style={{
                transform: cardStackOpen ? "rotate(180deg)" : "rotate(0deg)",
                transition: "transform 0.2s",
              }}
            />
            {cardStackOpen ? "收起模型列表" : `展开模型列表（${models.length}）`}
          </button>

          {cardStackOpen && (
            <div className="mf-connection-stack">
              {visibleModels.length === 0 && (
                <div className="mf-empty-state">没有匹配的 WeKnora 模型。</div>
              )}
              {visibleModels.map((model, index) => {
                const testNotice = tests[model.model_ref];
                const statusLabel = !model.enabled ? "已停用" : "已启用";
                return (
                  <details className="mf-connection-card" key={model.model_ref} open={index === 0}>
                    <summary>
                      <span className="mf-provider-mark" aria-hidden="true">
                        {modelTypeLabel[model.type]?.slice(0, 2).toUpperCase() ??
                          model.type.slice(0, 2).toUpperCase()}
                      </span>
                      <span className="mf-connection-title">
                        <strong>{model.name}</strong>
                        <small>
                          {model.provider ?? "未知"} · {modelTypeLabel[model.type] ?? model.type}
                          {model.is_builtin && " · 内置"}
                        </small>
                      </span>
                      <span className={`mf-health ${model.enabled ? "is-healthy" : ""}`}>
                        {statusLabel}
                      </span>
                      <ChevronDown className="mf-chevron" size={16} aria-hidden="true" />
                    </summary>
                    <div className="mf-connection-body">
                      <dl className="mf-connection-facts">
                        <div>
                          <dt>模型类型</dt>
                          <dd>{modelTypeLabel[model.type] ?? model.type}</dd>
                        </div>
                        <div>
                          <dt>来源</dt>
                          <dd>{model.source}</dd>
                        </div>
                        <div>
                          <dt>Provider</dt>
                          <dd>{model.provider ?? "—"}</dd>
                        </div>
                        {model.dimension != null && (
                          <div>
                            <dt>向量维度</dt>
                            <dd>{model.dimension}</dd>
                          </div>
                        )}
                        <div>
                          <dt>凭据与连通性</dt>
                          <dd>
                            {testNotice?.tone === "success"
                              ? "凭据已确认保存，连通性已验证"
                              : testNotice?.tone === "danger"
                                ? "连通性测试失败，可查看安全错误说明后重试"
                                : model.credential_status === "configured"
                                  ? "凭据已确认保存，等待连通性测试"
                                  : model.source === "local"
                                    ? "本地模型无需远程凭据，等待连通性测试"
                                    : "凭据保存状态未确认，请重新配置并测试"}
                          </dd>
                        </div>
                        {model.description && (
                          <div>
                            <dt>描述</dt>
                            <dd>{model.description}</dd>
                          </div>
                        )}
                      </dl>
                      {testNotice && (
                        <div className={`mf-test-result is-${testNotice.tone}`} role="status">
                          {testNotice.message}
                        </div>
                      )}
                      {effectiveCanEdit && !model.is_builtin && (
                        <div className="mf-card-actions">
                          <button
                            className="btn-small"
                            onClick={() => void runTest(model)}
                            disabled={busyAction === `test:${model.model_ref}`}
                            type="button"
                          >
                            {busyAction === `test:${model.model_ref}` ? "测试中…" : "测试连通性"}
                          </button>
                          <button
                            className="btn-small"
                            onClick={() => openEdit(model)}
                            type="button"
                          >
                            编辑
                          </button>
                          <button
                            className="btn-small mf-delete-btn"
                            onClick={() => setDeleteTarget(model)}
                            disabled={busyAction === `delete:${model.model_ref}`}
                            type="button"
                          >
                            {busyAction === `delete:${model.model_ref}` ? "删除中…" : "删除"}
                          </button>
                        </div>
                      )}
                    </div>
                  </details>
                );
              })}
            </div>
          )}
        </>
      )}

      <TaskModal
        open={formOpen && effectiveCanEdit}
        title={editingRef ? "编辑 WeKnora 模型" : "新增 WeKnora 模型"}
        description="地址和密钥仅单向写入；仅在凭据状态已确认时，编辑留空才表示保持原值。"
        onClose={() => setFormOpen(false)}
        busy={busyAction === "form"}
        size="large"
        eyebrow="WeKnora 模型"
        panelClassName="mf-connection-editor"
      >
        <form
          key={editingRef ?? "create"}
          className="ws-form-grid mf-form-grid"
          autoComplete="off"
          onSubmit={(event) => event.preventDefault()}
          ref={panelRef}
        >
          <FormField label="模型名称">
            <input
              data-weknora-field="name"
              autoComplete="off"
              list={nameSuggestions.length > 0 ? nameListId : undefined}
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
            {nameSuggestions.length > 0 && (
              <>
                <datalist id={nameListId}>
                  {nameSuggestions.map((modelName) => (
                    <option key={modelName} value={modelName} />
                  ))}
                </datalist>
                <small className="mf-field-hint">
                  可选：{nameSuggestions.join("、")}（也可手动输入）
                </small>
              </>
            )}
          </FormField>
          <FormField label="模型类型">
            <select
              data-weknora-field="type"
              value={form.type}
              onChange={(event) => setForm({ ...form, type: event.target.value })}
            >
              {MODEL_TYPES.map((t) => (
                <option key={t} value={t}>
                  {modelTypeLabel[t] ?? t}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="来源">
            <select
              data-weknora-field="source"
              value={form.source ?? "remote"}
              onChange={(event) => setForm({ ...form, source: event.target.value })}
            >
              <option value="remote">远程</option>
              <option value="local">本地</option>
            </select>
          </FormField>
          <FormField label="Provider">
            <ProviderSelect
              ariaLabel="模型供应商"
              options={providerOptions}
              value={form.provider ?? ""}
              disabled={busyAction === "form"}
              onChange={applyProvider}
              placeholder="请选择供应商（或自定义）"
            />
            {Boolean(form.base_url?.trim()) && (
              <small className="mf-field-hint">API 地址已按所选供应商自动带出，可手动修改。</small>
            )}
          </FormField>
          <FormField label="API 地址">
            <input
              data-weknora-field="base_url"
              name="weknora_model_endpoint"
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
              data-weknora-field="api_key"
              name="weknora_model_secret"
              type="password"
              autoComplete="new-password"
              data-lpignore="true"
              data-1p-ignore="true"
              value={form.api_key ?? ""}
              placeholder={editingRef ? "留空表示保持原密钥" : "保存后不再显示"}
              onChange={(event) => setForm({ ...form, api_key: event.target.value })}
            />
          </FormField>
          <FormField label="描述">
            <input
              data-weknora-field="description"
              autoComplete="off"
              value={form.description ?? ""}
              placeholder="可选，模型说明"
              onChange={(event) => setForm({ ...form, description: event.target.value })}
            />
          </FormField>
          {form.type === "embedding" && (
            <FormField label="向量维度">
              <input
                type="number"
                value={form.dimension ?? ""}
                placeholder="如 1536"
                onChange={(event) =>
                  setForm({
                    ...form,
                    dimension: event.target.value ? Number(event.target.value) : null,
                  })
                }
              />
            </FormField>
          )}
          <FormField label="启用状态">
            <select
              data-weknora-field="enabled"
              value={form.enabled ? "enabled" : "disabled"}
              onChange={(event) => setForm({ ...form, enabled: event.target.value === "enabled" })}
            >
              <option value="enabled">已启用</option>
              <option value="disabled">已停用</option>
            </select>
          </FormField>
        </form>
        <div className="mf-editor-actions">
          <button
            className="btn-small-primary"
            onClick={() => void saveModel()}
            disabled={busyAction === "form"}
            type="button"
          >
            {busyAction === "form" ? "保存中…" : "保存 WeKnora 模型"}
          </button>
          <button className="btn-small" onClick={() => setFormOpen(false)} type="button">
            取消
          </button>
        </div>
      </TaskModal>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="确认删除此 WeKnora 模型？"
        description="删除后不可恢复。"
        confirmText="删除模型"
        busyText="删除中…"
        busy={busyAction !== null && busyAction.startsWith("delete:")}
        danger
        onConfirm={() => {
          const target = deleteTarget;
          if (!target) return;
          void deleteModel(target).finally(() => setDeleteTarget(null));
        }}
        onCancel={() => setDeleteTarget(null)}
      />
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
