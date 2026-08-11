import { useEffect, useState } from "react";
import OperationStatusCard from "./OperationStatusCard";
import WizardModal from "./WizardModal";
import { migrateWeknoraKb } from "../api/admin";
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
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!open) return;
    setEmbedding(defaultEmbeddingRef || cfg.embedding?.model_ref || "");
    setChat(cfg.chat?.model_ref || "");
    setMultimodal(cfg.multimodal?.model_ref || "");
    setError(null);
    setStep(0);
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
    } catch {
      setError("迁移作业未能提交，请刷新状态并确认权限后重试。");
    } finally {
      setBusy(false);
    }
  };

  return (
    <WizardModal
      open={open}
      title={`迁移知识库“${cfg.kb_name}”`}
      description="把当前知识库迁移到一个绑定新嵌入模型的新库（绕开底座“已有文件不可改模型”的限制）。"
      steps={[
        { label: "选择模型", description: "确定新库的底座配置" },
        { label: "确认影响", description: "核对暂停范围与完成条件" },
      ]}
      currentStep={step}
      busy={busy}
      nextDisabled={!embedding || !chat}
      completeText="提交迁移作业"
      busyText="正在提交迁移作业…"
      onBack={() => setStep(0)}
      onNext={() => {
        if (!embedding || !chat) {
          setError("嵌入模型和问答模型为必选。");
          return;
        }
        setError(null);
        setStep(1);
      }}
      onComplete={() => void submit()}
      onCancel={onClose}
    >
      {step === 0 ? (
        <div className="mf-migrate-form">
          <p className="mf-migrate-note">
            先选择新库使用的模型。此步骤只在浏览器中核对，点击“继续”不会提交或写入。
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
          <p className="mf-migrate-note">重排模型沿用平台默认，无需选择。</p>
          {error && <div className="kl-modal-error">{error}</div>}
        </div>
      ) : (
        <div className="mf-migrate-review">
          <OperationStatusCard
            status="attention"
            title="提交后进入异步迁移，不代表迁移已经完成"
            description="迁移期间该库暂停新入库；只有所有文档达到最终完成状态后，系统才会切换并清理旧库。"
            counts={[
              {
                label: "嵌入模型",
                value:
                  options("embedding").find((m) => m.model_ref === embedding)?.name ?? "已选择",
              },
              {
                label: "问答模型",
                value: options("chat").find((m) => m.model_ref === chat)?.name ?? "已选择",
              },
            ]}
            nextStep="提交后关闭弹窗，在知识库状态卡中继续查看最终进度。"
          />
          {error && <div className="kl-modal-error">{error}</div>}
        </div>
      )}
    </WizardModal>
  );
}
