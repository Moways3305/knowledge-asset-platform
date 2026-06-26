// 入库 / 建库时的模型选择状态（PBC-38）。
// 加载顾问可读模型选项，默认选中平台推荐（is_default）的 embedding / rerank，
// 暴露切换与「是否应禁用提交」给入口表单（上传确认区 / 个人知识库创建）。
//
// 安全：只持有对底座 id 不可逆的 model_ref（内存 useState），绝不写入
// localStorage / sessionStorage，绝不接触真实 model_id。
//
// 阻断语义：
// - WeKnora 已启用但平台默认 embedding 未配置（default_missing）→ blockSubmit=true，
//   提示「尚未配置默认模型，请联系管理员」。
// - WeKnora 未配置（503）→ 模型选择不适用，不阻断（索引会被安全跳过）。
import { useState, useEffect, useCallback } from "react";
import { ApiError } from "../api/http";
import { fetchModelOptions } from "../api/weknoraModels";
import type { ModelOptionDTO } from "../types/weknoraAdmin";

export interface ModelSelectionState {
  loading: boolean;
  loaded: boolean;
  // WeKnora 未配置（503）：模型选择不适用，不阻断入库。
  weknoraDisabled: boolean;
  // 平台默认 embedding 未配置（WeKnora 已启用）：必须阻断提交。
  defaultMissing: boolean;
  embeddingOptions: ModelOptionDTO[];
  rerankOptions: ModelOptionDTO[];
  // 选中的安全 model_ref（"" = 未选；提交时省略 → 后端走平台默认）。
  embeddingRef: string;
  rerankRef: string;
  setEmbeddingRef: (v: string) => void;
  setRerankRef: (v: string) => void;
  reload: () => void;
  // 是否应禁用提交：WeKnora 已启用且平台默认 embedding 缺失。
  blockSubmit: boolean;
}

export function useModelSelection(): ModelSelectionState {
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [weknoraDisabled, setWeknoraDisabled] = useState(false);
  const [defaultMissing, setDefaultMissing] = useState(false);
  const [embeddingOptions, setEmbeddingOptions] = useState<ModelOptionDTO[]>([]);
  const [rerankOptions, setRerankOptions] = useState<ModelOptionDTO[]>([]);
  const [embeddingRef, setEmbeddingRef] = useState("");
  const [rerankRef, setRerankRef] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchModelOptions();
      const emb = res.items.filter((m) => m.type === "embedding");
      const rer = res.items.filter((m) => m.type === "rerank");
      setEmbeddingOptions(emb);
      setRerankOptions(rer);
      setDefaultMissing(res.default_missing);
      setWeknoraDisabled(false);
      // 默认选中平台推荐模型（is_default）；无默认则留空。
      setEmbeddingRef(emb.find((m) => m.is_default)?.model_ref ?? "");
      setRerankRef(rer.find((m) => m.is_default)?.model_ref ?? "");
      setLoaded(true);
    } catch (e) {
      // WeKnora 未配置：不阻断既有入库流程（索引会被安全跳过），仅隐藏模型选择。
      if (e instanceof ApiError && e.status === 503) {
        setWeknoraDisabled(true);
      } else {
        setWeknoraDisabled(false);
      }
      setDefaultMissing(false);
      setEmbeddingOptions([]);
      setRerankOptions([]);
      setEmbeddingRef("");
      setRerankRef("");
      setLoaded(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const blockSubmit = loaded && !weknoraDisabled && defaultMissing;

  return {
    loading,
    loaded,
    weknoraDisabled,
    defaultMissing,
    embeddingOptions,
    rerankOptions,
    embeddingRef,
    rerankRef,
    setEmbeddingRef,
    setRerankRef,
    reload: () => void load(),
    blockSubmit,
  };
}
