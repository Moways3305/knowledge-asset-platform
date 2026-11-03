import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError } from "../../../api/http";
import {
  deleteKnowledgeAsset,
  fetchKnowledgeDetail,
  fetchLifecycleEvents,
  fetchPreviewEntry,
  issuePreview,
  lifecycleArchiveConfirm,
  lifecycleArchiveRequest,
  requestOriginalAccess,
  retryKnowledgeIndex,
} from "../../../api/knowledge";
import type { VersionHistory } from "../../../api/knowledgeVersions";
import { useAuth } from "../../../auth/AuthContext";
import { readKnowledgeDetailSource } from "../../../routing/knowledgeDetailSource";
import type { KnowledgeDetailVM } from "../../../types/knowledge";
import type { LifecycleEventDTO } from "../../../types/lifecycle";
import type { PreviewEntryVM } from "../../../types/preview";
import { safeActionError } from "./model";

export function useKnowledgeDetail() {
  const { authMe, capabilities } = useAuth();
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const requestRef = useRef(0);
  const [detailView, setDetailView] = useState("content");
  const [metadataExpanded, setMetadataExpanded] = useState(false);
  const [asset, setAsset] = useState<KnowledgeDetailVM | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [authorizedHistory, setAuthorizedHistory] = useState<VersionHistory | null>(null);

  const [previewEntry, setPreviewEntry] = useState<PreviewEntryVM | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const [oaBusy, setOaBusy] = useState(false);
  const [oaError, setOaError] = useState<string | null>(null);
  const [oaNote, setOaNote] = useState<string | null>(null);
  const [requestOpen, setRequestOpen] = useState(false);
  const [requestReason, setRequestReason] = useState("");
  const [explainOpen, setExplainOpen] = useState(false);

  const [lcEvents, setLcEvents] = useState<LifecycleEventDTO[] | null>(null);
  const [lcLoading, setLcLoading] = useState(false);
  const [lcReason, setLcReason] = useState("");
  const [lcMsg, setLcMsg] = useState<string | null>(null);
  const [lcErr, setLcErr] = useState<string | null>(null);
  const [lcBusy, setLcBusy] = useState(false);

  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteReason, setDeleteReason] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);

  const [retryBusy, setRetryBusy] = useState(false);
  const [retryNote, setRetryNote] = useState<string | null>(null);
  const [retryErr, setRetryErr] = useState<string | null>(null);
  const [publicationOpen, setPublicationOpen] = useState(false);
  const [publicationNote, setPublicationNote] = useState<string | null>(null);
  const detailSource = readKnowledgeDetailSource(location.state);
  useEffect(() => {
    setDetailView("content");
  }, [id]);
  const backPath = detailSource.backTo;
  const backLabel = detailSource.backLabel;

  async function reloadAsset() {
    if (!id) return;
    try {
      setAsset(await fetchKnowledgeDetail(id));
    } catch {
      // Keep the confirmed detail visible if an action refresh fails.
    }
  }

  async function handlePreviewOriginal() {
    if (!id) return;
    const request = requestRef.current;
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const issued = await issuePreview(id);
      if (request !== requestRef.current) return;
      const entry = await fetchPreviewEntry(issued.preview_entry_url);
      if (request !== requestRef.current) return;
      setPreviewEntry(entry);
      setPreviewOpen(true);
    } catch (error) {
      if (request !== requestRef.current) return;
      setPreviewError(safeActionError(error, "原文预览暂时无法打开，请稍后再试。"));
      if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
        // Re-read current access instead of leaving a revoked grant marked as
        // available. The normal loader also hides stale data if refresh fails.
        setPreviewOpen(false);
        setPreviewEntry(null);
        setLoadAttempt((value) => value + 1);
      }
    } finally {
      if (request === requestRef.current) setPreviewLoading(false);
    }
  }

  async function handleRequestOriginal() {
    if (!id) return;
    setOaBusy(true);
    setOaError(null);
    setOaNote(null);
    try {
      const result = await requestOriginalAccess(id, requestReason.trim() || undefined);
      const message: Record<string, string> = {
        created: "原文访问申请已提交，待审批。",
        pending_exists: "原文访问申请正在审批中。",
        already_granted: "你已拥有该资产的原文访问权。",
      };
      setOaNote(message[result.status] ?? result.message);
      await reloadAsset();
      setRequestOpen(false);
      setRequestReason("");
    } catch (error) {
      setOaError(safeActionError(error, "申请原文访问失败，请重试。"));
    } finally {
      setOaBusy(false);
    }
  }

  async function loadLifecycleEvents() {
    if (!id) return;
    setLcLoading(true);
    setLcErr(null);
    try {
      const result = await fetchLifecycleEvents(id);
      setLcEvents(result.items);
    } catch (error) {
      setLcErr(safeActionError(error, "生命周期记录加载失败，请重试。"));
    } finally {
      setLcLoading(false);
    }
  }

  async function handleArchiveRequest() {
    if (!id) return;
    if (!lcReason.trim()) {
      setLcErr("请填写归档原因。");
      return;
    }
    setLcBusy(true);
    setLcMsg(null);
    setLcErr(null);
    try {
      await lifecycleArchiveRequest(id, {
        reason: lcReason.trim(),
        candidate_source: "manual",
      });
      setLcMsg("归档候选已提交。");
      await loadLifecycleEvents();
    } catch (error) {
      setLcErr(safeActionError(error, "发起归档失败，请重试。"));
    } finally {
      setLcBusy(false);
    }
  }

  async function handleArchiveConfirm() {
    if (!id) return;
    if (!lcReason.trim()) {
      setLcErr("请填写归档原因。");
      return;
    }
    setLcBusy(true);
    setLcMsg(null);
    setLcErr(null);
    try {
      await lifecycleArchiveConfirm(id, { reason: lcReason.trim() });
      setLcMsg("资产已归档。");
      await reloadAsset();
      await loadLifecycleEvents();
    } catch (error) {
      setLcErr(safeActionError(error, "确认归档失败，请重试。"));
    } finally {
      setLcBusy(false);
    }
  }

  async function handleRetryIndex() {
    if (!id) return;
    setRetryBusy(true);
    setRetryNote(null);
    setRetryErr(null);
    try {
      const result = await retryKnowledgeIndex(id);
      if (result.index_status === "indexed") setRetryNote("问答处理已完成。");
      else if (result.index_status === "skipped") setRetryNote("资产已保留，暂未进入问答。");
      else setRetryNote(result.index_error_message ?? "处理尚未完成，可稍后重试。");
      await reloadAsset();
    } catch (error) {
      setRetryErr(safeActionError(error, "重新处理问答失败，请重试。"));
    } finally {
      setRetryBusy(false);
    }
  }

  async function handleDelete() {
    if (!id) return;
    if (!deleteReason.trim()) {
      setDeleteErr("请填写删除原因。");
      return;
    }
    setDeleteBusy(true);
    setDeleteErr(null);
    try {
      await deleteKnowledgeAsset(id, deleteReason.trim());
      navigate(backPath);
    } catch (error) {
      setDeleteErr(safeActionError(error, "删除失败，请重试。"));
      setDeleteBusy(false);
    }
  }

  useEffect(() => {
    setPreviewError(null);
  }, [id]);

  useEffect(() => {
    if (!id) return;
    const request = ++requestRef.current;
    setPreviewOpen(false);
    setPreviewEntry(null);
    setPreviewLoading(false);
    setLoading(true);
    setNotFound(false);
    setLoadError(false);
    setAsset(null);
    setAuthorizedHistory(null);
    setLcEvents(null);
    fetchKnowledgeDetail(id)
      .then((detail) => {
        if (request !== requestRef.current) return;
        setAsset(detail);
        setLoading(false);
      })
      .catch((error) => {
        if (request !== requestRef.current) return;
        if (error instanceof ApiError && (error.status === 403 || error.status === 404)) {
          setNotFound(true);
        } else {
          setLoadError(true);
        }
        setLoading(false);
      });
    return () => {
      requestRef.current += 1;
    };
  }, [id, loadAttempt]);
  return {
    loading,
    backPath,
    backLabel,
    notFound,
    asset,
    loadError,
    authorizedHistory,
    id,
    setAuthorizedHistory,
    setLoadAttempt,
    authMe,
    handlePreviewOriginal,
    previewLoading,
    setRequestOpen,
    oaBusy,
    setPreviewOpen,
    setPreviewEntry,
    previewError,
    oaError,
    oaNote,
    publicationNote,
    detailView,
    setDetailView,
    setNotFound,
    reloadAsset,
    setPublicationNote,
    setPublicationOpen,
    lcEvents,
    lcLoading,
    loadLifecycleEvents,
    lcErr,
    lcReason,
    setLcReason,
    handleArchiveRequest,
    lcBusy,
    handleArchiveConfirm,
    handleRetryIndex,
    retryBusy,
    confirmDelete,
    setConfirmDelete,
    deleteReason,
    setDeleteReason,
    handleDelete,
    deleteBusy,
    lcMsg,
    retryNote,
    retryErr,
    deleteErr,
    metadataExpanded,
    setMetadataExpanded,
    setExplainOpen,
    publicationOpen,
    previewOpen,
    previewEntry,
    explainOpen,
    capabilities,
    requestOpen,
    setRequestReason,
    handleRequestOriginal,
    requestReason,
  };
}
export type KnowledgeDetailController = ReturnType<typeof useKnowledgeDetail>;
