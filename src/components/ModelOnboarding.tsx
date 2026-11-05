import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import { ApiError } from "../api/http";
import {
  createProviderConnection,
  createRegisteredModel,
  fetchProviderCatalog,
  fetchRegistry,
  syncRegisteredModel,
  updateProviderConnection,
  updateRegisteredModel,
  verifyRegisteredModel,
} from "../api/modelRegistry";
import type {
  Capability,
  ConnectionInput,
  ModelUsage,
  ProviderConnection,
  ProviderTemplate,
  RegistryInventory,
  RegistryModel,
  RegistryModelInput,
} from "../types/modelRegistry";
import TaskModal from "./TaskModal";
import { ProviderLogo } from "./providerIcons";
import "./ModelOnboarding.css";

export interface ModelOnboardingHandle {
  create(): void;
  connections(): void;
  edit(model: RegistryModel): void;
  retry(model: RegistryModel): void;
}
const capabilityLabels: Record<Capability, string> = {
  chat: "对话",
  embedding: "嵌入",
  rerank: "重排",
};
const usageLabels: Record<ModelUsage, string> = {
  business: "内容生成与项目问答",
  knowledge: "知识库检索与解析",
};
const emptyInventory: RegistryInventory = { connections: [], models: [] };
const blankModel = (): RegistryModelInput => ({
  request_id: crypto.randomUUID(),
  connection_id: "",
  display_name: "",
  model_name: "",
  capability: "chat",
  dimension: null,
  usages: ["business"],
});
const safeError = (error: unknown) =>
  error instanceof ApiError ? error.message : "操作未完成，请刷新配置后重试。";

export default function ModelOnboarding({
  managementRef,
  onInventory,
  onChanged,
  refreshSignal,
  canEdit,
}: {
  managementRef: Ref<ModelOnboardingHandle>;
  onInventory: (inventory: RegistryInventory) => void;
  onChanged: () => void | Promise<void>;
  refreshSignal: number;
  canEdit: boolean;
}) {
  const [inventory, setInventory] = useState(emptyInventory);
  const [providers, setProviders] = useState<ProviderTemplate[]>([]);
  const [view, setView] = useState<"model" | "connections" | "connection" | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [editing, setEditing] = useState<RegistryModel | null>(null);
  const resultRef = useRef<HTMLElement>(null);
  const [result, setResult] = useState<RegistryModel | null>(null);
  const [form, setForm] = useState<RegistryModelInput>(blankModel);
  const [connection, setConnection] = useState<ProviderConnection | null>(null);
  const [connectionForm, setConnectionForm] = useState<ConnectionInput>({
    name: "",
    provider: "deepseek",
    api_key: "",
    region: "cn-beijing",
    workspace_id: "",
  });
  const [advanced, setAdvanced] = useState(false);
  const [urls, setUrls] = useState({ chat: "", embedding: "", rerank: "" });
  const [rerankProtocol, setRerankProtocol] = useState<"rerank" | "dashscope">("rerank");
  const [returnToModel, setReturnToModel] = useState(false);
  const load = useCallback(async () => {
    try {
      const [next, catalog] = await Promise.all([fetchRegistry(), fetchProviderCatalog()]);
      setInventory(next);
      setProviders(catalog.providers);
      onInventory(next);
      setLoaded(true);
    } catch (e) {
      setLoaded(false);
      setError(safeError(e));
    }
  }, [onInventory]);
  useEffect(() => {
    void load();
  }, [load, refreshSignal]);
  const openModel = (model: RegistryModel | null) => {
    setEditing(model);
    setResult(model);
    setError("");
    setProgress("");
    setForm(
      model
        ? {
            request_id: model.request_id,
            connection_id: model.connection_id,
            display_name: model.display_name,
            model_name: model.model_name,
            capability: model.capability,
            dimension: model.dimension,
            usages: model.usages,
            expected_version: model.version,
          }
        : blankModel(),
    );
    setView("model");
  };
  const openConnection = (existing: ProviderConnection | null, returnTo = false) => {
    setConnection(existing);
    setReturnToModel(returnTo);
    setError("");
    setProgress("");
    setAdvanced(false);
    setUrls({ chat: "", embedding: "", rerank: "" });
    setRerankProtocol("rerank");
    setConnectionForm({
      request_id: existing?.id ?? crypto.randomUUID(),
      name: existing?.name ?? "",
      provider: existing?.provider ?? "deepseek",
      api_key: "",
      region: "cn-beijing",
      workspace_id: "",
      expected_version: existing?.config_version,
    });
    setView("connection");
  };
  const refresh = async () => {
    await load();
    await onChanged();
  };
  useEffect(() => {
    if (!busy && progress && result)
      resultRef.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [busy, progress, result]);
  const run = async (model: RegistryModel, forceVerify = false) => {
    let next = model;
    if (forceVerify || next.test_status !== "verified") {
      setProgress("正在使用虚构内容验证模型能力…");
      next = await verifyRegisteredModel(next);
      setResult(next);
    }
    if (next.test_status === "verified") {
      setProgress("验证通过，正在接入所选用途…");
      next = await syncRegisteredModel(next);
      setResult(next);
    }
    const complete =
      next.test_status === "verified" && next.usages.every((u) => next.bindings[u]?.current);
    setProgress(
      complete
        ? "模型已接入。可在模型设置或知识库配置中选择它。"
        : next.test_status === "verified"
          ? "验证通过，部分用途尚未接入。重试将继续未完成的步骤。"
          : "验证未通过。草稿已保留，请按提示修改后重试。",
    );
    await refresh();
    return next;
  };
  const retry = async (model: RegistryModel) => {
    if (!canEdit || busy) return;
    openModel(model);
    setBusy(true);
    try {
      setEditing(
        await run(
          model,
          model.usages.every((u) => model.bindings[u]?.current),
        ),
      );
    } catch (e) {
      setError(safeError(e));
      await load();
    } finally {
      setBusy(false);
    }
  };
  useImperativeHandle(managementRef, () => ({
    create: () => {
      if (canEdit && !busy) openModel(null);
    },
    connections: () => {
      if (canEdit && !busy) {
        setError("");
        setView("connections");
      }
    },
    edit: (model) => {
      if (canEdit && !busy) openModel(model);
    },
    retry: (model) => {
      void retry(model);
    },
  }));
  const patchForm = (patch: Partial<RegistryModelInput>) => {
    setForm((current) => ({ ...current, ...patch }));
    setResult(null);
    setProgress("");
  };
  const selected = inventory.connections.find((c) => c.id === form.connection_id);
  const template = providers.find((p) => p.id === connectionForm.provider);
  const saveConnection = async () => {
    if (!connectionForm.name.trim() || (!connection && !connectionForm.api_key?.trim())) {
      setError("请填写连接名称和 API Key。");
      return;
    }
    const body = { ...connectionForm };
    if (!body.api_key?.trim()) delete body.api_key;
    if (advanced) {
      body.endpoints = {};
      for (const cap of template?.capabilities ?? []) {
        if (urls[cap].trim())
          body.endpoints[cap] = {
            url: urls[cap].trim(),
            protocol: cap === "rerank" ? rerankProtocol : "openai",
          };
      }
    }
    setBusy(true);
    setError("");
    try {
      const saved = connection
        ? await updateProviderConnection(connection.id, body)
        : await createProviderConnection(body);
      await load();
      setConnectionForm((current) => ({ ...current, api_key: "" }));
      if (returnToModel) {
        const capability = saved.capabilities.includes(form.capability)
          ? form.capability
          : saved.capabilities[0];
        patchForm({
          connection_id: saved.id,
          capability,
          dimension: capability === "embedding" ? form.dimension : null,
          usages: capability === "chat" ? form.usages : ["knowledge"],
        });
        setView("model");
      } else setView("connections");
    } catch (e) {
      setError(safeError(e));
    } finally {
      setBusy(false);
    }
  };
  const saveModel = async (activate: boolean) => {
    if (
      !form.connection_id ||
      !form.display_name.trim() ||
      !form.model_name.trim() ||
      !form.usages.length ||
      (form.capability === "embedding" && !form.dimension)
    ) {
      setError("请填写连接、展示名称、模型名称、用途，以及嵌入模型的向量维度。");
      return;
    }
    setBusy(true);
    setError("");
    setProgress("正在保存草稿…");
    try {
      let saved = editing
        ? await updateRegisteredModel(editing.id, { ...form, expected_version: editing.version })
        : await createRegisteredModel(form);
      setEditing(saved);
      setResult(saved);
      setForm((current) => ({ ...current, expected_version: saved.version }));
      if (activate) {
        saved = await run(saved, true);
        setEditing(saved);
      } else {
        setProgress("草稿已保存；验证通过并接入后，才会出现在用途选择中。");
        await refresh();
      }
    } catch (e) {
      setError(safeError(e));
      await load();
    } finally {
      setBusy(false);
    }
  };
  const close = () => {
    if (!busy) {
      setView(null);
      setConnectionForm((current) => ({ ...current, api_key: "" }));
      setError("");
    }
  };
  return (
    <>
      {!view && error && (
        <div className="mf-inline-message is-danger" role="alert">
          {error}
          <button type="button" className="model-text-action" onClick={() => void load()}>
            重新加载接入配置
          </button>
        </div>
      )}
      <TaskModal
        open={view === "model"}
        title={editing ? "管理模型接入" : "接入模型"}
        description="选择供应商连接，验证模型能力，再接入需要的用途。"
        onClose={close}
        busy={busy}
        size="large"
        panelClassName="model-onboarding"
        footer={
          <div className="onboarding-actions">
            <button className="btn-small" disabled={busy} onClick={close}>
              关闭
            </button>
            <button
              className="btn-small"
              disabled={busy || !loaded}
              onClick={() => void saveModel(false)}
            >
              保存草稿
            </button>
            <button
              className="btn-small-primary"
              disabled={busy || !loaded}
              onClick={() => void saveModel(true)}
            >
              {busy ? "处理中…" : "验证并接入"}
            </button>
          </div>
        }
      >
        {error && (
          <div className="mf-inline-message is-danger" role="alert">
            {error}
          </div>
        )}
        <fieldset disabled={busy || !loaded} className="onboarding-fields">
          <section>
            <h3>供应商连接</h3>
            <div className="onboarding-connection-choice">
              <label>
                已有连接
                <select
                  aria-label="已有供应商连接"
                  value={form.connection_id}
                  disabled={!!editing}
                  onChange={(e) => {
                    const c = inventory.connections.find((x) => x.id === e.target.value);
                    const cap = c?.capabilities.includes(form.capability)
                      ? form.capability
                      : (c?.capabilities[0] ?? "chat");
                    patchForm({
                      connection_id: e.target.value,
                      capability: cap,
                      dimension: cap === "embedding" ? form.dimension : null,
                      usages: cap === "chat" ? ["business"] : ["knowledge"],
                    });
                  }}
                >
                  <option value="">请选择连接</option>
                  {inventory.connections.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
              {!editing && (
                <button
                  type="button"
                  className="btn-small"
                  onClick={() => openConnection(null, true)}
                >
                  新建连接
                </button>
              )}
            </div>
            {selected && (
              <p className="onboarding-help">
                {providers.find((p) => p.id === selected.provider)?.name ?? selected.provider} ·
                凭据版本 {selected.credential_version} · {selected.model_count} 个模型共用此连接
              </p>
            )}
          </section>
          <section>
            <h3>模型信息</h3>
            <div className="onboarding-grid">
              <label>
                展示名称
                <input
                  value={form.display_name}
                  onChange={(e) => patchForm({ display_name: e.target.value })}
                  placeholder="例如：项目问答主模型"
                />
              </label>
              <label>
                模型能力
                <select
                  aria-label="接入模型能力"
                  value={form.capability}
                  disabled={!!(editing?.external_ref || editing?.knowledge_ref)}
                  onChange={(e) => {
                    const cap = e.target.value as Capability;
                    patchForm({
                      capability: cap,
                      dimension: cap === "embedding" ? form.dimension : null,
                      usages: cap === "chat" ? ["business"] : ["knowledge"],
                    });
                  }}
                >
                  {(selected?.capabilities ?? ["chat", "embedding", "rerank"]).map((cap) => (
                    <option value={cap} key={cap}>
                      {capabilityLabels[cap as Capability]}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                模型名称
                <input
                  value={form.model_name}
                  disabled={!!(editing?.external_ref || editing?.knowledge_ref)}
                  onChange={(e) => patchForm({ model_name: e.target.value })}
                  placeholder="服务商控制台中的模型或推理接入点名称"
                />
              </label>
              {form.capability === "embedding" && (
                <label>
                  向量维度
                  <input
                    type="number"
                    min="1"
                    max="65536"
                    value={form.dimension ?? ""}
                    disabled={!!editing?.knowledge_ref}
                    onChange={(e) =>
                      patchForm({ dimension: e.target.value ? Number(e.target.value) : null })
                    }
                  />
                </label>
              )}
            </div>
            <p className="onboarding-help">
              实际调用权限以验证结果为准。已接入的嵌入模型如需更换模型或维度，请新增后迁移知识库。
            </p>
          </section>
          <section>
            <h3>可用场景</h3>
            <div className="onboarding-usages">
              {(["business", "knowledge"] as ModelUsage[]).map((usage) => (
                <label key={usage}>
                  <input
                    type="checkbox"
                    checked={form.usages.includes(usage)}
                    disabled={
                      (usage === "business" && form.capability !== "chat") ||
                      !!(editing?.bindings[usage]?.status === "ready")
                    }
                    onChange={(e) =>
                      patchForm({
                        usages: e.target.checked
                          ? [...form.usages, usage]
                          : form.usages.filter((u) => u !== usage),
                      })
                    }
                  />
                  <span>
                    {usageLabels[usage]}
                    {usage === "business" && <small>适用于对话模型</small>}
                  </span>
                </label>
              ))}
            </div>
            <p className="onboarding-help">
              接入后可供相应场景选择，默认模型和已有知识库绑定由“模型设置”“知识库配置”管理。
            </p>
          </section>
        </fieldset>
        {progress && (
          <p className="onboarding-progress" role="status">
            {progress}
          </p>
        )}
        {result && (
          <section ref={resultRef} className="onboarding-result" aria-label="模型接入结果">
            <h3>保存版本的验证结果</h3>
            <p>
              {result.test_message}
              {result.test_duration_ms !== null && ` · ${result.test_duration_ms} ms`}
              {result.observed_dimension !== null && ` · ${result.observed_dimension} 维`}
            </p>
            {result.usages.map((u) => (
              <p key={u}>
                <strong>{usageLabels[u]}</strong> · {result.bindings[u]?.message ?? "尚未接入"}
              </p>
            ))}
            {result.test_code && <small>排查代码：{result.test_code}</small>}
          </section>
        )}
      </TaskModal>
      <TaskModal
        open={view === "connections"}
        title="供应商连接"
        description="一个连接可供多个模型共用，地址和密钥加密保存。"
        onClose={close}
        size="large"
        footer={
          <button
            className="btn-small-primary"
            disabled={busy || !loaded}
            onClick={() => openConnection(null)}
          >
            新建供应商连接
          </button>
        }
      >
        {error && (
          <div role="alert" className="mf-inline-message is-danger">
            {error}
          </div>
        )}
        <div className="onboarding-connections">
          {inventory.connections.length === 0 ? (
            <p>尚未创建连接。先添加服务商凭据，再接入模型。</p>
          ) : (
            inventory.connections.map((c) => (
              <div className="onboarding-connection" key={c.id}>
                <ProviderLogo provider={c.provider} label={c.provider} />
                <div>
                  <strong>{c.name}</strong>
                  <small>
                    {c.capabilities.map((x) => capabilityLabels[x]).join(" · ")} · {c.model_count}{" "}
                    个模型 · 凭据版本 {c.credential_version}
                  </small>
                </div>
                <button className="model-text-action" onClick={() => openConnection(c)}>
                  编辑连接
                </button>
              </div>
            ))
          )}
        </div>
      </TaskModal>
      <TaskModal
        open={view === "connection"}
        title={connection ? "编辑供应商连接" : "新建供应商连接"}
        description={
          connection
            ? "地址和密钥留空时保留原配置。更改后需要重新验证关联模型，再接入新版本。"
            : "选择供应商模板，也可以配置自定义兼容服务。"
        }
        onClose={() => {
          if (!busy) {
            setView(returnToModel ? "model" : "connections");
            setConnectionForm((current) => ({ ...current, api_key: "" }));
            setError("");
          }
        }}
        busy={busy}
        size="large"
        footer={
          <button
            className="btn-small-primary"
            disabled={busy}
            onClick={() => void saveConnection()}
          >
            {busy ? "保存中…" : "保存连接"}
          </button>
        }
      >
        {error && (
          <div role="alert" className="mf-inline-message is-danger">
            {error}
          </div>
        )}
        {connection && connection.model_count > 0 && (
          <div className="onboarding-impact">
            影响 {connection.model_count} 个模型：{connection.affected_models.join("、")}
            。保存连接后，现有用途继续使用已接入版本，直到各模型验证并接入新版本。
          </div>
        )}
        <fieldset disabled={busy} className="onboarding-fields">
          <div className="onboarding-grid">
            <label>
              连接名称
              <input
                value={connectionForm.name}
                onChange={(e) => setConnectionForm({ ...connectionForm, name: e.target.value })}
                placeholder="例如：硅基流动 · 项目服务"
              />
            </label>
            <label>
              供应商
              <select
                value={connectionForm.provider}
                disabled={!!connection}
                onChange={(e) => {
                  setConnectionForm({ ...connectionForm, provider: e.target.value });
                  setAdvanced(e.target.value === "custom");
                  setUrls({ chat: "", embedding: "", rerank: "" });
                }}
              >
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            {template?.workspace && (
              <>
                <label>
                  地域
                  <select
                    value={connectionForm.region}
                    onChange={(e) =>
                      setConnectionForm({ ...connectionForm, region: e.target.value })
                    }
                  >
                    <option value="cn-beijing">北京</option>
                    <option value="cn-hongkong">香港</option>
                    <option value="ap-southeast-1">新加坡</option>
                  </select>
                </label>
                <label>
                  业务空间 ID
                  <input
                    value={connectionForm.workspace_id}
                    placeholder={connection ? "留空保留现有接口" : "请从服务商控制台复制"}
                    onChange={(e) =>
                      setConnectionForm({ ...connectionForm, workspace_id: e.target.value })
                    }
                  />
                </label>
              </>
            )}
            <label>
              API Key
              <input
                type="password"
                autoComplete="new-password"
                value={connectionForm.api_key}
                placeholder={connection ? "留空保持原凭据" : "仅用于服务端调用，保存后不回显"}
                onChange={(e) => setConnectionForm({ ...connectionForm, api_key: e.target.value })}
              />
            </label>
          </div>
          <label className="onboarding-advanced">
            <input
              type="checkbox"
              checked={advanced}
              onChange={(e) => {
                setAdvanced(e.target.checked);
                if (!connection && template?.base)
                  setUrls({
                    chat: template.capabilities.includes("chat") ? template.base : "",
                    embedding: template.capabilities.includes("embedding") ? template.base : "",
                    rerank: template.capabilities.includes("rerank")
                      ? `${template.base}/rerank`
                      : "",
                  });
              }}
            />
            自定义能力接口
          </label>
          {advanced ? (
            <div className="onboarding-grid">
              {template?.capabilities.map((cap) => (
                <label key={cap}>
                  {capabilityLabels[cap]}
                  {cap === "rerank" ? "完整接口地址" : " Base URL"}
                  <input
                    value={urls[cap]}
                    onChange={(e) => setUrls({ ...urls, [cap]: e.target.value })}
                    placeholder="留空表示不提供此能力"
                  />
                </label>
              ))}
              {template?.capabilities.includes("rerank") && (
                <label>
                  重排协议
                  <select
                    value={rerankProtocol}
                    onChange={(e) => setRerankProtocol(e.target.value as "rerank" | "dashscope")}
                  >
                    <option value="rerank">通用 Rerank（Cohere 格式）</option>
                    <option value="dashscope">百炼原生 Rerank</option>
                  </select>
                </label>
              )}
            </div>
          ) : (
            <p className="onboarding-help">
              {connection
                ? "保留已保存的接口；填写新的业务空间或勾选自定义接口后才会替换。"
                : template?.workspace
                  ? "系统根据地域和业务空间，分别生成对话、嵌入和重排接口。"
                  : template?.base
                    ? `使用供应商默认 Base URL：${template.base}`
                    : "请在自定义能力接口中填写服务地址。"}
            </p>
          )}
        </fieldset>
      </TaskModal>
    </>
  );
}
