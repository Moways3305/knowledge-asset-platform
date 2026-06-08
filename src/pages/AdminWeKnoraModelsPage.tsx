import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  checkWeknoraModel,
  createWeknoraModel,
  deleteWeknoraModel,
  fetchWeknoraKbConfigs,
  fetchWeknoraModels,
  fetchWeknoraProviders,
  updateWeknoraKbInit,
  updateWeknoraModel,
} from "../api/client";
import type {
  KbConfigDTO,
  ModelDTO,
  ModelMutateRequestDTO,
  ProviderDTO,
} from "../types/weknoraAdmin";

// 模型配置中心：admin 运营工具。代理 WeKnora 模型与 KB 初始化配置，
// 不在前端出现 model_id / kb_id / api_key（保存后不回显）/ base_url 真实值。

const TYPE_OPTIONS = [
  { value: "chat", label: "对话（chat）" },
  { value: "embedding", label: "嵌入（embedding）" },
  { value: "rerank", label: "重排（rerank）" },
  { value: "vllm", label: "多模态（vllm）" },
  { value: "asr", label: "语音（asr）" },
];
const SOURCE_OPTIONS = [
  { value: "remote", label: "远程 API（remote）" },
  { value: "local", label: "本地 Ollama（local）" },
];
const scopeLabel: Record<string, string> = { company: "公司库", project: "项目库", personal: "个人库" };
const mappingStatusLabel: Record<string, string> = { active: "已初始化", init_failed: "初始化失败" };

const emptyForm = (): ModelMutateRequestDTO => ({
  name: "", type: "chat", source: "remote", provider: "", base_url: "", api_key: "", description: "",
});

export default function AdminWeKnoraModelsPage() {
  const [models, setModels] = useState<ModelDTO[]>([]);
  const [providers, setProviders] = useState<ProviderDTO[]>([]);
  const [kbConfigs, setKbConfigs] = useState<KbConfigDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [notConfigured, setNotConfigured] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState("");

  // 创建 / 编辑模型表单。
  const [formOpen, setFormOpen] = useState(false);
  const [editingRef, setEditingRef] = useState<string | null>(null);
  const [form, setForm] = useState<ModelMutateRequestDTO>(emptyForm());
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // 连通性测试。
  const [checkResult, setCheckResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [checkBusy, setCheckBusy] = useState(false);

  const describe = (e: unknown, fallback: string) =>
    e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : fallback;

  const load = useCallback(async () => {
    setLoading(true); setError(null); setNotConfigured(null);
    try {
      const [m, p, k] = await Promise.all([
        fetchWeknoraModels(typeFilter || undefined),
        fetchWeknoraProviders(),
        fetchWeknoraKbConfigs(),
      ]);
      setModels(m); setProviders(p); setKbConfigs(k);
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) {
        // 未配置 WeKnora：只展示 missing config 项名，不展示值。
        const miss = (e.detail?.missing_config as string[] | undefined) ?? [];
        setNotConfigured(miss.length ? miss : ["WEKNORA_BASE_URL", "WEKNORA_API_KEY"]);
      } else if (e instanceof ApiError && (e.status === 403)) {
        setError("仅系统管理员可访问模型配置中心。");
      } else {
        setError(describe(e, "加载模型配置失败（请确认后端已启动）"));
      }
      setModels([]); setProviders([]); setKbConfigs([]);
    } finally {
      setLoading(false);
    }
  }, [typeFilter]);

  useEffect(() => { void load(); }, [load]);

  const openCreate = () => { setEditingRef(null); setForm(emptyForm()); setSaveError(null); setCheckResult(null); setFormOpen(true); };
  const openEdit = (m: ModelDTO) => {
    setEditingRef(m.model_ref);
    setForm({ name: m.name, type: m.type, source: m.source ?? "remote", provider: m.provider ?? "", base_url: "", api_key: "", description: m.description ?? "" });
    setSaveError(null); setCheckResult(null); setFormOpen(true);
  };

  const handleSave = useCallback(async () => {
    setSaveError(null);
    if (!form.name.trim()) { setSaveError("请填写模型名称"); return; }
    setSaveBusy(true);
    try {
      if (editingRef) {
        await updateWeknoraModel(editingRef, form);
        setNote("模型已更新");
      } else {
        await createWeknoraModel(form);
        setNote("模型已创建");
      }
      setFormOpen(false);
      setForm(emptyForm()); // 清空表单，绝不回显已提交的访问密钥
      await load();
    } catch (e) {
      setSaveError(describe(e, "保存模型失败"));
    } finally {
      setSaveBusy(false);
    }
  }, [editingRef, form, load]);

  const handleDelete = useCallback(async (m: ModelDTO) => {
    setNote(null); setError(null);
    try {
      await deleteWeknoraModel(m.model_ref);
      setNote(`模型「${m.name}」已删除`);
      await load();
    } catch (e) {
      setError(describe(e, "删除模型失败"));
    }
  }, [load]);

  const handleCheck = useCallback(async () => {
    setCheckBusy(true); setCheckResult(null);
    try {
      const r = await checkWeknoraModel({
        model_type: form.type, api_url: form.base_url ?? "", api_key: form.api_key ?? "", model: form.name,
      });
      setCheckResult({ ok: r.success, msg: r.message });
    } catch (e) {
      setCheckResult({ ok: false, msg: describe(e, "连通性测试失败") });
    } finally {
      setCheckBusy(false);
    }
  }, [form]);

  return (
    <div className="ws-page">
      <div className="kl-header">
        <div className="kl-header-text">
          <h2>WeKnora 模型配置中心</h2>
          <p>系统管理员在此代理管理知识底座的 provider / 模型与各知识库的初始化模型配置，无需登录 WeKnora 控制台。本页仅承载安全运营元数据，不显示底座内部 id / 访问密钥 / 服务地址真实值。</p>
        </div>
      </div>

      {note && <section className="ws-section"><div className="ws-note-hint" style={{ color: "var(--color-success-fg, #176)" }}>{note}</div></section>}
      {error && <section className="ws-section"><div className="ws-note-hint" style={{ color: "var(--color-danger-fg, #b00)" }}>{error}</div></section>}

      {notConfigured ? (
        <section className="ws-section">
          <div className="ig-empty-state">
            <div className="ig-empty-title">知识底座（WeKnora）未配置</div>
            <p className="ig-empty-desc">
              缺少配置项：{notConfigured.map((m) => <code key={m} style={{ marginRight: 8 }}>{m}</code>)}。
              请在部署环境注入这些配置后重启后端；本页不显示配置值。
            </p>
          </div>
        </section>
      ) : loading ? (
        <section className="ws-section"><div className="ig-empty-state"><div className="ig-empty-title">加载中…</div></div></section>
      ) : (
        <>
          {/* 模型列表 */}
          <section className="ws-section">
            <div className="ig-toolbar">
              <h3 style={{ margin: 0 }}>模型</h3>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
                  <option value="">全部类型</option>
                  {TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                <button className="btn-small-primary" onClick={openCreate}>新增模型</button>
                <button className="btn-small" onClick={() => void load()}>刷新</button>
              </div>
            </div>
            {models.length === 0 ? (
              <div className="ig-empty-state"><div className="ig-empty-title">暂无模型</div><p className="ig-empty-desc">点击「新增模型」添加远程 / 本地模型。</p></div>
            ) : (
              <div className="ws-table-wrap">
                <table className="ws-table">
                  <thead><tr><th>名称</th><th>类型</th><th>provider</th><th>来源</th><th>状态</th><th>操作</th></tr></thead>
                  <tbody>
                    {models.map((m) => (
                      <tr key={m.model_ref}>
                        <td>{m.name}</td>
                        <td>{m.type}</td>
                        <td>{m.provider ?? "—"}</td>
                        <td>{m.source ?? "—"}</td>
                        <td><span className={`ws-status-pill ${m.enabled ? "ws-status-on" : "ws-status-off"}`}>{m.enabled ? "可用" : "停用"}</span>{m.is_builtin && <span className="ws-cell-project">（内置）</span>}</td>
                        <td className="ws-cell-actions">
                          <button className="btn-small" onClick={() => openEdit(m)}>编辑</button>
                          {!m.is_builtin && <button className="btn-small btn-small-danger" onClick={() => void handleDelete(m)}>删除</button>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="au-note" style={{ marginTop: 8 }}>可用 provider：{providers.length > 0 ? providers.map((p) => p.label).join(" · ") : "—"}</p>
          </section>

          {/* 创建 / 编辑表单 */}
          {formOpen && (
            <section className="ws-section">
              <div className="ws-detail-panel">
                <div className="ws-detail-head">
                  <span className="ws-detail-title">{editingRef ? "编辑模型" : "新增模型"}</span>
                  <button className="btn-small" onClick={() => setFormOpen(false)} disabled={saveBusy}>关闭</button>
                </div>
                <div className="ws-form-grid">
                  <label className="ws-form-field"><span className="ws-form-label">模型名称</span>
                    <input className="ws-form-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="服务商 model id 或 Ollama tag" /></label>
                  <label className="ws-form-field"><span className="ws-form-label">类型</span>
                    <select className="ws-form-input" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                      {TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></label>
                  <label className="ws-form-field"><span className="ws-form-label">来源</span>
                    <select className="ws-form-input" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}>
                      {SOURCE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></label>
                  <label className="ws-form-field"><span className="ws-form-label">provider</span>
                    <select className="ws-form-input" value={form.provider ?? ""} onChange={(e) => setForm({ ...form, provider: e.target.value })}>
                      <option value="">（不指定）</option>
                      {providers.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}</select></label>
                  <label className="ws-form-field"><span className="ws-form-label">API 地址</span>
                    <input className="ws-form-input" value={form.base_url ?? ""} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="远程模型必填；保存后不回显" /></label>
                  <label className="ws-form-field"><span className="ws-form-label">访问密钥</span>
                    <input className="ws-form-input" type="password" value={form.api_key ?? ""} onChange={(e) => setForm({ ...form, api_key: e.target.value })} placeholder="仅上送底座，保存后不回显" /></label>
                  {form.type === "embedding" && (
                    <label className="ws-form-field"><span className="ws-form-label">向量维度（可选）</span>
                      <input className="ws-form-input" type="number" value={form.dimension ?? ""} onChange={(e) => setForm({ ...form, dimension: e.target.value ? Number(e.target.value) : null })} /></label>
                  )}
                  <label className="ws-form-field"><span className="ws-form-label">描述（可选）</span>
                    <input className="ws-form-input" value={form.description ?? ""} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
                </div>
                {saveError && <div className="ws-note-hint" style={{ color: "var(--color-danger-fg, #b00)" }}>{saveError}</div>}
                {checkResult && (
                  <div className="ws-note-hint" style={{ color: checkResult.ok ? "var(--color-success-fg, #176)" : "var(--color-danger-fg, #b00)" }}>
                    连通性测试：{checkResult.ok ? "通过" : "失败"} — {checkResult.msg}
                  </div>
                )}
                <div className="ws-form-actions">
                  <button className="btn-small-primary" onClick={() => void handleSave()} disabled={saveBusy}>{saveBusy ? "保存中…" : (editingRef ? "保存修改" : "创建模型")}</button>
                  {form.type !== "asr" && <button className="btn-small" onClick={() => void handleCheck()} disabled={checkBusy || !form.base_url || !form.api_key || !form.name}>{checkBusy ? "测试中…" : "连通性测试"}</button>}
                  <button className="btn-small" onClick={() => setFormOpen(false)} disabled={saveBusy}>取消</button>
                </div>
                <p className="au-note">连通性测试仅返回「通过 / 失败 + 安全文案」，不回显密钥 / 地址 / 原始响应。访问密钥与 API 地址只代理写入底座，平台不保存、列表不回显。</p>
              </div>
            </section>
          )}

          {/* KB 初始化配置 */}
          <section className="ws-section">
            <h3>知识库初始化配置</h3>
            {kbConfigs.length === 0 ? (
              <div className="ig-empty-state"><div className="ig-empty-title">暂无知识库</div><p className="ig-empty-desc">入库或创建项目后，会在此显示各知识库的模型初始化配置。</p></div>
            ) : (
              <div className="ws-table-wrap">
                <table className="ws-table">
                  <thead><tr><th>知识库</th><th>范围</th><th>状态</th><th>对话</th><th>嵌入</th><th>重排</th><th>多模态</th><th>操作</th></tr></thead>
                  <tbody>
                    {kbConfigs.map((k) => (
                      <KbConfigRow key={k.mapping_id} cfg={k} models={models} onSaved={(msg) => { setNote(msg); void load(); }} onError={(msg) => setError(msg)} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="au-note" style={{ marginTop: 8 }}>
              初始化失败（init_failed）的知识库在此选择并保存模型即可恢复 active；已落库但索引失败的具体资产仍需在 <Link to="/admin/ingest">入库管理</Link> 或资产详情页重试索引。
            </p>
          </section>
        </>
      )}
    </div>
  );
}

// 单个知识库初始化配置行：可为每个槽位选择模型 ref 并保存。
function KbConfigRow({ cfg, models, onSaved, onError }: {
  cfg: KbConfigDTO;
  models: ModelDTO[];
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [chat, setChat] = useState(cfg.chat?.model_ref ?? "");
  const [embedding, setEmbedding] = useState(cfg.embedding?.model_ref ?? "");
  const [rerank, setRerank] = useState(cfg.rerank?.model_ref ?? "");
  const [multimodal, setMultimodal] = useState(cfg.multimodal?.model_ref ?? "");
  const [busy, setBusy] = useState(false);

  const opts = (type: string) => models.filter((m) => m.type === type);
  const sel = (value: string, setter: (v: string) => void, type: string, current: { name: string | null } | null) => (
    <select className="ws-form-input" value={value} onChange={(e) => setter(e.target.value)}>
      <option value="">{current?.name ? `保持（${current.name}）` : "（未设置）"}</option>
      {opts(type).map((m) => <option key={m.model_ref} value={m.model_ref}>{m.name}</option>)}
    </select>
  );

  const save = async () => {
    setBusy(true);
    try {
      const body: Record<string, string> = {};
      if (chat) body.chat_model_ref = chat;
      if (embedding) body.embedding_model_ref = embedding;
      if (rerank) body.rerank_model_ref = rerank;
      if (multimodal) body.multimodal_ref = multimodal;
      if (Object.keys(body).length === 0) { onError("请至少选择一个模型"); setBusy(false); return; }
      await updateWeknoraKbInit(cfg.mapping_id, body);
      onSaved(`知识库「${cfg.kb_name}」初始化配置已更新`);
    } catch (e) {
      onError(e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "更新初始化配置失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr className={cfg.mapping_status === "init_failed" ? "ws-row-disabled" : ""}>
      <td>{cfg.kb_name}{cfg.project_name ? ` · ${cfg.project_name}` : ""}{cfg.owner_name ? ` · ${cfg.owner_name}` : ""}</td>
      <td>{scopeLabel[cfg.scope] ?? cfg.scope}</td>
      <td><span className={`ws-status-pill ${cfg.mapping_status === "active" ? "ws-status-on" : "ws-status-off"}`}>{mappingStatusLabel[cfg.mapping_status] ?? cfg.mapping_status}</span></td>
      <td>{sel(chat, setChat, "chat", cfg.chat)}</td>
      <td>{sel(embedding, setEmbedding, "embedding", cfg.embedding)}</td>
      <td>{sel(rerank, setRerank, "rerank", cfg.rerank)}</td>
      <td>{sel(multimodal, setMultimodal, "vllm", cfg.multimodal)}</td>
      <td>
        <button className="btn-small btn-small-primary" onClick={() => void save()} disabled={busy}>{busy ? "保存中…" : "保存"}</button>
        {cfg.config_error && <div className="ws-cell-suggestion" style={{ color: "var(--color-danger-fg, #b00)" }}>{cfg.config_error}</div>}
      </td>
    </tr>
  );
}

