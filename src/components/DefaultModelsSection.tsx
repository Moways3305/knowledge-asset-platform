import { useState, useEffect, useCallback } from "react";
import { ApiError } from "../api/http";
import { fetchDefaultModels, updateDefaultModels } from "../api/weknoraModels";
import type { DefaultModelsDTO, ModelDTO } from "../types/weknoraAdmin";

// 平台默认模型设置区（PBC-38）。
// - admin 可保存（canEdit）；治理角色若进入本页则只读（canEdit=false）。
// - 用对底座 id 不可逆的 model_ref 选择；绝不展示 / 提交真实 model_id。
// - 保存会整体覆盖四个槽位，故每次提交携带全部当前选择，避免无意清空其它默认槽位。
//
// 平台默认 embedding 未配置时显式提示，提醒管理员配置（顾问入库会被 fail-closed 禁用）。
export default function DefaultModelsSection({
  models,
  canEdit,
}: {
  models: ModelDTO[];
  canEdit: boolean;
}) {
  const [current, setCurrent] = useState<DefaultModelsDTO | null>(null);
  const [embedding, setEmbedding] = useState("");
  const [rerank, setRerank] = useState("");
  const [chat, setChat] = useState("");
  const [multimodal, setMultimodal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const describe = (e: unknown, fallback: string) =>
    e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : fallback;

  const apply = (d: DefaultModelsDTO) => {
    setCurrent(d);
    setEmbedding(d.embedding?.model_ref ?? "");
    setRerank(d.rerank?.model_ref ?? "");
    setChat(d.chat?.model_ref ?? "");
    setMultimodal(d.multimodal?.model_ref ?? "");
  };

  const load = useCallback(async () => {
    try {
      apply(await fetchDefaultModels());
    } catch (e) {
      setError(describe(e, "加载平台默认模型失败"));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = useCallback(async () => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const d = await updateDefaultModels({
        embedding_model_ref: embedding || null,
        rerank_model_ref: rerank || null,
        chat_model_ref: chat || null,
        multimodal_ref: multimodal || null,
      });
      apply(d);
      setNote("平台默认模型已保存");
    } catch (e) {
      setError(describe(e, "保存平台默认模型失败"));
    } finally {
      setBusy(false);
    }
  }, [embedding, rerank, chat, multimodal]);

  const opts = (type: string) => models.filter((m) => m.type === type);
  const slot = (
    label: string,
    value: string,
    setter: (v: string) => void,
    type: string,
    optional: boolean,
    currentSlot: { model_ref: string | null; name: string | null } | null | undefined,
  ) => {
    const options = opts(type);
    // 当模型列表被类型筛选时，仍补一项已选默认，确保当前选择始终可见、保存不被无意清空。
    const selectedShown = value === "" || options.some((m) => m.model_ref === value);
    return (
      <label className="ws-form-field">
        <span className="ws-form-label">{label}</span>
        <select
          className="ws-form-input"
          aria-label={label}
          value={value}
          disabled={!canEdit}
          onChange={(e) => setter(e.target.value)}
        >
          <option value="">{optional ? "（不设置）" : "（未设置）"}</option>
          {!selectedShown && currentSlot?.model_ref && (
            <option value={currentSlot.model_ref}>{currentSlot.name ?? "当前默认"}（当前）</option>
          )}
          {options.map((m) => (
            <option key={m.model_ref} value={m.model_ref}>
              {m.name}
              {m.provider ? `（${m.provider}）` : ""}
            </option>
          ))}
        </select>
      </label>
    );
  };

  const embeddingMissing = current !== null && !current.embedding?.model_ref;

  return (
    <section className="ws-section">
      <h3>平台默认模型</h3>
      <p className="au-note">
        平台默认模型用于顾问入库 / 建库时的推荐选择；未配置默认 embedding
        时，顾问入库会被禁用并提示联系管理员（不再从 .env 静默兜底）。本区仅用对底座 id 不可逆的
        model_ref 选择，不显示底座内部标识。
        {canEdit ? "" : "（只读：治理角色可查看，修改需系统管理员）"}
      </p>
      {embeddingMissing && (
        <div
          className="ws-note-hint"
          role="alert"
          style={{ color: "var(--color-danger-fg, #b00)" }}
        >
          尚未配置默认 embedding 模型，顾问入库将被禁用，请在下方设置后保存。
        </div>
      )}
      {error && (
        <div className="ws-note-hint" style={{ color: "var(--color-danger-fg, #b00)" }}>
          {error}
        </div>
      )}
      {note && (
        <div className="ws-note-hint" style={{ color: "var(--color-success-fg, #176)" }}>
          {note}
        </div>
      )}
      <div className="ws-form-grid">
        {slot(
          "默认嵌入 embedding",
          embedding,
          setEmbedding,
          "embedding",
          false,
          current?.embedding,
        )}
        {slot("默认重排 rerank（可选）", rerank, setRerank, "rerank", true, current?.rerank)}
        {slot("默认对话 chat（可选）", chat, setChat, "chat", true, current?.chat)}
        {slot("默认多模态（可选）", multimodal, setMultimodal, "vllm", true, current?.multimodal)}
      </div>
      {canEdit && (
        <div className="ws-form-actions">
          <button className="btn-small-primary" onClick={() => void save()} disabled={busy}>
            {busy ? "保存中…" : "保存平台默认模型"}
          </button>
        </div>
      )}
    </section>
  );
}
