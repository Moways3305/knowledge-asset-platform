import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ModelAdvancedSettings from "./ModelAdvancedSettings";
import type { ModelSelectionState } from "../hooks/useModelSelection";

// 构造受控的模型选择状态，直接驱动展示分支（不触发网络）。
function makeModels(over: Partial<ModelSelectionState> = {}): ModelSelectionState {
  return {
    loading: false,
    loaded: true,
    weknoraDisabled: false,
    defaultMissing: false,
    embeddingOptions: [
      {
        model_ref: "ref_emb_default",
        name: "BGE 嵌入",
        type: "embedding",
        provider: "siliconflow",
        description: null,
        enabled: true,
        is_default: true,
      },
      {
        model_ref: "ref_emb_alt",
        name: "M3E 嵌入",
        type: "embedding",
        provider: "local",
        description: null,
        enabled: true,
        is_default: false,
      },
    ],
    rerankOptions: [
      {
        model_ref: "ref_rer_default",
        name: "BGE 重排",
        type: "rerank",
        provider: "siliconflow",
        description: null,
        enabled: true,
        is_default: true,
      },
    ],
    embeddingRef: "ref_emb_default",
    rerankRef: "ref_rer_default",
    setEmbeddingRef: vi.fn(),
    setRerankRef: vi.fn(),
    reload: vi.fn(),
    blockSubmit: false,
    ...over,
  };
}

describe("ModelAdvancedSettings", () => {
  it("默认折叠；展开后默认选中平台推荐 embedding", async () => {
    render(<ModelAdvancedSettings models={makeModels()} />);
    // 折叠态：选择框未渲染。
    expect(screen.queryByLabelText("嵌入模型 embedding")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /高级设置/ }));
    const sel = screen.getByLabelText("嵌入模型 embedding") as HTMLSelectElement;
    expect(sel.value).toBe("ref_emb_default");
  });

  it("切换模型调用 setter（普通顾问可切换）", async () => {
    const m = makeModels();
    render(<ModelAdvancedSettings models={m} />);
    await userEvent.click(screen.getByRole("button", { name: /高级设置/ }));
    await userEvent.selectOptions(screen.getByLabelText("嵌入模型 embedding"), "ref_emb_alt");
    expect(m.setEmbeddingRef).toHaveBeenCalledWith("ref_emb_alt");
  });

  it("不渲染真实 model_id（仅 model_ref 作为 option value + 安全名称展示）", async () => {
    render(<ModelAdvancedSettings models={makeModels()} />);
    await userEvent.click(screen.getByRole("button", { name: /高级设置/ }));
    // 展示模型名，选项值是对底座 id 不可逆的 model_ref，不含任何真实 server-only id。
    expect(screen.getByText(/BGE 嵌入/)).toBeInTheDocument();
    const sel = screen.getByLabelText("嵌入模型 embedding") as HTMLSelectElement;
    const values = Array.from(sel.options).map((o) => o.value);
    expect(values).toEqual(["ref_emb_default", "ref_emb_alt"]);
  });

  it("默认 embedding 缺失时显示安全提示且不渲染选择框", () => {
    render(
      <ModelAdvancedSettings models={makeModels({ defaultMissing: true, blockSubmit: true })} />,
    );
    expect(
      screen.getByText("尚未配置默认嵌入或问答模型，请联系管理员在模型配置中设置。"),
    ).toBeInTheDocument();
  });

  it("WeKnora 未配置时整块不渲染", () => {
    const { container } = render(
      <ModelAdvancedSettings models={makeModels({ weknoraDisabled: true })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
