import { useState } from "react";
import type { ModelSelectionState } from "../hooks/useModelSelection";

// 入库 / 建库高级设置：模型选择（PBC-38）。
// 默认收起；默认选中平台推荐 embedding / rerank；普通顾问可在此切换。
// 仅展示模型名 / provider / 说明，绝不出现真实 model_id（DTO 本就不含）。
// 选择以对底座 id 不可逆的 model_ref 提交，由父级表单放入入库 payload。
//
// 平台默认 embedding 未配置时（models.blockSubmit）：显示安全提示，父级据此禁用提交。
export default function ModelAdvancedSettings({ models }: { models: ModelSelectionState }) {
  const [open, setOpen] = useState(false);

  // WeKnora 未配置：模型选择不适用，整块不渲染（入库仍可进行，索引被安全跳过）。
  if (models.weknoraDisabled) return null;

  const missing = models.blockSubmit;

  const slot = (
    label: string,
    value: string,
    setter: (v: string) => void,
    options: ModelSelectionState["embeddingOptions"],
    optional: boolean,
  ) => (
    <label className="ws-form-field">
      <span className="ws-form-label">{label}</span>
      <select
        className="ws-form-input"
        aria-label={label}
        value={value}
        disabled={missing || options.length === 0}
        onChange={(e) => setter(e.target.value)}
      >
        {optional && <option value="">（不指定，使用平台推荐）</option>}
        {options.map((m) => (
          <option key={m.model_ref} value={m.model_ref}>
            {m.name}
            {m.provider ? `（${m.provider}）` : ""}
            {m.is_default ? " · 推荐" : ""}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <section className="upload-section up-model-advanced">
      <button
        type="button"
        className="up-advanced-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "▾" : "▸"} 高级设置（模型选择）
      </button>
      {missing && (
        <div
          className="up-submit-notice"
          role="alert"
          style={{ color: "var(--color-danger-fg, #b00)" }}
        >
          尚未配置默认模型，请联系管理员在模型配置中设置。
        </div>
      )}
      {open && !missing && (
        <div className="up-model-advanced-body">
          <p className="correction-hint">
            推荐默认模型适合大多数文档；仅在你明确需要时切换。模型由平台 / WeKnora
            管理后台维护，此处不显示底座内部标识。
          </p>
          <div className="ws-form-grid">
            {slot(
              "嵌入模型 embedding",
              models.embeddingRef,
              models.setEmbeddingRef,
              models.embeddingOptions,
              false,
            )}
            {slot(
              "重排模型 rerank（可选）",
              models.rerankRef,
              models.setRerankRef,
              models.rerankOptions,
              true,
            )}
          </div>
        </div>
      )}
    </section>
  );
}
