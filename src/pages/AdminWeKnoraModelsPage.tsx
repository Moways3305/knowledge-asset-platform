import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchWeknoraKbConfigs, fetchWeknoraModels, updateWeknoraKbInit } from "../api/admin";
import { ApiError } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import { PageHeader, PageSection, ProductPage } from "../components/ProductLayout";
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

export default function AdminWeKnoraModelsPage() {
  const { capabilities } = useAuth();
  const [models, setModels] = useState<ModelDTO[]>([]);
  const [kbConfigs, setKbConfigs] = useState<KbConfigDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [notConfigured, setNotConfigured] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const loadKnowledgeConfigs = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotConfigured(false);
    try {
      const [availableModels, configs] = await Promise.all([
        fetchWeknoraModels(),
        fetchWeknoraKbConfigs(),
      ]);
      setModels(availableModels);
      setKbConfigs(configs);
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

  useEffect(() => {
    void loadKnowledgeConfigs();
  }, [loadKnowledgeConfigs]);

  return (
    <ProductPage className="ws-page">
      <PageHeader
        title="模型与知识库配置"
        description="统一管理模型连接，并为内容生成和知识库分别指定用途。"
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
                  <th>问答</th>
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
      onError(caught instanceof ApiError ? caught.message : "更新知识库配置失败");
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
