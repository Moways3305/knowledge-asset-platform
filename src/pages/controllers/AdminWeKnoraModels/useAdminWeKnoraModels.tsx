import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchWeknoraDefaultModels,
  fetchWeknoraKbConfigs,
  fetchWeknoraModels,
  updateWeknoraDefaultModels,
  updateWeknoraKbInit,
} from "../../../api/admin";
import { ApiError } from "../../../api/http";
import {
  fetchModelConnections,
  fetchModelUsageAssignments,
  updateModelUsageAssignments,
} from "../../../api/modelConnections";
import { useAuth } from "../../../auth/AuthContext";
import type { ModelConnectionDTO } from "../../../types/modelConnections";
import type { KbConfigDTO, ModelDTO, WeknoraDefaultModelsDTO } from "../../../types/weknoraAdmin";
import { DrawerKind, emptyDefaults, kbUpdateErrorMessage } from "./model";

export function useAdminWeKnoraModels() {
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
  const [pollError, setPollError] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<DrawerKind>(isGlobalOperator ? "external" : "knowledge");
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

  const loadVersion = useRef(0);
  const load = useCallback(async () => {
    const version = ++loadVersion.current;
    setLoading(true);
    setPollError(false);
    setError(null);
    setNotConfigured(false);
    setForbidden(false);
    try {
      const [availableModels, configs, modelDefaults] = await Promise.all([
        fetchWeknoraModels(),
        fetchWeknoraKbConfigs(),
        isGlobalOperator ? fetchWeknoraDefaultModels() : Promise.resolve(emptyDefaults),
      ]);
      if (version !== loadVersion.current) return;
      setModels(availableModels);
      setKbConfigs(configs);
      setDefaults(modelDefaults);
      if (isGlobalOperator) {
        const [connections, assignments] = await Promise.all([
          fetchModelConnections(),
          fetchModelUsageAssignments(),
        ]);
        if (version !== loadVersion.current) return;
        setExternalConnections(connections.items);
        setExternalDefaultRef(assignments.external_llm_default?.model_ref ?? "");
      }
    } catch (caught) {
      if (version !== loadVersion.current) return;
      if (caught instanceof ApiError && caught.status === 503) setNotConfigured(true);
      else if (caught instanceof ApiError && caught.status === 403) {
        setForbidden(true);
        setError("当前身份仅可查看允许的配置摘要。");
      } else setError("模型与知识库配置暂时无法加载，请刷新后重试。");
    } finally {
      if (version === loadVersion.current) setLoading(false);
    }
  }, [isGlobalOperator]);

  useEffect(() => {
    void load();
    return () => {
      loadVersion.current += 1;
    };
  }, [load]);

  const migrationActive = kbConfigs.some((config) =>
    ["queued", "running"].includes(config.migration?.job_status ?? ""),
  );
  useEffect(() => {
    if (!migrationActive || loading) return;
    let active = true;
    let pending = false;
    const version = loadVersion.current;
    const timer = window.setInterval(() => {
      if (pending) return;
      pending = true;
      void fetchWeknoraKbConfigs()
        .then((configs) => {
          if (active && version === loadVersion.current) {
            setKbConfigs(configs);
            setPollError(false);
          }
        })
        .catch(() => {
          if (active && version === loadVersion.current) setPollError(true);
        })
        .finally(() => {
          pending = false;
        });
    }, 5_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [migrationActive, loading]);

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
    setDrawer("knowledge");
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
    setDrawer("knowledge");
    setMigrationKb(config);
  };

  const showMigrationResult = (config: KbConfigDTO) => {
    setDrawer("knowledge");
    setMigrationResult(config);
    setDrawer("migration");
  };
  return {
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
    externalIssues,
    modelIssues,
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
  };
}
export type AdminWeKnoraModelsController = ReturnType<typeof useAdminWeKnoraModels>;
