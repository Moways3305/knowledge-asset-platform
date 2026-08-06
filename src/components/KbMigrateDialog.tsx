import { useEffect, useState } from "react";
import ConfirmDialog from "./ConfirmDialog";
import { migrateWeknoraKb } from "../api/admin";
import { ApiError } from "../api/http";
import type { KbConfigDTO, ModelDTO } from "../types/weknoraAdmin";

export default function KbMigrateDialog({
  cfg,
  models,
  defaultEmbeddingRef,
  open,
  onClose,
  onMigrated,
}: {
  cfg: KbConfigDTO;
  models: ModelDTO[];
  defaultEmbeddingRef: string;
  open: boolean;
  onClose: () => void;
  onMigrated: (message: string) => Promise<void> | void;
}) {
  const [embedding, setEmbedding] = useState("");
  const [chat, setChat] = useState("");
  const [multimodal, setMultimodal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setEmbedding(defaultEmbeddingRef || cfg.embedding?.model_ref || "");
    setChat(cfg.chat?.model_ref || "");
    setMultimodal(cfg.multimodal?.model_ref || "");
    setError(null);
  }, [
    open,
    cfg.chat?.model_ref,
    cfg.embedding?.model_ref,
    cfg.multimodal?.model_ref,
    defaultEmbeddingRef,
  ]);

  const options = (type: string) => models.filter((model) => model.type === type && model.enabled);

  const submit = async () => {
    if (!embedding || !chat) {
      setError("嵌入模型和问答模型为必选。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await migrateWeknoraKb(cfg.mapping_id, {
        embedding_model_ref: embedding,
        chat_model_ref: chat,
        multimodal_model_ref: multimodal || null,
      });
      onClose();
      await onMigrated(
        `知识库“${cfg.kb_name}”迁移作业已提交：将新建库并逐文档重新上传向量化，全部成功后删除旧库；迁移期间该库暂停新入库。`,
      );
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "迁移作业提交失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog
      open={open}
      title={`迁移知识库“${cfg.kb_name}”`}
      description="把当前知识库迁移到一个绑定新嵌入模型的新库（绕开底座“已有文件不可改模型”的限制）。"
      confirmText={busy ? "提交中…" : "开始迁移"}
      busy={busy}
      onConfirm={() => void submit()}
      onCancel={onClose}
      error={error ? "migrate-submit-failed" : null}
      errorDescription={error}
    >
      <div className="mf-migrate-form">
        <p className="mf-migrate-note">
          迁移期间该库暂停新入库确认；全部文档迁移成功后旧库会被删除。可在下方选择新库使用的模型。
        </p>
        <label className="ws-form-field">
          <span className="ws-form-label">嵌入模型（必选）</span>
          <select
            className="ws-form-input"
            value={embedding}
            disabled={busy}
            onChange={(event) => setEmbedding(event.target.value)}
          >
            <option value="">请选择嵌入模型</option>
            {options("embedding").map((model) => (
              <option key={model.model_ref} value={model.model_ref}>
                {model.name}
              </option>
            ))}
          </select>
        </label>
        <label className="ws-form-field">
          <span className="ws-form-label">问答模型（必选）</span>
          <select
            className="ws-form-input"
            value={chat}
            disabled={busy}
            onChange={(event) => setChat(event.target.value)}
          >
            <option value="">请选择问答模型</option>
            {options("chat").map((model) => (
              <option key={model.model_ref} value={model.model_ref}>
                {model.name}
              </option>
            ))}
          </select>
        </label>
        <label className="ws-form-field">
          <span className="ws-form-label">多模态模型（可选）</span>
          <select
            className="ws-form-input"
            value={multimodal}
            disabled={busy}
            onChange={(event) => setMultimodal(event.target.value)}
          >
            <option value="">不启用</option>
            {options("vllm").map((model) => (
              <option key={model.model_ref} value={model.model_ref}>
                {model.name}
              </option>
            ))}
          </select>
        </label>
        <p className="mf-migrate-note">重排模型：按库重排不受底座支持，沿用平台默认，无需选择。</p>
      </div>
    </ConfirmDialog>
  );
}
