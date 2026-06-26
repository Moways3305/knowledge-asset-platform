import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useModelSelection } from "./useModelSelection";
import { ApiError } from "../api/http";

const api = vi.hoisted(() => ({ fetchModelOptions: vi.fn() }));
vi.mock("../api/weknoraModels", () => api);

const embDefault = {
  model_ref: "ref_emb_default",
  name: "BGE 嵌入",
  type: "embedding",
  provider: "siliconflow",
  description: null,
  enabled: true,
  is_default: true,
};
const rerDefault = {
  model_ref: "ref_rer_default",
  name: "BGE 重排",
  type: "rerank",
  provider: "siliconflow",
  description: null,
  enabled: true,
  is_default: true,
};

describe("useModelSelection", () => {
  beforeEach(() => {
    api.fetchModelOptions.mockReset();
  });

  it("默认存在时自动选中平台推荐 embedding/rerank，不阻断提交", async () => {
    api.fetchModelOptions.mockResolvedValue({
      items: [embDefault, rerDefault],
      default_missing: false,
    });
    const { result } = renderHook(() => useModelSelection());
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.embeddingRef).toBe("ref_emb_default");
    expect(result.current.rerankRef).toBe("ref_rer_default");
    expect(result.current.blockSubmit).toBe(false);
  });

  it("默认 embedding 缺失时 blockSubmit=true", async () => {
    api.fetchModelOptions.mockResolvedValue({
      items: [{ ...embDefault, is_default: false }],
      default_missing: true,
    });
    const { result } = renderHook(() => useModelSelection());
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.embeddingRef).toBe("");
    expect(result.current.blockSubmit).toBe(true);
  });

  it("WeKnora 未配置（503）时不阻断提交，仅标记 weknoraDisabled", async () => {
    api.fetchModelOptions.mockRejectedValue(
      new ApiError(503, "WeKnora 未配置", "weknora_not_configured"),
    );
    const { result } = renderHook(() => useModelSelection());
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.weknoraDisabled).toBe(true);
    expect(result.current.blockSubmit).toBe(false);
  });

  it("绝不把 model_ref 写入 localStorage / sessionStorage", async () => {
    const lsSet = vi.spyOn(Storage.prototype, "setItem");
    api.fetchModelOptions.mockResolvedValue({
      items: [embDefault, rerDefault],
      default_missing: false,
    });
    const { result } = renderHook(() => useModelSelection());
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(lsSet).not.toHaveBeenCalled();
    lsSet.mockRestore();
  });
});
