import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchWeknoraDefaultModels,
  fetchWeknoraKbConfigs,
  fetchWeknoraModels,
  updateWeknoraDefaultModels,
  updateWeknoraKbInit,
} from "../api/admin";
import { ApiError } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import { PageHeader, PageSection, ProductPage, SettingsRow } from "../components/ProductLayout";
import UnifiedModelConnectionsSection from "../components/UnifiedModelConnectionsSection";
import type { KbConfigDTO, ModelDTO } from "../types/weknoraAdmin";

const scopeLabel: Record<string, string> = {
  company: "公司库",
  project: "项目库",
  personal: "个人库",
};
const mappingStatusLabel: Record<string, string> = {
  active: "已初始化",
  init_failed: "初始化失败",
};

function kbUpdateErrorMessage(caught: unknown): string {
  if (caught instanceof ApiError) {
    const messages: Record<string, string> = {
      weknora_kb_config_rejected: "知识库配置被底座拒绝，请检查所选模型是否兼容",
      weknora_embedding_locked: "知识库已有文件，不能更换嵌入模型",
      weknora_model_type_mismatch: "所选模型类型与配置项不匹配",
      weknora_model_slot_unsupported: "当前底座不支持按知识库更新该模型",
      weknora_kb_chat_model_missing: "知识库当前未配置问答模型，请先选择问答模型",
    };
    if (caught.deniedReason && messages[caught.deniedReason]) {
      return messages[caught.deniedReason];
    }
    if (caught.status >= 400 && caught.status < 500) {
      return "知识库配置未保存，请检查所选模型";
    }
  }
  return "模型连接服务暂不可用，请稍后重试";
}

export default function AdminWeKnoraModelsPage() {
  const { capabilities } = useAuth();
  const [models, setModels] = useState<ModelDTO[]>([]);
  const [kbConfigs, setKbConfigs] = useState<KbConfigDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [notConfigured, setNotConfigured] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [defaultChatRef, setDefaultChatRef] = useState("");
  const [defaultEmbeddingRef, setDefaultEmbeddingRef] = useState("");
  const [defaultRerankRef, setDefaultRerankRef] = useState("");
  const [defaultMultimodalRef, setDefaultMultimodalRef] = useState("");
  const [defaultsBusy, setDefaultsBusy] = useState(false);

  const loadKnowledgeConfigs = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotConfigured(false);
    try {
      const [availableModels, configs, defaults] = await Promise.all([
        fetchWeknoraModels(),
        fetchWeknoraKbConfigs(),
        fetchWeknoraDefaultModels(),
      ]);
      setModels(availableModels);
      setKbConfigs(configs);
      setDefaultChatRef(defaults.chat?.model_ref ?? "");
      setDefaultEmbeddingRef(defaults.embedding?.model_ref ?? "");
      setDefaultRerankRef(defaults.rerank?.model_ref ?? "");
      setDefaultMultimodalRef(defaults.multimodal?.model_ref ?? "");
    } catch (caught) {
      setModels([]);
      setKbConfigs([]);
      if (caught instanceof ApiError && caught.status === 503) {
        setNotConfigured(true);
      } else {
        setError("知识库配置暂时无法加载，请刷新或检查 WeKnora 连接");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const saveFoundationDefaults = async () => {
    if (!defaultEmbeddingRef || !defaultChatRef) {
      setError("请配置底座默认嵌入模型和底座兼容 LLM 槽位");
      return;
    }
    setDefaultsBusy(true);
    setError(null);
    try {
      const updated = await updateWeknoraDefaultModels({
        embedding_model_ref: defaultEmbeddingRef,
        chat_model_ref: defaultChatRef,
        rerank_model_ref: defaultRerankRef || null,
        multimodal_ref: defaultMultimodalRef || null,
      });
      setDefaultChatRef(updated.chat?.model_ref ?? "");
      setDefaultEmbeddingRef(updated.embedding?.model_ref ?? "");
      setDefaultRerankRef(updated.rerank?.model_ref ?? "");
      setDefaultMultimodalRef(updated.multimodal?.model_ref ?? "");
      setNote("WeKnora 底座默认模型已更新；外部 LLM 默认连接未改变");
    } catch {
      setError("WeKnora 底座默认模型保存失败，请检查模型类型和底座连接");
    } finally {
      setDefaultsBusy(false);
    }
  };

  useEffect(() => {
    void loadKnowledgeConfigs();
  }, [loadKnowledgeConfigs]);

  return (
    <ProductPage className="ws-page">
      <PageHeader
        title="外部 LLM 与知识库底座"
        description="外部 LLM 由 KAP 直接调用；WeKnora 模型仅服务知识库初始化、检索与底座兼容。"
        actions={
          <button
            className="btn-small"
            onClick={() => void loadKnowledgeConfigs()}
            disabled={loading}
          >
            {loading ? "加载中…" : "刷新"}
          </button>
        }
      />

      <UnifiedModelConnectionsSection canEdit={capabilities.isAdmin} />

      <PageSection
        title="WeKnora 底座默认模型"
        description="用于新知识库初始化和检索底座。修改默认值不会重建知识库，也不会改变已有库的嵌入绑定。"
      >
        {notConfigured ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">WeKnora 尚未配置</div>
            <p className="ig-empty-desc">此状态不影响上方外部 LLM 连接的创建、编辑和测试。</p>
          </div>
        ) : loading ? (
          <div className="ig-empty-state">正在加载底座默认模型…</div>
        ) : (
          <div className="product-settings-list">
            <FoundationModelSelect
              label="默认嵌入模型"
              description="新知识库的向量化模型；已有知识库保持原绑定。"
              value={defaultEmbeddingRef}
              type="embedding"
              models={models}
              disabled={!capabilities.isAdmin || defaultsBusy}
              onChange={setDefaultEmbeddingRef}
            />
            <FoundationModelSelect
              label="底座兼容配置（LLM 槽位）"
              description="满足当前 WeKnora 初始化契约，不控制 KAP 内容生成或项目问答。"
              value={defaultChatRef}
              type="chat"
              models={models}
              disabled={!capabilities.isAdmin || defaultsBusy}
              onChange={setDefaultChatRef}
            />
            <FoundationModelSelect
              label="默认重排模型"
              description="用于改善底座检索排序，可按部署能力选择。"
              value={defaultRerankRef}
              type="rerank"
              models={models}
              disabled={!capabilities.isAdmin || defaultsBusy}
              onChange={setDefaultRerankRef}
              optional
            />
            <FoundationModelSelect
              label="默认多模态模型"
              description="仅用于底座支持的多模态解析能力。"
              value={defaultMultimodalRef}
              type="vllm"
              models={models}
              disabled={!capabilities.isAdmin || defaultsBusy}
              onChange={setDefaultMultimodalRef}
              optional
            />
            {capabilities.isAdmin && (
              <div>
                <button
                  className="btn-small-primary"
                  onClick={() => void saveFoundationDefaults()}
                  disabled={defaultsBusy}
                >
                  {defaultsBusy ? "保存中…" : "保存 WeKnora 底座默认模型"}
                </button>
              </div>
            )}
          </div>
        )}
      </PageSection>

      <PageSection
        title="知识库配置"
        description="查看每个知识库当前绑定模型；已有库的嵌入模型锁定和失败恢复规则保持不变。"
      >
        {note && <div className="product-inline-note">{note}</div>}
        {error && (
          <div className="product-inline-note is-danger" role="alert">
            {error}
          </div>
        )}
        {notConfigured ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">知识库连接尚未配置</div>
            <p className="ig-empty-desc">
              内容生成连接仍可管理；完成 WeKnora 部署配置后刷新本页即可查看知识库。
            </p>
          </div>
        ) : loading ? (
          <div className="ig-empty-state">正在加载知识库配置…</div>
        ) : kbConfigs.length === 0 ? (
          <div className="ig-empty-state">
            <div className="ig-empty-title">暂无知识库</div>
            <p className="ig-empty-desc">入库或创建项目后，会在此显示各知识库当前绑定的模型。</p>
          </div>
        ) : (
          <div className="ws-table-wrap">
            <table className="ws-table">
              <thead>
                <tr>
                  <th>知识库</th>
                  <th>范围</th>
                  <th>状态</th>
                  <th>底座兼容</th>
                  <th>嵌入</th>
                  <th>重排</th>
                  <th>多模态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {kbConfigs.map((config) => (
                  <KbConfigRow
                    key={config.mapping_id}
                    cfg={config}
                    models={models}
                    onSaved={(message) => {
                      setNote(message);
                      void loadKnowledgeConfigs();
                    }}
                    onError={setError}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="au-note" style={{ margin: 12 }}>
          初始化失败的知识库可在此调整兼容模型后恢复；索引失败资产仍在{" "}
          <Link to="/admin/ingest">入库管理</Link>或资产详情中重试。
        </p>
      </PageSection>
    </ProductPage>
  );
}

function FoundationModelSelect({
  label,
  description,
  value,
  type,
  models,
  disabled,
  onChange,
  optional = false,
}: {
  label: string;
  description: string;
  value: string;
  type: string;
  models: ModelDTO[];
  disabled: boolean;
  onChange: (value: string) => void;
  optional?: boolean;
}) {
  const options = models.filter((model) => model.type === type && model.enabled);
  return (
    <SettingsRow
      title={label}
      description={description}
      control={
        <select
          aria-label={label}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">{optional ? "暂不设置" : "请选择底座模型"}</option>
          {options.map((model) => (
            <option key={model.model_ref} value={model.model_ref}>
              {model.name}
            </option>
          ))}
        </select>
      }
    />
  );
}

function KbConfigRow({
  cfg,
  models,
  onSaved,
  onError,
}: {
  cfg: KbConfigDTO;
  models: ModelDTO[];
  onSaved: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [chat, setChat] = useState(cfg.chat?.model_ref ?? "");
  const [embedding, setEmbedding] = useState(cfg.embedding?.model_ref ?? "");
  const [rerank, setRerank] = useState(cfg.rerank?.model_ref ?? "");
  const [multimodal, setMultimodal] = useState(cfg.multimodal?.model_ref ?? "");
  const [busy, setBusy] = useState(false);

  const options = (type: string) => models.filter((model) => model.type === type && model.enabled);
  const selector = (
    value: string,
    setter: (value: string) => void,
    type: string,
    current: { name: string | null } | null,
  ) => (
    <select
      className="ws-form-input"
      value={value}
      onChange={(event) => setter(event.target.value)}
    >
      <option value="">{current?.name ? `保持（${current.name}）` : "（未设置）"}</option>
      {options(type).map((model) => (
        <option key={model.model_ref} value={model.model_ref}>
          {model.name}
        </option>
      ))}
    </select>
  );

  const save = async () => {
    const body: Record<string, string> = {};
    if (chat) body.chat_model_ref = chat;
    if (embedding) body.embedding_model_ref = embedding;
    if (rerank) body.rerank_model_ref = rerank;
    if (multimodal) body.multimodal_ref = multimodal;
    if (Object.keys(body).length === 0) {
      onError("请至少选择一个模型");
      return;
    }
    setBusy(true);
    try {
      await updateWeknoraKbInit(cfg.mapping_id, body);
      onSaved(`知识库「${cfg.kb_name}」配置已更新`);
    } catch (caught) {
      onError(kbUpdateErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr className={cfg.mapping_status === "init_failed" ? "ws-row-disabled" : ""}>
      <td>
        {cfg.kb_name}
        {cfg.project_name ? ` · ${cfg.project_name}` : ""}
        {cfg.owner_name ? ` · ${cfg.owner_name}` : ""}
      </td>
      <td>{scopeLabel[cfg.scope] ?? cfg.scope}</td>
      <td>
        <span
          className={`ws-status-pill ${cfg.mapping_status === "active" ? "ws-status-on" : "ws-status-off"}`}
        >
          {mappingStatusLabel[cfg.mapping_status] ?? cfg.mapping_status}
        </span>
      </td>
      <td>{selector(chat, setChat, "chat", cfg.chat)}</td>
      <td>{selector(embedding, setEmbedding, "embedding", cfg.embedding)}</td>
      <td>{selector(rerank, setRerank, "rerank", cfg.rerank)}</td>
      <td>{selector(multimodal, setMultimodal, "vllm", cfg.multimodal)}</td>
      <td>
        <button className="btn-small-primary" onClick={() => void save()} disabled={busy}>
          {busy ? "保存中…" : "保存"}
        </button>
        {cfg.config_error && <div className="ws-cell-suggestion">{cfg.config_error}</div>}
      </td>
    </tr>
  );
}
