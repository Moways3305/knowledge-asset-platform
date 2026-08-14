import { useCallback, useEffect, useMemo, useState } from "react";
import { Bot, Database, RefreshCw, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import {
  fetchWeknoraDefaultModels,
  fetchWeknoraKbConfigs,
  fetchWeknoraModels,
  updateWeknoraDefaultModels,
  updateWeknoraKbInit,
} from "../api/admin";
import {
  fetchModelConnections,
  fetchModelUsageAssignments,
  updateModelUsageAssignments,
} from "../api/modelConnections";
import { ApiError } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import DetailDrawer from "../components/DetailDrawer";
import KbMigrateDialog from "../components/KbMigrateDialog";
import OperationStatusCard from "../components/OperationStatusCard";
import { operationStatusFromJob } from "../components/operationStatus";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import TaskModal from "../components/TaskModal";
import UnifiedModelConnectionsSection from "../components/UnifiedModelConnectionsSection";
import WeknoraModelsSection from "../components/WeknoraModelsSection";
import type { ModelConnectionDTO } from "../types/modelConnections";
import type { KbConfigDTO, ModelDTO, WeknoraDefaultModelsDTO } from "../types/weknoraAdmin";
import "./AdminWeKnoraModelsPage.css";

type DrawerKind = "external" | "weknora" | "knowledge" | "migration" | null;

const scopeLabel: Record<string, string> = {
  company: "公司库",
  project: "项目库",
  personal: "个人库",
};

const mappingStatusLabel: Record<string, string> = {
  active: "已初始化",
  init_failed: "初始化异常",
  migrating: "迁移中",
};

const emptyDefaults: WeknoraDefaultModelsDTO = {
  embedding: null,
  rerank: null,
  chat: null,
  multimodal: null,
  updated_at: null,
};

function kbUpdateErrorMessage(caught: unknown): string {
  if (caught instanceof ApiError) {
    const messages: Record<string, string> = {
      weknora_kb_config_rejected: "知识库配置被底座拒绝，请检查所选模型是否兼容。",
      weknora_model_type_mismatch: "所选模型类型与配置项不匹配。",
      weknora_model_slot_unsupported: "当前底座不支持更新该模型。",
      weknora_kb_chat_model_missing: "请先选择底座兼容 LLM。",
    };
    if (caught.deniedReason && messages[caught.deniedReason]) return messages[caught.deniedReason];
  }
  return "知识库配置未保存，请检查模型状态后重试。";
}

function slotName(slot: { name: string | null } | null): string {
  return slot?.name?.trim() || "未设置";
}

export default function AdminWeKnoraModelsPage() {
  const { capabilities } = useAuth();
  const isGlobalOperator = capabilities.isAdmin || capabilities.isGovernance;
  const [models, setModels] = useState<ModelDTO[]>([]);
  const [kbConfigs, setKbConfigs] = useState<KbConfigDTO[]>([]);
  const [defaults, setDefaults] = useState<WeknoraDefaultModelsDTO>(emptyDefaults);
  const [externalConnections, setExternalConnections] = useState<ModelConnectionDTO[]>([]);
  const [externalDefaultRef, setExternalDefaultRef] = useState("");
  const [loading, setLoading] = useState(true);
  const [notConfigured, setNotConfigured] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<DrawerKind>(null);
  const [defaultsModal, setDefaultsModal] = useState<"external" | "foundation" | null>(null);
  const [selectedKb, setSelectedKb] = useState<KbConfigDTO | null>(null);
  const [migrationKb, setMigrationKb] = useState<KbConfigDTO | null>(null);
  const [migrationResult, setMigrationResult] = useState<KbConfigDTO | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [kbQuery, setKbQuery] = useState("");
  const [kbScope, setKbScope] = useState("all");
  const [kbStatus, setKbStatus] = useState("all");
  const [kbDraft, setKbDraft] = useState({ chat: "", embedding: "", rerank: "", multimodal: "" });
  const [foundationDraft, setFoundationDraft] = useState({
    chat: "",
    embedding: "",
    rerank: "",
    multimodal: "",
  });

  const canEdit = (isGlobalOperator || capabilities.isProjectManager) && !forbidden;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotConfigured(false);
    setForbidden(false);
    try {
      const [availableModels, configs, modelDefaults] = await Promise.all([
        fetchWeknoraModels(),
        fetchWeknoraKbConfigs(),
        isGlobalOperator ? fetchWeknoraDefaultModels() : Promise.resolve(emptyDefaults),
      ]);
      setModels(availableModels);
      setKbConfigs(configs);
      setDefaults(modelDefaults);
      if (isGlobalOperator) {
        const [connections, assignments] = await Promise.all([
          fetchModelConnections(),
          fetchModelUsageAssignments(),
        ]);
        setExternalConnections(connections.items);
        setExternalDefaultRef(assignments.external_llm_default?.model_ref ?? "");
      }
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 503) setNotConfigured(true);
      else if (caught instanceof ApiError && caught.status === 403) {
        setForbidden(true);
        setError("当前身份仅可查看允许的配置摘要。");
      } else setError("模型与知识库配置暂时无法加载，请刷新后重试。");
    } finally {
      setLoading(false);
    }
  }, [isGlobalOperator]);

  useEffect(() => {
    void load();
  }, [load]);

  const migrationActive = kbConfigs.some((config) =>
    ["queued", "running"].includes(config.migration?.job_status ?? ""),
  );
  useEffect(() => {
    if (!migrationActive) return;
    const timer = window.setInterval(() => {
      void fetchWeknoraKbConfigs()
        .then(setKbConfigs)
        .catch(() => undefined);
    }, 5_000);
    return () => window.clearInterval(timer);
  }, [migrationActive]);

  const counts = useMemo(() => {
    const migrating = kbConfigs.filter((item) => item.mapping_status === "migrating").length;
    const anomalies = kbConfigs.filter(
      (item) => item.mapping_status === "init_failed" || (item.migration?.failed_count ?? 0) > 0,
    ).length;
    return {
      pending: kbConfigs.filter((item) => item.mapping_status === "init_failed").length,
      migrating,
      anomalies,
      company: kbConfigs.filter((item) => item.scope === "company").length,
      project: kbConfigs.filter((item) => item.scope === "project").length,
      personal: kbConfigs.filter((item) => item.scope === "personal").length,
    };
  }, [kbConfigs]);
  const modelIssues = models.filter(
    (model) => model.enabled && model.credential_status === "missing",
  ).length;
  const externalIssues = externalConnections.filter(
    (connection) => connection.enabled && connection.health_status !== "healthy",
  ).length;
  const connectionIssues = counts.anomalies + (isGlobalOperator ? modelIssues + externalIssues : 0);
  const availableConnections = isGlobalOperator
    ? externalConnections.filter(
        (connection) => connection.enabled && connection.health_status === "healthy",
      ).length +
      models.filter((model) => model.enabled && model.credential_status !== "missing").length
    : kbConfigs.filter((config) => config.mapping_status === "active").length;

  const filteredKbs = useMemo(() => {
    const query = kbQuery.trim().toLowerCase();
    return kbConfigs.filter((item) => {
      const readableName =
        `${item.kb_name} ${item.project_name ?? ""} ${item.owner_name ?? ""}`.toLowerCase();
      const statusMatches =
        kbStatus === "all" ||
        (kbStatus === "exception"
          ? item.mapping_status === "init_failed" || (item.migration?.failed_count ?? 0) > 0
          : item.mapping_status === kbStatus);
      return (
        (!query || readableName.includes(query)) &&
        (kbScope === "all" || item.scope === kbScope) &&
        statusMatches
      );
    });
  }, [kbConfigs, kbQuery, kbScope, kbStatus]);

  const displayedMigrationResult = useMemo(() => {
    if (!migrationResult) return null;
    return (
      kbConfigs.find((config) => config.mapping_id === migrationResult.mapping_id) ??
      migrationResult
    );
  }, [kbConfigs, migrationResult]);

  const refreshAll = () => {
    setRefreshSignal((value) => value + 1);
    void load();
  };

  const openFoundationDefaults = () => {
    setFoundationDraft({
      chat: defaults.chat?.model_ref ?? "",
      embedding: defaults.embedding?.model_ref ?? "",
      rerank: defaults.rerank?.model_ref ?? "",
      multimodal: defaults.multimodal?.model_ref ?? "",
    });
    setDefaultsModal("foundation");
  };

  const saveFoundationDefaults = async () => {
    if (!foundationDraft.embedding || !foundationDraft.chat) {
      setError("请选择默认嵌入模型和底座兼容 LLM。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await updateWeknoraDefaultModels({
        embedding_model_ref: foundationDraft.embedding,
        chat_model_ref: foundationDraft.chat,
        rerank_model_ref: foundationDraft.rerank || null,
        multimodal_ref: foundationDraft.multimodal || null,
      });
      setDefaults(updated);
      setDefaultsModal(null);
      setNote("默认底座配置已保存。已有知识库仍保留各自绑定。");
    } catch {
      setError("默认底座配置未保存，请检查模型类型和连接状态。");
    } finally {
      setBusy(false);
    }
  };

  const saveExternalDefault = async () => {
    setBusy(true);
    setError(null);
    try {
      await updateModelUsageAssignments({
        external_llm_default_ref: externalDefaultRef || undefined,
      });
      setDefaultsModal(null);
      setNote("外部 LLM 默认用途已保存。WeKnora 底座配置未改变。");
      await load();
    } catch {
      setError("默认用途未保存，请选择已启用且可用的连接。");
    } finally {
      setBusy(false);
    }
  };

  const openKbConfig = (config: KbConfigDTO) => {
    setDrawer(null);
    setKbDraft({
      chat: config.chat?.model_ref ?? "",
      embedding: config.embedding?.model_ref ?? "",
      rerank: config.rerank?.model_ref ?? "",
      multimodal: config.multimodal?.model_ref ?? "",
    });
    setSelectedKb(config);
  };

  const saveKbConfig = async () => {
    if (
      !selectedKb ||
      (!kbDraft.chat && !kbDraft.embedding && !kbDraft.rerank && !kbDraft.multimodal)
    ) {
      setError("请至少选择一个模型。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await updateWeknoraKbInit(selectedKb.mapping_id, {
        chat_model_ref: kbDraft.chat || null,
        embedding_model_ref: kbDraft.embedding || null,
        rerank_model_ref: kbDraft.rerank || null,
        multimodal_ref: kbDraft.multimodal || null,
      });
      setSelectedKb(null);
      await load();
      setDrawer("knowledge");
      setNote(`知识库“${selectedKb.kb_name}”配置已保存。`);
    } catch (caught) {
      setError(kbUpdateErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const openMigration = (config: KbConfigDTO) => {
    setSelectedKb(null);
    setDrawer(null);
    setMigrationKb(config);
  };

  const showMigrationResult = (config: KbConfigDTO) => {
    setDrawer(null);
    setMigrationResult(config);
    setDrawer("migration");
  };

  return (
    <ProductPage className="ws-page mf-page mf-overview-page admin-control-page">
      <PageHeader
        title="模型配置"
        description="先处理不可用连接，再维护模型与知识库底座。"
        status={
          <StatusBadge
            tone={error ? "danger" : migrationActive ? "info" : loading ? "info" : "success"}
            label={
              error
                ? "配置需要处理"
                : migrationActive
                  ? "迁移处理中"
                  : loading
                    ? "正在同步"
                    : "运行状态已同步"
            }
          />
        }
        actions={
          <div className="mf-page-actions">
            <button
              className="btn-small-primary"
              onClick={() =>
                setDrawer(
                  !isGlobalOperator || counts.anomalies
                    ? "knowledge"
                    : externalIssues
                      ? "external"
                      : modelIssues
                        ? "weknora"
                        : "external",
                )
              }
            >
              {!isGlobalOperator
                ? counts.anomalies
                  ? "处理知识库异常"
                  : "管理知识库配置"
                : connectionIssues
                  ? "处理连接异常"
                  : "管理模型连接"}
            </button>
            <button
              className="btn-small mf-refresh"
              onClick={refreshAll}
              disabled={loading}
              aria-label="刷新连接状态"
            >
              <RefreshCw size={14} aria-hidden="true" />
            </button>
          </div>
        }
      />

      <section className="admin-status-band" aria-label="连接运行状态">
        <div className={connectionIssues ? "is-danger" : ""}>
          <strong>{connectionIssues}</strong>
          <span>需要处理</span>
          <small>{isGlobalOperator ? "凭据、初始化或迁移异常" : "知识库初始化或迁移异常"}</small>
        </div>
        <div className="is-processing">
          <strong>{counts.migrating}</strong>
          <span>处理中</span>
          <small>知识库迁移任务</small>
        </div>
        <div>
          <strong>{availableConnections}</strong>
          <span>{isGlobalOperator ? "可用连接" : "可用知识库"}</span>
          <small>{isGlobalOperator ? "已启用且通过状态检查" : "当前项目范围"}</small>
        </div>
      </section>

      {error && (
        <div className="mf-inline-message is-danger" role="alert">
          {error}
        </div>
      )}
      {note && (
        <div className="mf-inline-message is-success" role="status">
          {note}
        </div>
      )}
      {!canEdit && !loading && (
        <div className="mf-inline-message">当前身份为只读视图，修改与迁移动作已隐藏。</div>
      )}

      <section className="mf-connection-workspace admin-workspace-panel" aria-label="连接管理">
        <div className="admin-workspace-heading">
          <h2>连接管理</h2>
          <span>名称 · 可用状态 · 影响范围 · 下一步</span>
        </div>
        <div className="mf-connection-rows">
          <div className="mf-connection-row">
            <Sparkles size={19} aria-hidden="true" />
            <div>
              <h3>外部 LLM</h3>
              <small>内容生成与项目问答</small>
            </div>
            <StatusBadge
              tone={externalIssues ? "danger" : "success"}
              label={
                externalIssues
                  ? `${externalIssues} 个连接异常`
                  : `${externalConnections.filter((item) => item.enabled).length} 个连接可用`
              }
            />
            <span>{externalDefaultRef ? "默认用途已配置" : "下一步：设置默认用途"}</span>
            <button
              className="btn-small"
              aria-label="管理外部 LLM"
              onClick={() => setDrawer("external")}
            >
              查看连接
            </button>
          </div>
          <div className="mf-connection-row">
            <Bot size={19} aria-hidden="true" />
            <div>
              <h3>WeKnora 底座</h3>
              <small>嵌入、对话、重排与多模态</small>
            </div>
            <StatusBadge
              tone={modelIssues ? "danger" : "success"}
              label={
                modelIssues
                  ? `${modelIssues} 个凭据缺失`
                  : `${models.filter((item) => item.enabled).length} 个模型启用`
              }
            />
            <span>
              {modelIssues ? "下一步：补齐凭据" : `默认嵌入：${slotName(defaults.embedding)}`}
            </span>
            <button
              className="btn-small"
              aria-label="管理 WeKnora 模型"
              onClick={() => setDrawer("weknora")}
            >
              查看底座
            </button>
          </div>
          <div className="mf-connection-row">
            <Database size={19} aria-hidden="true" />
            <div>
              <h3>知识库配置</h3>
              <small>公司、项目与个人知识库</small>
            </div>
            <StatusBadge
              tone={counts.anomalies ? "danger" : counts.migrating ? "info" : "success"}
              label={
                counts.anomalies
                  ? `${counts.anomalies} 项异常`
                  : counts.migrating
                    ? `${counts.migrating} 项迁移中`
                    : `${kbConfigs.length} 个知识库可用`
              }
            />
            <span>
              {counts.anomalies ? "下一步：修复初始化或迁移" : `待初始化 ${counts.pending} 项`}
            </span>
            <button
              className="btn-small"
              aria-label="管理知识库配置"
              onClick={() => setDrawer("knowledge")}
            >
              查看知识库
            </button>
          </div>
        </div>
      </section>

      {notConfigured && (
        <div className="mf-overview-empty">
          <strong>WeKnora 尚未配置</strong>
          <span>外部 LLM 仍可独立管理；完成底座部署后刷新即可。</span>
        </div>
      )}
      <p className="mf-kb-footnote">
        索引失败资产仍在 <Link to="/admin/ingest">入库管理</Link> 或资产详情中重试。
      </p>

      <DetailDrawer
        open={drawer === "external"}
        title="管理外部 LLM"
        description="搜索、测试并维护 KAP 直接调用的模型连接。"
        onClose={() => {
          setDrawer(null);
          void load();
        }}
      >
        {canEdit && isGlobalOperator && (
          <div className="mf-drawer-secondary-actions">
            <button className="btn-small" onClick={() => setDefaultsModal("external")}>
              编辑默认用途
            </button>
          </div>
        )}
        <UnifiedModelConnectionsSection
          canEdit={canEdit && isGlobalOperator}
          refreshSignal={refreshSignal}
          showUsageControls={false}
        />
      </DetailDrawer>

      <DetailDrawer
        open={drawer === "weknora"}
        title="管理 WeKnora 模型"
        description="维护知识库底座可选择的模型，不展示凭据或内部地址。"
        onClose={() => {
          setDrawer(null);
          void load();
        }}
      >
        {canEdit && isGlobalOperator && (
          <div className="mf-drawer-secondary-actions">
            <button className="btn-small" onClick={openFoundationDefaults}>
              编辑默认底座
            </button>
          </div>
        )}
        <WeknoraModelsSection canEdit={canEdit && isGlobalOperator} refreshSignal={refreshSignal} />
      </DetailDrawer>

      <DetailDrawer
        open={drawer === "knowledge"}
        title="管理知识库配置"
        description="按名称、范围和运行状态查找知识库。"
        onClose={() => setDrawer(null)}
      >
        <div className="mf-drawer-filters">
          <input
            aria-label="搜索知识库"
            placeholder="搜索知识库、项目或归属人"
            value={kbQuery}
            onChange={(event) => setKbQuery(event.target.value)}
          />
          <select
            aria-label="知识库范围"
            value={kbScope}
            onChange={(event) => setKbScope(event.target.value)}
          >
            <option value="all">全部范围</option>
            <option value="company">公司库</option>
            <option value="project">项目库</option>
            <option value="personal">个人库</option>
          </select>
          <select
            aria-label="知识库状态"
            value={kbStatus}
            onChange={(event) => setKbStatus(event.target.value)}
          >
            <option value="all">全部状态</option>
            <option value="init_failed">未初始化</option>
            <option value="migrating">迁移中</option>
            <option value="exception">异常</option>
          </select>
        </div>
        <div className="mf-kb-drawer-list">
          {filteredKbs.length === 0 ? (
            <div className="mf-empty-state">
              <strong>没有匹配的知识库</strong>
              <span>调整搜索或筛选条件后重试。</span>
            </div>
          ) : (
            filteredKbs.map((config) => (
              <article className="mf-kb-drawer-row" key={config.mapping_id}>
                <div>
                  <strong>{config.kb_name}</strong>
                  <span>
                    {config.project_name ??
                      config.owner_name ??
                      scopeLabel[config.scope] ??
                      config.scope}
                  </span>
                </div>
                <div className="mf-kb-row-facts">
                  <span>{scopeLabel[config.scope] ?? config.scope}</span>
                  <StatusBadge
                    tone={
                      config.mapping_status === "init_failed"
                        ? "danger"
                        : config.mapping_status === "migrating"
                          ? "info"
                          : "success"
                    }
                    label={mappingStatusLabel[config.mapping_status] ?? config.mapping_status}
                  />
                  <span>嵌入：{slotName(config.embedding)}</span>
                </div>
                <div className="mf-kb-row-actions">
                  {canEdit && (
                    <button className="btn-small" onClick={() => openKbConfig(config)}>
                      配置
                    </button>
                  )}
                  {config.migration && (
                    <button className="btn-small" onClick={() => showMigrationResult(config)}>
                      查看迁移结果
                    </button>
                  )}
                </div>
                {config.config_error && (
                  <p className="mf-safe-error">初始化未完成，请检查模型兼容性后重试。</p>
                )}
              </article>
            ))
          )}
        </div>
      </DetailDrawer>

      <TaskModal
        open={defaultsModal === "external"}
        title="编辑默认用途"
        description="内容生成与默认项目问答使用同一条 KAP 直连连接。"
        onClose={() => !busy && setDefaultsModal(null)}
        busy={busy}
        footer={
          <>
            <button
              className="btn-small-primary"
              onClick={() => void saveExternalDefault()}
              disabled={busy}
            >
              保存默认用途
            </button>
            <button className="btn-small" onClick={() => setDefaultsModal(null)} disabled={busy}>
              取消
            </button>
          </>
        }
      >
        <label className="ws-form-field">
          <span className="ws-form-label">默认外部 LLM</span>
          <select
            value={externalDefaultRef}
            onChange={(event) => setExternalDefaultRef(event.target.value)}
          >
            <option value="">请选择已启用连接</option>
            {externalConnections
              .filter((item) => item.enabled)
              .map((item) => (
                <option key={item.model_ref} value={item.model_ref}>
                  {item.display_name} · {item.provider ?? "自定义"}
                </option>
              ))}
          </select>
        </label>
      </TaskModal>

      <TaskModal
        open={defaultsModal === "foundation"}
        title="编辑默认底座"
        description="只影响新建知识库；已有知识库继续使用各自绑定。"
        onClose={() => !busy && setDefaultsModal(null)}
        busy={busy}
        size="large"
        footer={
          <>
            <button
              className="btn-small-primary"
              onClick={() => void saveFoundationDefaults()}
              disabled={busy}
            >
              保存默认底座
            </button>
            <button className="btn-small" onClick={() => setDefaultsModal(null)} disabled={busy}>
              取消
            </button>
          </>
        }
      >
        <div className="ws-form-grid mf-modal-model-grid">
          <ModelSelect
            label="默认嵌入模型"
            value={foundationDraft.embedding}
            type="embedding"
            models={models}
            onChange={(embedding) => setFoundationDraft({ ...foundationDraft, embedding })}
          />
          <ModelSelect
            label="底座兼容 LLM"
            value={foundationDraft.chat}
            type="chat"
            models={models}
            onChange={(chat) => setFoundationDraft({ ...foundationDraft, chat })}
          />
          <ModelSelect
            label="默认重排模型"
            value={foundationDraft.rerank}
            type="rerank"
            models={models}
            optional
            onChange={(rerank) => setFoundationDraft({ ...foundationDraft, rerank })}
          />
          <ModelSelect
            label="默认多模态模型"
            value={foundationDraft.multimodal}
            type="vllm"
            models={models}
            optional
            onChange={(multimodal) => setFoundationDraft({ ...foundationDraft, multimodal })}
          />
        </div>
      </TaskModal>

      <TaskModal
        open={selectedKb !== null}
        title={selectedKb ? `配置“${selectedKb.kb_name}”` : "配置知识库"}
        description="选择此知识库使用的底座模型。嵌入模型变更后需通过迁移完成重新向量化。"
        onClose={() => !busy && setSelectedKb(null)}
        busy={busy}
        size="large"
        footer={
          <>
            <button
              className="btn-small-primary"
              onClick={() => void saveKbConfig()}
              disabled={busy}
            >
              保存知识库配置
            </button>
            {selectedKb && canEdit && (
              <button
                className="btn-small"
                onClick={() => openMigration(selectedKb)}
                disabled={busy}
              >
                迁移到新嵌入模型
              </button>
            )}
            <button
              className="btn-small"
              onClick={() => {
                setSelectedKb(null);
                setDrawer("knowledge");
              }}
              disabled={busy}
            >
              取消
            </button>
          </>
        }
      >
        <div className="ws-form-grid mf-modal-model-grid">
          <ModelSelect
            label="底座兼容"
            value={kbDraft.chat}
            type="chat"
            models={models}
            onChange={(chat) => setKbDraft({ ...kbDraft, chat })}
          />
          <ModelSelect
            label="嵌入"
            value={kbDraft.embedding}
            type="embedding"
            models={models}
            onChange={(embedding) => setKbDraft({ ...kbDraft, embedding })}
          />
          <ModelSelect
            label="重排"
            value={kbDraft.rerank}
            type="rerank"
            models={models}
            optional
            onChange={(rerank) => setKbDraft({ ...kbDraft, rerank })}
          />
          <ModelSelect
            label="多模态"
            value={kbDraft.multimodal}
            type="vllm"
            models={models}
            optional
            onChange={(multimodal) => setKbDraft({ ...kbDraft, multimodal })}
          />
        </div>
      </TaskModal>

      {migrationKb && (
        <KbMigrateDialog
          cfg={migrationKb}
          models={models}
          defaultEmbeddingRef={defaults.embedding?.model_ref ?? ""}
          open
          onClose={() => {
            setMigrationKb(null);
            setDrawer("knowledge");
          }}
          onMigrated={async (message) => {
            setNote(message);
            await load();
            setDrawer("knowledge");
          }}
        />
      )}

      <DetailDrawer
        open={drawer === "migration" && displayedMigrationResult !== null}
        title={
          displayedMigrationResult ? `迁移结果 · ${displayedMigrationResult.kb_name}` : "迁移结果"
        }
        description="任务已受理不等于迁移完成；旧库只会在最终核验通过后删除。"
        onClose={() => {
          setDrawer("knowledge");
          setMigrationResult(null);
        }}
      >
        {displayedMigrationResult?.migration ? (
          <OperationStatusCard
            status={operationStatusFromJob(displayedMigrationResult.migration.job_status)}
            title={
              displayedMigrationResult.migration.job_status === "completed"
                ? "迁移已完成"
                : displayedMigrationResult.migration.job_status === "failed"
                  ? "迁移未完成"
                  : "迁移核验状态"
            }
            description={
              ["queued", "running"].includes(displayedMigrationResult.migration.job_status)
                ? "请求已提交，系统仍在处理文档。"
                : undefined
            }
            counts={[
              { label: "总数", value: displayedMigrationResult.migration.total_count },
              {
                label: "直接完成",
                value: displayedMigrationResult.migration.completed_count,
                tone: "success",
              },
              {
                label: "重复已核验",
                value: displayedMigrationResult.migration.verified_duplicate_count,
                tone: "success",
              },
              {
                label: "重复待核验",
                value: displayedMigrationResult.migration.duplicate_pending_count,
                tone: "warning",
              },
              { label: "处理中", value: displayedMigrationResult.migration.processing_count },
              {
                label: "失败",
                value: displayedMigrationResult.migration.failed_count,
                tone: "danger",
              },
            ]}
            nextStep={
              displayedMigrationResult.migration.failed_count > 0
                ? "检查模型状态后返回知识库列表重试失败项。"
                : displayedMigrationResult.migration.pending_count > 0
                  ? "等待处理完成后返回列表再次核验。"
                  : "最终核验已完成。"
            }
          />
        ) : (
          <div className="mf-empty-state">暂无迁移记录。</div>
        )}
      </DetailDrawer>
    </ProductPage>
  );
}

function ModelSelect({
  label,
  value,
  type,
  models,
  onChange,
  optional = false,
}: {
  label: string;
  value: string;
  type: string;
  models: ModelDTO[];
  onChange: (value: string) => void;
  optional?: boolean;
}) {
  return (
    <label className="ws-form-field">
      <span className="ws-form-label">{label}</span>
      <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">{optional ? "暂不设置" : "请选择模型"}</option>
        {models
          .filter((model) => model.type === type && model.enabled)
          .map((model) => (
            <option key={model.model_ref} value={model.model_ref}>
              {model.name}
            </option>
          ))}
      </select>
    </label>
  );
}
