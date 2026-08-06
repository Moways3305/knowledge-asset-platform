import { useCallback, useEffect, useState } from "react";
import { Database, RefreshCw } from "lucide-react";
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
import { PageHeader, PageSection, ProductPage } from "../components/ProductLayout";
import KbMigrateDialog from "../components/KbMigrateDialog";
import UnifiedModelConnectionsSection from "../components/UnifiedModelConnectionsSection";
import WeknoraModelsSection from "../components/WeknoraModelsSection";
import type { KbConfigDTO, ModelDTO } from "../types/weknoraAdmin";
import "./AdminWeKnoraModelsPage.css";

const scopeLabel: Record<string, string> = {
  company: "公司库",
  project: "项目库",
  personal: "个人库",
};
const mappingStatusLabel: Record<string, string> = {
  active: "已初始化",
  init_failed: "初始化失败",
  migrating: "迁移中",
};

function kbUpdateErrorMessage(caught: unknown): string {
  if (caught instanceof ApiError) {
    const messages: Record<string, string> = {
      weknora_kb_config_rejected: "知识库配置被底座拒绝，请检查所选模型是否兼容。",
      weknora_model_type_mismatch: "所选模型类型与配置项不匹配。",
      weknora_model_slot_unsupported: "当前底座不支持按知识库更新该模型。",
      weknora_kb_chat_model_missing: "知识库尚未配置问答模型，请先选择问答模型。",
    };
    if (caught.deniedReason && messages[caught.deniedReason]) {
      return messages[caught.deniedReason];
    }
    if (caught.status >= 400 && caught.status < 500) {
      return "知识库配置未保存，请检查所选模型。";
    }
  }
  return "知识库配置服务暂不可用，请稍后重试。";
}

export default function AdminWeKnoraModelsPage() {
  const { capabilities } = useAuth();
  const [models, setModels] = useState<ModelDTO[]>([]);
  const [kbConfigs, setKbConfigs] = useState<KbConfigDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [notConfigured, setNotConfigured] = useState(false);
  const [weknoraForbidden, setWeknoraForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [defaultChatRef, setDefaultChatRef] = useState("");
  const [defaultEmbeddingRef, setDefaultEmbeddingRef] = useState("");
  const [defaultRerankRef, setDefaultRerankRef] = useState("");
  const [defaultMultimodalRef, setDefaultMultimodalRef] = useState("");
  const [defaultsBusy, setDefaultsBusy] = useState(false);
  const [refreshSignal, setRefreshSignal] = useState(0);
  const isGlobalOperator = capabilities.isAdmin || capabilities.isGovernance;
  const canEdit = (isGlobalOperator || capabilities.isProjectManager) && !weknoraForbidden;

  const loadKnowledgeConfigs = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotConfigured(false);
    setWeknoraForbidden(false);
    try {
      const [availableModels, configs, defaults] = await Promise.all([
        fetchWeknoraModels(),
        fetchWeknoraKbConfigs(),
        isGlobalOperator
          ? fetchWeknoraDefaultModels()
          : Promise.resolve({
              embedding: null,
              rerank: null,
              chat: null,
              multimodal: null,
              updated_at: null,
            }),
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
      } else if (caught instanceof ApiError && caught.status === 403) {
        setWeknoraForbidden(true);
        setError("当前身份没有 WeKnora 管理权限，此区域保持只读。");
      } else {
        setError("知识库底座暂时无法加载，请刷新或检查 WeKnora 连接。");
      }
    } finally {
      setLoading(false);
    }
  }, [isGlobalOperator]);

  const refreshAll = () => {
    setRefreshSignal((value) => value + 1);
    void loadKnowledgeConfigs();
  };

  const saveFoundationDefaults = async () => {
    if (!defaultEmbeddingRef || !defaultChatRef) {
      setError("请配置默认嵌入模型和底座兼容 LLM。");
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
      setNote("WeKnora 底座默认模型已更新；外部 LLM 默认连接未改变。");
    } catch {
      setError("WeKnora 底座默认模型保存失败，请检查模型类型和底座连接。");
    } finally {
      setDefaultsBusy(false);
    }
  };

  const refreshSavedKbConfig = async (mappingId: string, message: string) => {
    setError(null);
    setNote(null);
    try {
      const refreshed = await fetchWeknoraKbConfigs();
      const savedConfig = refreshed.find((config) => config.mapping_id === mappingId);
      if (!savedConfig) {
        setNote(null);
        setError("知识库配置已保存，但暂时无法读取最新状态，请刷新后确认。");
        return;
      }
      setKbConfigs((current) =>
        current.map((config) => (config.mapping_id === mappingId ? savedConfig : config)),
      );
      setNote(message);
    } catch {
      setNote(null);
      setError("知识库配置已保存，但最新服务端状态读取失败，请刷新后确认。");
    }
  };

  useEffect(() => {
    void loadKnowledgeConfigs();
  }, [loadKnowledgeConfigs]);

  // 迁移作业进行中时，静默轮询 KB 配置以刷新进度。
  const anyMigrationActive = kbConfigs.some(
    (config) =>
      config.migration != null && ["queued", "running"].includes(config.migration.job_status),
  );
  useEffect(() => {
    if (!anyMigrationActive) return;
    const timer = window.setInterval(() => {
      void fetchWeknoraKbConfigs()
        .then((configs) => setKbConfigs(configs))
        .catch(() => {
          // 静默：下一轮轮询继续。
        });
    }, 5_000);
    return () => window.clearInterval(timer);
  }, [anyMigrationActive]);

  return (
    <ProductPage className="ws-page mf-page">
      <PageHeader
        title="模型与知识库底座"
        description="外部 LLM 由 KAP 直接调用；WeKnora 用于知识库底座。"
        actions={
          <button className="btn-small mf-refresh" onClick={refreshAll} disabled={loading}>
            <RefreshCw size={14} aria-hidden="true" />
            {loading ? "刷新中…" : "刷新"}
          </button>
        }
      />

      {isGlobalOperator && (
        <div className="mf-workspace">
          <div className="mf-model-panels">
            <UnifiedModelConnectionsSection canEdit refreshSignal={refreshSignal} />
            <WeknoraModelsSection canEdit refreshSignal={refreshSignal} />
          </div>

          <aside className="mf-foundation-panel" aria-labelledby="weknora-foundation-title">
            <div className="mf-panel-heading">
              <div>
                <span className="mf-panel-kicker">WEKNORA BASE</span>
                <h3 id="weknora-foundation-title">知识库底座</h3>
              </div>
              <span className="mf-foundation-mark" aria-hidden="true">
                <Database size={17} />
              </span>
            </div>

            {!capabilities.isAdmin && !capabilities.isGovernance && !weknoraForbidden && (
              <div className="mf-inline-message">当前身份仅可查看，修改需系统管理员。</div>
            )}
            {error && (
              <div className="mf-inline-message is-danger" role="alert">
                {error}
              </div>
            )}
            {note && <div className="mf-inline-message is-success">{note}</div>}

            {notConfigured ? (
              <div className="mf-foundation-empty">
                <strong>WeKnora 尚未配置</strong>
                <span>这不会影响左侧外部 LLM 的创建、编辑和测试。</span>
              </div>
            ) : loading ? (
              <div className="mf-foundation-empty">正在加载底座模型…</div>
            ) : error && models.length === 0 ? (
              <div className="mf-foundation-empty">
                <strong>底座配置不可用</strong>
                <span>外部 LLM 管理仍可独立使用。</span>
              </div>
            ) : (
              <div className="mf-foundation-fields">
                <FoundationModelSelect
                  label="默认嵌入模型"
                  description="用于新知识库向量化；已有库保持原绑定。"
                  value={defaultEmbeddingRef}
                  type="embedding"
                  models={models}
                  disabled={!canEdit || defaultsBusy}
                  onChange={setDefaultEmbeddingRef}
                />
                <FoundationModelSelect
                  label="底座兼容 LLM"
                  description="仅满足 WeKnora 初始化与检索契约。"
                  value={defaultChatRef}
                  type="chat"
                  models={models}
                  disabled={!canEdit || defaultsBusy}
                  onChange={setDefaultChatRef}
                />
                <FoundationModelSelect
                  label="默认重排模型"
                  description="可选，用于改善检索排序。"
                  value={defaultRerankRef}
                  type="rerank"
                  models={models}
                  disabled={!canEdit || defaultsBusy}
                  onChange={setDefaultRerankRef}
                  optional
                />
                <FoundationModelSelect
                  label="默认多模态模型"
                  description="可选，仅用于底座支持的多模态解析。"
                  value={defaultMultimodalRef}
                  type="vllm"
                  models={models}
                  disabled={!canEdit || defaultsBusy}
                  onChange={setDefaultMultimodalRef}
                  optional
                />
                {canEdit && (
                  <button
                    className="btn-small-primary mf-foundation-save"
                    onClick={() => void saveFoundationDefaults()}
                    disabled={defaultsBusy}
                  >
                    {defaultsBusy ? "保存中…" : "保存底座配置"}
                  </button>
                )}
              </div>
            )}
          </aside>
        </div>
      )}

      <PageSection
        className="mf-kb-section"
        title="知识库配置"
        description={
          isGlobalOperator
            ? "已有知识库保留嵌入锁定、模型类型校验与初始化失败恢复规则。"
            : "仅显示你担任项目经理的项目知识库，可在此修复初始化失败配置。"
        }
      >
        {notConfigured ? (
          <div className="mf-empty-state">
            <strong>知识库连接尚未配置</strong>
            <span>完成 WeKnora 部署配置后刷新，即可查看知识库。</span>
          </div>
        ) : loading ? (
          <div className="mf-empty-state">正在加载知识库配置…</div>
        ) : error && kbConfigs.length === 0 ? (
          <div className="mf-empty-state">
            <strong>知识库配置不可用</strong>
            <span>请刷新或检查当前管理权限与 WeKnora 连接。</span>
          </div>
        ) : kbConfigs.length === 0 ? (
          <div className="mf-empty-state">
            <strong>暂无知识库</strong>
            <span>创建公司、项目或个人知识库后，会在此显示底座绑定。</span>
          </div>
        ) : (
          <div className="ws-table-wrap mf-kb-table-wrap">
            <table className="ws-table mf-kb-table">
              <thead>
                <tr>
                  <th>知识库</th>
                  <th>范围 / 状态</th>
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
                    canEdit={canEdit}
                    defaultEmbeddingRef={defaultEmbeddingRef}
                    onSaved={refreshSavedKbConfig}
                    onError={(message) => {
                      setError(message);
                      setNote(null);
                    }}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mf-kb-footnote">
          初始化失败可在此调整兼容模型；索引失败资产仍在 <Link to="/admin/ingest">入库管理</Link>
          或资产详情中重试。
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
    <label className="mf-foundation-field">
      <span>{label}</span>
      <small>{description}</small>
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
    </label>
  );
}

function KbConfigRow({
  cfg,
  models,
  canEdit,
  defaultEmbeddingRef,
  onSaved,
  onError,
}: {
  cfg: KbConfigDTO;
  models: ModelDTO[];
  canEdit: boolean;
  defaultEmbeddingRef: string;
  onSaved: (mappingId: string, message: string) => Promise<void>;
  onError: (message: string) => void;
}) {
  const [chat, setChat] = useState(cfg.chat?.model_ref ?? "");
  const [embedding, setEmbedding] = useState(cfg.embedding?.model_ref ?? "");
  const [rerank, setRerank] = useState(cfg.rerank?.model_ref ?? "");
  const [multimodal, setMultimodal] = useState(cfg.multimodal?.model_ref ?? "");
  const [busy, setBusy] = useState(false);
  const [migrateOpen, setMigrateOpen] = useState(false);
  const migrationActive =
    cfg.migration != null && ["queued", "running"].includes(cfg.migration.job_status);

  useEffect(() => {
    setChat(cfg.chat?.model_ref ?? "");
    setEmbedding(cfg.embedding?.model_ref ?? "");
    setRerank(cfg.rerank?.model_ref ?? "");
    setMultimodal(cfg.multimodal?.model_ref ?? "");
  }, [cfg.chat, cfg.embedding, cfg.multimodal, cfg.rerank]);

  const options = (type: string) => models.filter((model) => model.type === type && model.enabled);
  const selector = (
    label: string,
    value: string,
    setter: (value: string) => void,
    type: string,
    current: { name: string | null } | null,
  ) => (
    <select
      className="ws-form-input"
      aria-label={`${cfg.kb_name} ${label}`}
      value={value}
      disabled={!canEdit || busy}
      onChange={(event) => setter(event.target.value)}
    >
      <option value="">{current?.name ? `保持：${current.name}` : "（未设置）"}</option>
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
      onError("请至少选择一个模型。");
      return;
    }
    setBusy(true);
    try {
      await updateWeknoraKbInit(cfg.mapping_id, body);
      const embeddingSwitched =
        Boolean(embedding) && embedding !== (cfg.embedding?.model_ref ?? "");
      await onSaved(
        cfg.mapping_id,
        embeddingSwitched
          ? `知识库“${cfg.kb_name}”配置已更新，嵌入模型已切换，请对库内文档执行重新解析以完成重新向量化。`
          : `知识库“${cfg.kb_name}”配置已更新。`,
      );
    } catch (caught) {
      onError(kbUpdateErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr className={cfg.mapping_status === "init_failed" ? "ws-row-disabled" : ""}>
      <td>
        <strong className="mf-kb-name">{cfg.kb_name}</strong>
        {(cfg.project_name || cfg.owner_name) && (
          <span className="mf-kb-context">{cfg.project_name ?? cfg.owner_name}</span>
        )}
      </td>
      <td>
        <span className="mf-kb-scope">{scopeLabel[cfg.scope] ?? cfg.scope}</span>
        <span
          className={`ws-status-pill ${cfg.mapping_status === "active" ? "ws-status-on" : "ws-status-off"}`}
        >
          {mappingStatusLabel[cfg.mapping_status] ?? cfg.mapping_status}
        </span>
      </td>
      <td>{selector("底座兼容", chat, setChat, "chat", cfg.chat)}</td>
      <td>{selector("嵌入", embedding, setEmbedding, "embedding", cfg.embedding)}</td>
      <td>{selector("重排", rerank, setRerank, "rerank", cfg.rerank)}</td>
      <td>{selector("多模态", multimodal, setMultimodal, "vllm", cfg.multimodal)}</td>
      <td>
        {canEdit && (
          <button
            className="btn-small-primary"
            onClick={() => void save()}
            disabled={busy || migrationActive}
          >
            {busy ? "保存中…" : "保存"}
          </button>
        )}
        {canEdit && (
          <button
            className="btn-small mf-migrate-btn"
            onClick={() => setMigrateOpen(true)}
            disabled={migrationActive}
            title="重建知识库并迁移到新的嵌入模型"
          >
            {migrationActive ? "迁移中…" : "迁移库"}
          </button>
        )}
        {cfg.migration && (
          <div className="mf-migrate-status">
            {cfg.migration.job_status === "completed" && "迁移完成，旧库已删除"}
            {cfg.migration.job_status === "completed_with_errors" &&
              `迁移完成（${cfg.migration.failed_count} 失败，可再次迁移续跑）`}
            {cfg.migration.job_status === "failed" && "迁移失败，可重试"}
            {migrationActive && (
              <>
                迁移中：{cfg.migration.success_count}/{cfg.migration.total_count} · 失败{" "}
                {cfg.migration.failed_count}
              </>
            )}
          </div>
        )}
        {cfg.config_error && <div className="ws-cell-suggestion">{cfg.config_error}</div>}
        <KbMigrateDialog
          cfg={cfg}
          models={models}
          defaultEmbeddingRef={defaultEmbeddingRef}
          open={migrateOpen}
          onClose={() => setMigrateOpen(false)}
          onMigrated={async (message) => {
            await onSaved(cfg.mapping_id, message);
          }}
        />
      </td>
    </tr>
  );
}
