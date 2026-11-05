import ModelOnboarding, { type ModelOnboardingHandle } from "../components/ModelOnboarding";
import type { RegistryInventory } from "../types/modelRegistry";
import { useRef, useState } from "react";
import { Plus, Settings2, RefreshCw } from "lucide-react";
import ModelRegistryTable from "../components/ModelRegistryTable";
import { emptyManagementState, type ModelManagementHandle } from "../components/modelManagement";
import type { ModelConnectionDTO } from "../types/modelConnections";
import type { ModelDTO } from "../types/weknoraAdmin";
import { Link } from "react-router-dom";
import { ActionGroup, ActionMenu, FormActions } from "../components/ActionLayout";
import DetailDrawer from "../components/DetailDrawer";
import KbMigrateDialog from "../components/KbMigrateDialog";
import { operationStatusFromJob } from "../components/operationStatus";
import OperationStatusCard from "../components/OperationStatusCard";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import TaskModal from "../components/TaskModal";
import UnifiedModelConnectionsSection from "../components/UnifiedModelConnectionsSection";
import WeknoraModelsSection from "../components/WeknoraModelsSection";
import "./AdminWeKnoraModelsPage.css";
import {
  mappingStatusLabel,
  ModelSelect,
  scopeLabel,
  slotName,
} from "./controllers/AdminWeKnoraModels/model";
import { useAdminWeKnoraModels } from "./controllers/AdminWeKnoraModels/useAdminWeKnoraModels";

export default function AdminWeKnoraModelsPage() {
  const {
    error,
    connectionIssues,
    notConfigured,
    loading,
    migrationActive,
    refreshAll,
    busy,
    pollError,
    note,
    canEdit,
    drawer,
    setDrawer,
    counts,
    isGlobalOperator,
    setDefaultsModal,
    refreshSignal,
    load,
    openFoundationDefaults,
    kbQuery,
    setKbQuery,
    kbScope,
    setKbScope,
    kbStatus,
    setKbStatus,
    filteredKbs,
    kbConfigs,
    openKbConfig,
    openMigration,
    showMigrationResult,
    defaultsModal,
    saveExternalDefault,
    externalDefaultRef,
    setExternalDefaultRef,
    externalConnections,
    saveFoundationDefaults,
    foundationDraft,
    models,
    setFoundationDraft,
    selectedKb,
    setSelectedKb,
    saveKbConfig,
    kbDraft,
    setKbDraft,
    migrationKb,
    defaults,
    setMigrationKb,
    setNote,
    displayedMigrationResult,
    setMigrationResult,
  } = useAdminWeKnoraModels();

  const onboarding = useRef<ModelOnboardingHandle>(null);
  const [registryInventory, setRegistryInventory] = useState<RegistryInventory>({
    connections: [],
    models: [],
  });
  const externalManager = useRef<ModelManagementHandle<ModelConnectionDTO>>(null);
  const knowledgeManager = useRef<ModelManagementHandle<ModelDTO>>(null);
  const [externalState, setExternalState] = useState(emptyManagementState);
  const [knowledgeState, setKnowledgeState] = useState(emptyManagementState);
  const [entry, setEntry] = useState<"settings" | null>(null);
  const editable = canEdit && isGlobalOperator;

  return (
    <ProductPage className="ws-page mf-page mf-overview-page admin-control-page model-registry-page">
      <PageHeader
        title="模型管理"
        description="管理可用模型，为内容生成、项目问答和知识检索选择合适的模型。"
        status={
          <StatusBadge
            tone={error || connectionIssues ? "danger" : notConfigured ? "neutral" : "info"}
            label={
              loading
                ? "正在同步"
                : error
                  ? "配置读取失败"
                  : notConfigured
                    ? "底座尚未配置"
                    : connectionIssues
                      ? `${connectionIssues} 项配置需要处理`
                      : migrationActive
                        ? "迁移处理中"
                        : "配置已同步"
            }
          />
        }
        actions={
          <div className="mf-page-actions">
            <button
              className="btn-small mf-refresh"
              onClick={refreshAll}
              disabled={loading || busy}
              aria-label="刷新连接状态"
            >
              <RefreshCw size={14} aria-hidden="true" />
            </button>
            {editable && (
              <>
                <button
                  className="btn-small"
                  disabled={loading || busy}
                  onClick={() => setEntry("settings")}
                >
                  <Settings2 size={16} aria-hidden="true" />
                  模型设置
                </button>
                <button className="btn-small" onClick={() => onboarding.current?.connections()}>
                  供应商连接
                </button>
                <button
                  className="btn-small-primary"
                  disabled={loading || busy}
                  onClick={() => onboarding.current?.create()}
                >
                  <Plus size={16} aria-hidden="true" />
                  接入模型
                </button>
              </>
            )}
          </div>
        }
      />

      {error && (
        <div className="mf-inline-message is-danger" role="alert">
          {error}
        </div>
      )}
      {pollError && (
        <div className="mf-inline-message is-danger" role="alert">
          迁移状态刷新失败，当前显示上次结果；请刷新后核对，不要重复提交迁移。
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

      <div className="model-registry-layout">
        <section className="model-registry-navigation" aria-label="模型管理导航">
          <div className="model-registry-tabs" role="group" aria-label="模型管理导航">
            {isGlobalOperator && (
              <button
                type="button"
                aria-pressed={drawer !== "knowledge" && drawer !== "migration"}
                onClick={() => setDrawer("external")}
              >
                模型列表
              </button>
            )}
            <button
              type="button"
              aria-pressed={drawer === "knowledge" || drawer === "migration"}
              aria-label="管理知识库配置"
              onClick={() => setDrawer("knowledge")}
            >
              知识库配置{counts.anomalies > 0 ? `（${counts.anomalies} 项异常）` : ""}
            </button>
          </div>
        </section>
        <div className="model-registry-content">
          {notConfigured && (
            <div className="mf-overview-empty">
              <strong>知识库模型服务尚未配置</strong>
              <span>内容生成与项目问答模型仍可独立管理。</span>
            </div>
          )}
          {isGlobalOperator && drawer !== "knowledge" && drawer !== "migration" && (
            <ModelRegistryTable
              registeredModels={registryInventory.models}
              onRegisteredAction={(action, model) => onboarding.current?.[action](model)}
              connections={externalConnections}
              models={models}
              externalState={externalState}
              knowledgeState={knowledgeState}
              canEdit={editable}
              loading={loading}
              onExternalAction={(action, model) => externalManager.current?.[action]?.(model)}
              onKnowledgeAction={(action, model) => knowledgeManager.current?.[action]?.(model)}
            />
          )}
          {isGlobalOperator && (
            <>
              <ModelOnboarding
                managementRef={onboarding}
                onInventory={setRegistryInventory}
                onChanged={load}
                refreshSignal={refreshSignal}
                canEdit={editable}
              />
              <UnifiedModelConnectionsSection
                managementRef={externalManager}
                onManagementState={setExternalState}
                canEdit={editable}
                refreshSignal={refreshSignal}
                onChanged={load}
                showUsageControls={false}
              />
              <WeknoraModelsSection
                managementRef={knowledgeManager}
                onManagementState={setKnowledgeState}
                canEdit={editable}
                refreshSignal={refreshSignal}
                onChanged={load}
              />
            </>
          )}
          {drawer === "knowledge" && (
            <section className="mf-inline-workspace" aria-label="管理知识库配置" role="region">
              <p className="mf-kb-footnote">
                这里管理各知识库的模型绑定。索引失败请前往 <Link to="/admin/ingest">入库管理</Link>{" "}
                处理。
              </p>
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
                    <strong>
                      {loading
                        ? "正在读取知识库…"
                        : error
                          ? "知识库配置读取失败"
                          : notConfigured
                            ? "底座尚未配置"
                            : !kbConfigs.length
                              ? "暂无可管理的知识库"
                              : "没有匹配的知识库"}
                    </strong>
                    <span>
                      {error
                        ? "请使用页首刷新重试。"
                        : notConfigured
                          ? "完成底座配置后刷新。"
                          : kbConfigs.length
                            ? "调整搜索或筛选条件后重试。"
                            : "知识库创建后，可在这里管理模型绑定。"}
                    </span>
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
                          <ActionGroup label={`${config.kb_name}操作`}>
                            <button className="btn-small" onClick={() => openKbConfig(config)}>
                              配置
                            </button>
                            <ActionMenu label="更多知识库操作">
                              <button className="btn-small" onClick={() => openMigration(config)}>
                                迁移到新嵌入模型
                              </button>
                            </ActionMenu>
                          </ActionGroup>
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
            </section>
          )}
        </div>
      </div>
      <TaskModal
        open={entry !== null && editable}
        title="模型设置"
        onClose={() => setEntry(null)}
        description="按用途设置默认模型；已有知识库保留各自的模型绑定。"
      >
        <div className="model-entry-options">
          <button
            onClick={() => {
              setEntry(null);
              setDefaultsModal("external");
            }}
          >
            <strong>内容生成与项目问答</strong>
            <span>设置内容生成和默认项目问答共同使用的对话模型。</span>
          </button>
          <button
            onClick={() => {
              setEntry(null);
              openFoundationDefaults();
            }}
          >
            <strong>新建知识库的默认模型</strong>
            <span>设置嵌入、重排、对话和多模态模型，不更改已有知识库。</span>
          </button>
        </div>
      </TaskModal>
      <TaskModal
        open={defaultsModal === "external"}
        title="默认对话模型"
        description="内容生成与默认项目问答使用同一个对话模型。"
        onClose={() => !busy && setDefaultsModal(null)}
        busy={busy}
        footer={
          <FormActions>
            <button className="btn-small" onClick={() => setDefaultsModal(null)} disabled={busy}>
              取消
            </button>
            <button
              className="btn-small-primary"
              onClick={() => void saveExternalDefault()}
              disabled={busy}
            >
              保存默认用途
            </button>
          </FormActions>
        }
      >
        <label className="ws-form-field">
          <span className="ws-form-label">默认对话模型</span>
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
        title="知识库默认模型"
        description="只影响新建知识库；已有知识库继续使用各自绑定。"
        onClose={() => !busy && setDefaultsModal(null)}
        busy={busy}
        size="large"
        footer={
          <FormActions>
            <button className="btn-small" onClick={() => setDefaultsModal(null)} disabled={busy}>
              取消
            </button>
            <button
              className="btn-small-primary"
              onClick={() => void saveFoundationDefaults()}
              disabled={busy}
            >
              保存默认底座
            </button>
          </FormActions>
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
          <FormActions>
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
            <button
              className="btn-small-primary"
              onClick={() => void saveKbConfig()}
              disabled={busy}
            >
              保存知识库配置
            </button>
          </FormActions>
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
