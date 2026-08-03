import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchAuthMe } from "../../api/auth";
import { ApiError } from "../../api/http";
import { confirmIngest, createIngestUpload, fetchIngestAiResult } from "../../api/ingest";
import { fetchNamingOptions, previewIngestNaming } from "../../api/naming";
import type { IngestAiResultDTO, NamingFields, PendingIngestItemDTO } from "../../types/ingest";
import type { NamingOptionsDTO, NamingPreviewDTO } from "../../types/naming";
import {
  POLL_INTERVAL_MS,
  POLL_MAX_ATTEMPTS,
  sleep,
  visibilityToKey,
  type FlowState,
  type PathBranch,
  type TargetLibrary,
} from "./uploadConstants";
import { suggestNamingCategory } from "./namingCategorySuggestion";

export interface ConfirmationNamingState {
  taskId: string | null;
  target: {
    library: TargetLibrary;
    projectId: string;
    locked: boolean;
  };
  fields: {
    title: string;
    oneLiner: string;
    summary: string;
    keyPoints: string;
    tags: string;
    assetType: string;
    confidentiality: string;
    aiAccess: string;
    visibility: string;
    businessStage: string;
  };
  ai: {
    naming: NamingFields | null;
    generation: {
      status: IngestAiResultDTO["suggestion_generation_status"];
      reason: string;
    } | null;
  };
}

interface ConfirmationOptions {
  activePath: PathBranch;
  embeddingModelRef: string;
  rerankModelRef: string;
  loadPending: () => Promise<void>;
  loadLocalPending: () => Promise<void>;
  removeLocalTask: (taskId: string) => void;
  beforeSingleTask: () => void;
}

export function useIngestConfirmation({
  activePath,
  embeddingModelRef,
  rerankModelRef,
  loadPending,
  loadLocalPending,
  removeLocalTask,
  beforeSingleTask,
}: ConfirmationOptions) {
  const workflowRunRef = useRef(0);
  const [flowState, setFlowState] = useState<FlowState>("idle");
  const [fileName, setFileName] = useState("");
  const [fileSize, setFileSize] = useState(0);
  const [fileType, setFileType] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedTaskName, setSelectedTaskName] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [resultAssetId, setResultAssetId] = useState<string | null>(null);
  const [submitReviewId, setSubmitReviewId] = useState<string | null>(null);
  const [submitIndexStatus, setSubmitIndexStatus] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [processingNote, setProcessingNote] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editOneLiner, setEditOneLiner] = useState("");
  const [editSummary, setEditSummary] = useState("");
  const [editKeyPoints, setEditKeyPoints] = useState("");
  const [editTags, setEditTags] = useState("");
  const [editVisibility, setEditVisibility] = useState("项目内");
  const [editBizStage, setEditBizStage] = useState("行动辅导");
  const [editAssetType, setEditAssetType] = useState("methodology");
  const [editConfidentiality, setEditConfidentiality] = useState("L2");
  const [editAiAccess, setEditAiAccess] = useState("A2");
  const [targetLibrary, setTargetLibrary] = useState<TargetLibrary>("");
  const [targetLocked, setTargetLocked] = useState(false);
  const [targetProjectId, setTargetProjectId] = useState("");
  const [canUseCompanyTarget, setCanUseCompanyTarget] = useState(false);
  const [projects, setProjects] = useState<{ projectId: string; projectName: string }[]>([]);
  const [llmStatus, setLlmStatus] = useState<{
    status: string | null;
    provider: string | null;
    summaryStatus: IngestAiResultDTO["summary_status"];
    generationModelRef: string | null;
  } | null>(null);
  const [desensitization, setDesensitization] = useState<{
    status: string | null;
    counts: Record<string, number> | null;
    message: string | null;
  } | null>(null);
  const [suggestionGeneration, setSuggestionGeneration] = useState<{
    status: IngestAiResultDTO["suggestion_generation_status"];
    reason: string;
  } | null>(null);
  const [extraction, setExtraction] = useState<{
    status: string | null;
    charCount: number | null;
    isDuplicate: boolean;
  } | null>(null);
  const [naming, setNaming] = useState<NamingFields | null>(null);
  const [namingOptions, setNamingOptions] = useState<NamingOptionsDTO | null>(null);
  const [namingPolicyResolved, setNamingPolicyResolved] = useState(false);
  const [namingCategoryId, setNamingCategoryId] = useState("");
  const [namingFormedOn, setNamingFormedOn] = useState("");
  const [namingVersion, setNamingVersion] = useState("V1");
  const [namingApplicableTo, setNamingApplicableTo] = useState("");
  const [namingPreview, setNamingPreview] = useState<NamingPreviewDTO | null>(null);
  const [namingPreviewBusy, setNamingPreviewBusy] = useState(false);
  const [namingPreviewError, setNamingPreviewError] = useState<string | null>(null);
  const namingPreviewRunRef = useRef(0);

  const beginWorkflowRun = useCallback(() => {
    workflowRunRef.current += 1;
    return workflowRunRef.current;
  }, []);
  const isCurrentWorkflowRun = useCallback((runId: number) => workflowRunRef.current === runId, []);

  useEffect(
    () => () => {
      workflowRunRef.current += 1;
    },
    [],
  );

  useEffect(() => {
    fetchAuthMe()
      .then((me) => {
        setProjects(
          me.projects.map((project) => ({
            projectId: project.projectId,
            projectName: project.projectName,
          })),
        );
        setCanUseCompanyTarget(me.canDiscoverL5);
      })
      .catch(() => {
        setProjects([]);
        setCanUseCompanyTarget(false);
      });
  }, []);

  const applyAiResult = useCallback((ai: IngestAiResultDTO) => {
    setLlmStatus({
      status: ai.content_processing_status,
      provider: ai.llm_provider,
      summaryStatus: ai.summary_status,
      generationModelRef: ai.generation_model_ref,
    });
    setDesensitization({
      status: ai.desensitization_status,
      counts: ai.desensitization_counts,
      message: ai.desensitization_message,
    });
    // The backend projection is the only trusted suggestion source. If it
    // cannot derive a safe subject, require explicit manual input.
    setEditTitle(ai.suggested_title ?? "");
    setEditOneLiner(ai.suggested_one_liner ?? "");
    setEditSummary(ai.suggested_summary ?? "");
    setEditKeyPoints((ai.suggested_key_points ?? []).join("\n"));
    setEditTags((ai.suggested_tags ?? []).join(" · "));
    setEditAssetType(ai.suggested_asset_type ?? "methodology");
    setEditConfidentiality(ai.suggested_confidentiality_level ?? "L2");
    setEditAiAccess(ai.suggested_ai_access_level ?? "A2");
    setSuggestionGeneration({
      status: ai.suggestion_generation_status,
      reason: ai.suggestion_generation_reason,
    });
    setNaming(ai.naming_parsed_fields ?? null);
    const aiDate = ai.naming_parsed_fields?.date ?? "";
    if (/^\d{8}$/.test(aiDate)) {
      setNamingFormedOn(`${aiDate.slice(0, 4)}-${aiDate.slice(4, 6)}-${aiDate.slice(6)}`);
    }
    // Version provenance is persisted and fail-closed by the backend. The
    // legacy parsed naming payload is compatibility metadata only and must
    // never override the authoritative suggestion projection.
    const projectedVersion = ai.suggested_version?.trim().toUpperCase() ?? "";
    setNamingVersion(/^V[1-9]\d*(?:\.\d+)*$/.test(projectedVersion) ? projectedVersion : "V1");
    setExtraction({
      status: ai.extraction_status,
      charCount: ai.extracted_char_count,
      isDuplicate: ai.is_possible_duplicate,
    });
  }, []);

  useEffect(() => {
    namingPreviewRunRef.current += 1;
    setNamingPreview(null);
    setNamingPreviewError(null);
    setNamingPolicyResolved(targetLibrary === "personal");
    if (!targetLibrary || (targetLibrary === "project" && !targetProjectId)) {
      setNamingOptions(null);
      setNamingCategoryId("");
      return;
    }
    let live = true;
    fetchNamingOptions(targetLibrary, targetLibrary === "project" ? targetProjectId : undefined)
      .then((value) => {
        if (!live) return;
        setNamingOptions(value);
        setNamingPolicyResolved(true);
        if (!value.required) {
          setNamingCategoryId("");
          return;
        }
        setNamingCategoryId((current) =>
          value.categories.some((item) => item.id === current)
            ? current
            : (suggestNamingCategory(naming, value.categories)?.id ?? ""),
        );
        if (value.default_confidentiality) setEditConfidentiality(value.default_confidentiality);
      })
      .catch((reason) => {
        if (!live) return;
        setNamingOptions(null);
        setNamingPolicyResolved(false);
        setNamingPreviewError(reason instanceof ApiError ? reason.message : "命名规则暂时无法加载");
      });
    return () => {
      live = false;
    };
  }, [naming, targetLibrary, targetProjectId]);

  useEffect(() => {
    const runId = ++namingPreviewRunRef.current;
    setNamingPreview(null);
    if (!namingOptions?.required || !taskId) {
      setNamingPreviewBusy(false);
      return;
    }
    if (
      !namingCategoryId ||
      !editTitle.trim() ||
      !namingFormedOn ||
      !/^V[1-9]\d*(?:\.\d+)*$/.test(namingVersion) ||
      (targetLibrary === "company" && !namingApplicableTo.trim())
    ) {
      setNamingPreviewBusy(false);
      setNamingPreviewError("请完整填写目录类别、主题、形成日期和规范版本");
      return;
    }
    setNamingPreviewBusy(true);
    setNamingPreviewError(null);
    const timer = window.setTimeout(() => {
      previewIngestNaming(taskId, {
        target_scope: targetLibrary as "project" | "company",
        target_project_id: targetLibrary === "project" ? targetProjectId : undefined,
        confidentiality_level: editConfidentiality,
        naming: {
          category_id: namingCategoryId,
          subject: editTitle,
          formed_on: namingFormedOn,
          version: namingVersion,
          applicable_to: targetLibrary === "company" ? namingApplicableTo : undefined,
        },
      })
        .then((value) => {
          if (namingPreviewRunRef.current !== runId) return;
          setNamingPreview(value);
          const renderedSubject = value.fields?.subject;
          if (typeof renderedSubject === "string" && renderedSubject !== editTitle) {
            setEditTitle(renderedSubject);
          }
        })
        .catch((reason) => {
          if (namingPreviewRunRef.current !== runId) return;
          setNamingPreviewError(reason instanceof ApiError ? reason.message : "规范名预览失败");
        })
        .finally(() => {
          if (namingPreviewRunRef.current === runId) setNamingPreviewBusy(false);
        });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [
    editConfidentiality,
    editTitle,
    namingApplicableTo,
    namingCategoryId,
    namingFormedOn,
    namingOptions?.required,
    namingVersion,
    targetLibrary,
    targetProjectId,
    taskId,
  ]);

  const pollAiResult = useCallback(async (id: string, isCurrent: () => boolean) => {
    if (!isCurrent()) return null;
    let ai = await fetchIngestAiResult(id);
    if (!isCurrent()) return null;
    let attempts = 0;
    while (ai.status === "processing" && attempts < POLL_MAX_ATTEMPTS) {
      await sleep(POLL_INTERVAL_MS);
      if (!isCurrent()) return null;
      ai = await fetchIngestAiResult(id);
      if (!isCurrent()) return null;
      attempts += 1;
    }
    return ai;
  }, []);

  const handleSelectPendingTask = useCallback(
    async (task: PendingIngestItemDTO) => {
      beforeSingleTask();
      const runId = beginWorkflowRun();
      const isCurrent = () => isCurrentWorkflowRun(runId);
      setSelectedTaskName(task.source_file_name);
      setTaskId(task.id);
      setApiError(null);
      setProcessingNote(null);
      setResultAssetId(null);
      if (
        task.target_scope === "personal" ||
        task.target_scope === "project" ||
        task.target_scope === "company"
      ) {
        setTargetLibrary(task.target_scope);
        setTargetLocked(true);
      } else {
        setTargetLibrary("");
        setTargetLocked(false);
      }
      setTargetProjectId(task.target_project_id ?? "");
      setFlowState("processing");
      try {
        const ai = await pollAiResult(task.id, isCurrent);
        if (!ai || !isCurrent()) return;
        applyAiResult(ai);
        if (ai.status === "processing") {
          setProcessingNote(
            "后台仍在处理该企微微盘文件（抽取 / LLM 内容处理），请稍后刷新重试，暂不可确认。",
          );
          setFlowState("processing");
          return;
        }
        if (ai.status === "failed") {
          setProcessingNote(
            `文件处理失败：${ai.error_message ?? "无法从该文件抽取内容"}。请检查文件后重试，当前不可确认入库。`,
          );
          setFlowState("failed");
          return;
        }
        setFlowState("ready");
      } catch (error) {
        if (!isCurrent()) return;
        setApiError(error instanceof ApiError ? error.message : "加载该任务的 AI 建议失败");
        setFlowState("idle");
      }
    },
    [applyAiResult, beforeSingleTask, beginWorkflowRun, isCurrentWorkflowRun, pollAiResult],
  );

  const handleStart = useCallback(async () => {
    beforeSingleTask();
    const runId = beginWorkflowRun();
    const isCurrent = () => isCurrentWorkflowRun(runId);
    if (!selectedFile) {
      setApiError("请先选择本地文件");
      return;
    }
    setFlowState("processing");
    setApiError(null);
    setProcessingNote(null);
    try {
      const upload = await createIngestUpload({ file: selectedFile });
      if (!isCurrent()) return;
      setTaskId(upload.ingest_task_id);
      const ai = await pollAiResult(upload.ingest_task_id, isCurrent);
      if (!ai || !isCurrent()) return;
      if (ai.status === "processing") {
        setProcessingNote(
          "后台仍在处理该上传（抽取 / LLM 内容处理），请稍后刷新重试，暂不可提交。",
        );
        setFlowState("processing");
        return;
      }
      applyAiResult(ai);
      if (ai.status === "failed") {
        setProcessingNote(
          `文件处理失败：${ai.error_message ?? "无法从该文件抽取内容"}。请检查文件后重新上传，当前不可提交入库。`,
        );
        setFlowState("failed");
        return;
      }
      setFlowState("ready");
    } catch (error) {
      if (!isCurrent()) return;
      setApiError(error instanceof ApiError ? error.message : "创建入库任务失败，请稍后重试");
      setFlowState("file_selected");
    }
  }, [
    applyAiResult,
    beforeSingleTask,
    beginWorkflowRun,
    isCurrentWorkflowRun,
    pollAiResult,
    selectedFile,
  ]);

  const handleRefreshProcessing = useCallback(async () => {
    const runId = beginWorkflowRun();
    const isCurrent = () => isCurrentWorkflowRun(runId);
    if (!taskId) return;
    setApiError(null);
    setProcessingNote(null);
    setFlowState("processing");
    try {
      const ai = await pollAiResult(taskId, isCurrent);
      if (!ai || !isCurrent()) return;
      applyAiResult(ai);
      if (ai.status === "processing") {
        setProcessingNote("后台仍在处理，请稍后重新检查，当前不可确认入库。");
        return;
      }
      if (ai.status === "failed") {
        setProcessingNote(
          `文件处理失败：${ai.error_message ?? "无法从该文件抽取内容"}。当前不可确认入库。`,
        );
        setFlowState("failed");
        return;
      }
      setFlowState("ready");
    } catch (error) {
      if (!isCurrent()) return;
      setApiError(error instanceof ApiError ? error.message : "任务状态暂时无法获取，请稍后重试");
      setFlowState(activePath === "a" ? "idle" : "file_selected");
    }
  }, [activePath, applyAiResult, beginWorkflowRun, isCurrentWorkflowRun, pollAiResult, taskId]);

  const handleSubmit = useCallback(async () => {
    const runId = beginWorkflowRun();
    const isCurrent = () => isCurrentWorkflowRun(runId);
    if (!taskId) return;
    setApiError(null);
    if (!targetLibrary) {
      setApiError("请选择目标知识库");
      return;
    }
    if (!editTitle.trim()) {
      setApiError("请填写标题或主题");
      return;
    }
    const selectedTargetLibrary: Exclude<TargetLibrary, ""> = targetLibrary;
    if (selectedTargetLibrary === "project" && !targetProjectId) {
      setApiError("请选择目标项目");
      return;
    }
    try {
      const tags = editTags
        .split(/[·,，、\s]+/)
        .map((tag) => tag.trim())
        .filter(Boolean);
      const keyPoints = editKeyPoints
        .split("\n")
        .map((point) => point.trim())
        .filter(Boolean);
      const response = await confirmIngest(taskId, {
        title: editTitle,
        one_liner: editOneLiner || undefined,
        summary: editSummary,
        key_points: keyPoints,
        tags,
        target_scope: selectedTargetLibrary,
        target_project_id: selectedTargetLibrary === "project" ? targetProjectId : undefined,
        target_zone: "material",
        asset_type: editAssetType,
        visibility: visibilityToKey[editVisibility] ?? "project_only",
        confidentiality_level: editConfidentiality,
        ai_access_level: editAiAccess,
        lifecycle_phase_key: editBizStage,
        embedding_model_ref: embeddingModelRef || undefined,
        rerank_model_ref: rerankModelRef || undefined,
        naming: namingOptions?.required
          ? {
              category_id: namingCategoryId,
              subject: editTitle,
              formed_on: namingFormedOn,
              version: namingVersion,
              applicable_to: selectedTargetLibrary === "company" ? namingApplicableTo : undefined,
            }
          : undefined,
      });
      if (!isCurrent()) return;
      setResultAssetId(response.result_asset_id);
      setSubmitReviewId(response.review_id ?? null);
      setSubmitIndexStatus(response.index_status ?? null);
      setFlowState("submitted");
      if (activePath === "a") void loadPending();
      if (activePath === "b") {
        removeLocalTask(taskId);
        void loadLocalPending();
      }
    } catch (error) {
      if (!isCurrent()) return;
      setApiError(error instanceof ApiError ? error.message : "提交入库失败");
    }
  }, [
    activePath,
    beginWorkflowRun,
    editAiAccess,
    editAssetType,
    editBizStage,
    editConfidentiality,
    editKeyPoints,
    editOneLiner,
    editSummary,
    editTags,
    editTitle,
    editVisibility,
    embeddingModelRef,
    isCurrentWorkflowRun,
    loadLocalPending,
    loadPending,
    namingApplicableTo,
    namingCategoryId,
    namingFormedOn,
    namingOptions?.required,
    namingVersion,
    removeLocalTask,
    rerankModelRef,
    targetLibrary,
    targetProjectId,
    taskId,
  ]);

  const resetConfirmation = useCallback(() => {
    beginWorkflowRun();
    setFlowState("idle");
    setApiError(null);
    setProcessingNote(null);
    setLlmStatus(null);
    setDesensitization(null);
    setSelectedFile(null);
    setExtraction(null);
    setNaming(null);
    setFileName("");
    setFileSize(0);
    setFileType("");
    setSelectedTaskName("");
    setEditTitle("");
    setEditOneLiner("");
    setEditSummary("");
    setEditKeyPoints("");
    setEditTags("");
    setEditVisibility("项目内");
    setEditBizStage("行动辅导");
    setTargetLibrary("");
    setTargetProjectId("");
    setTargetLocked(false);
    setSuggestionGeneration(null);
    setEditAssetType("methodology");
    setEditConfidentiality("L2");
    setEditAiAccess("A2");
    setTaskId(null);
    setResultAssetId(null);
    setSubmitReviewId(null);
    setSubmitIndexStatus(null);
    setNamingOptions(null);
    setNamingPolicyResolved(false);
    setNamingCategoryId("");
    setNamingFormedOn("");
    setNamingVersion("V1");
    setNamingApplicableTo("");
    setNamingPreview(null);
    setNamingPreviewBusy(false);
    setNamingPreviewError(null);
  }, [beginWorkflowRun]);

  const namingPreviewState = useMemo<ConfirmationNamingState>(
    () => ({
      taskId,
      target: {
        library: targetLibrary,
        projectId: targetProjectId,
        locked: targetLocked,
      },
      fields: {
        title: editTitle,
        oneLiner: editOneLiner,
        summary: editSummary,
        keyPoints: editKeyPoints,
        tags: editTags,
        assetType: editAssetType,
        confidentiality: editConfidentiality,
        aiAccess: editAiAccess,
        visibility: editVisibility,
        businessStage: editBizStage,
      },
      ai: {
        naming,
        generation: suggestionGeneration,
      },
    }),
    [
      editAiAccess,
      editAssetType,
      editBizStage,
      editConfidentiality,
      editKeyPoints,
      editOneLiner,
      editSummary,
      editTags,
      editTitle,
      editVisibility,
      naming,
      suggestionGeneration,
      targetLibrary,
      targetLocked,
      targetProjectId,
      taskId,
    ],
  );

  return {
    flowState,
    fileName,
    fileSize,
    fileType,
    selectedTaskName,
    taskId,
    resultAssetId,
    submitReviewId,
    submitIndexStatus,
    apiError,
    setApiError,
    processingNote,
    editTitle,
    setEditTitle,
    editOneLiner,
    setEditOneLiner,
    editSummary,
    setEditSummary,
    editKeyPoints,
    setEditKeyPoints,
    editTags,
    setEditTags,
    editVisibility,
    setEditVisibility,
    editBizStage,
    setEditBizStage,
    editAssetType,
    setEditAssetType,
    editConfidentiality,
    setEditConfidentiality,
    editAiAccess,
    setEditAiAccess,
    targetLibrary,
    setTargetLibrary,
    targetLocked,
    setTargetLocked,
    targetProjectId,
    setTargetProjectId,
    canUseCompanyTarget,
    projects,
    llmStatus,
    setLlmStatus,
    desensitization,
    setDesensitization,
    suggestionGeneration,
    setSuggestionGeneration,
    extraction,
    setExtraction,
    naming,
    setNaming,
    namingOptions,
    namingCategoryId,
    setNamingCategoryId,
    namingFormedOn,
    setNamingFormedOn,
    namingVersion,
    setNamingVersion,
    namingApplicableTo,
    setNamingApplicableTo,
    namingPreview,
    namingPreviewBusy,
    namingPreviewError,
    namingPreviewReady:
      targetLibrary === "personal" ||
      (namingPolicyResolved &&
        (!namingOptions?.required || Boolean(namingPreview?.canonical_name))),
    namingRequired: Boolean(namingOptions?.required),
    applyAiResult,
    pollAiResult,
    handleSelectPendingTask,
    handleStart,
    handleRefreshProcessing,
    handleSubmit,
    resetConfirmation,
    beginWorkflowRun,
    isCurrentWorkflowRun,
    namingPreviewState,
  };
}
