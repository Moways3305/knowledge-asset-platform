import { useState, useRef, useCallback, useEffect } from "react";
import { ApiError } from "../../api/http";
import { fetchAuthMe } from "../../api/auth";
import {
  confirmIngest,
  createIngestUpload,
  fetchIngestAiResult,
  fetchPendingIngestTasks,
} from "../../api/ingest";
import type { IngestAiResultDTO, NamingFields, PendingIngestItemDTO } from "../../types/ingest";
import {
  POLL_INTERVAL_MS,
  POLL_MAX_ATTEMPTS,
  sleep,
  visibilityToKey,
  type FlowState,
  type PathBranch,
  type TargetLibrary,
} from "./uploadConstants";

// 资产化确认工作台的容器 Hook：收拢两条路径（A 企微微盘待确认 / B 本地上传）共享的
// 全部状态、AI 结果轮询、人工校正字段、确认入库与重置逻辑。页面本体只消费此 hook、
// 做步骤路由与顶层 state 传递；展示拆到 UploadStepA / UploadStepB / UploadConfirmPanel。
export function useUploadFlow() {
  const [activePath, setActivePath] = useState<PathBranch>("b");

  // Path B local upload state
  const [flowState, setFlowState] = useState<FlowState>("idle");
  const [fileName, setFileName] = useState("");
  const [fileSize, setFileSize] = useState(0);
  const [fileType, setFileType] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [extraction, setExtraction] = useState<{
    status: string | null;
    preview: string | null;
    charCount: number | null;
    errorMessage: string | null;
    isDuplicate: boolean;
    duplicateTaskId: string | null;
  } | null>(null);
  const [naming, setNaming] = useState<NamingFields | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Path A：企微微盘待确认任务。
  const [pendingTasks, setPendingTasks] = useState<PendingIngestItemDTO[]>([]);
  const [pendingLoading, setPendingLoading] = useState(false);
  const [pendingError, setPendingError] = useState<string | null>(null);
  const [selectedTaskName, setSelectedTaskName] = useState("");

  // Shared confirmation fields
  const [editTitle, setEditTitle] = useState("");
  const [editOneLiner, setEditOneLiner] = useState("");
  const [editSummary, setEditSummary] = useState("");
  const [editKeyPoints, setEditKeyPoints] = useState("");
  const [llmStatus, setLlmStatus] = useState<{ status: string | null; provider: string | null } | null>(null);
  const [desensitization, setDesensitization] = useState<{
    status: string | null;
    counts: Record<string, number> | null;
    message: string | null;
  } | null>(null);
  const [editTags, setEditTags] = useState("");
  const [editVisibility, setEditVisibility] = useState("项目内");
  const [editBizStage, setEditBizStage] = useState("行动辅导");
  const [targetLibrary, setTargetLibrary] = useState<TargetLibrary>("personal");
  const [confirmConfidence, setConfirmConfidence] = useState("—");

  // 真实入库任务状态
  const [taskId, setTaskId] = useState<string | null>(null);
  const [resultAssetId, setResultAssetId] = useState<string | null>(null);
  const [submitIndexStatus, setSubmitIndexStatus] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [processingNote, setProcessingNote] = useState<string | null>(null);
  const [editAssetType, setEditAssetType] = useState("methodology");
  const [editConfidentiality, setEditConfidentiality] = useState("L2");
  const [editAiAccess, setEditAiAccess] = useState("A2");
  const [projects, setProjects] = useState<{ projectId: string; projectName: string }[]>([]);
  const [targetProjectId, setTargetProjectId] = useState("");

  useEffect(() => {
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, []);

  useEffect(() => {
    fetchAuthMe()
      .then((me) => {
        setProjects(me.projects.map((p) => ({ projectId: p.projectId, projectName: p.projectName })));
        if (me.projects.length > 0) setTargetProjectId(me.projects[0].projectId);
      })
      .catch(() => setProjects([]));
  }, []);

  // Path A：拉取企微微盘扫描创建的真实待确认任务。后端按权限只返回调用人可确认的任务。
  const loadPending = useCallback(async () => {
    setPendingLoading(true);
    setPendingError(null);
    try {
      setPendingTasks(await fetchPendingIngestTasks("path_a_wecom"));
    } catch (e) {
      setPendingError(
        e instanceof ApiError ? e.message : "加载企微微盘待确认任务失败（请确认后端已启动）"
      );
    } finally {
      setPendingLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activePath === "a") void loadPending();
  }, [activePath, loadPending]);

  // 把一次 ai-result 的建议填入人工校正区（Path A / Path B 共用）。
  const applyAiResult = useCallback((ai: IngestAiResultDTO, fallbackTitle: string) => {
    setLlmStatus({ status: ai.content_processing_status, provider: ai.llm_provider });
    setDesensitization({
      status: ai.desensitization_status,
      counts: ai.desensitization_counts,
      message: ai.desensitization_message,
    });
    setEditTitle(ai.suggested_title ?? fallbackTitle);
    setEditOneLiner(ai.suggested_one_liner ?? "");
    setEditSummary(ai.suggested_summary ?? "");
    setEditKeyPoints((ai.suggested_key_points ?? []).join("\n"));
    setEditTags((ai.suggested_tags ?? []).join(" · "));
    setEditAssetType(ai.suggested_asset_type ?? "methodology");
    setEditConfidentiality(ai.suggested_confidentiality_level ?? "L2");
    setEditAiAccess(ai.suggested_ai_access_level ?? "A2");
    setConfirmConfidence(ai.confidence != null ? `${Math.round(ai.confidence * 100)}%` : "—");
    setNaming(ai.naming_parsed_fields ?? null);
    setExtraction({
      status: ai.extraction_status,
      preview: ai.extracted_text_preview,
      charCount: ai.extracted_char_count,
      errorMessage: ai.error_message,
      isDuplicate: ai.is_possible_duplicate,
      duplicateTaskId: ai.duplicate_of_task_id,
    });
  }, []);

  // 轮询 ai-result 至非 processing 或超时。
  const pollAiResult = useCallback(async (id: string) => {
    let ai = await fetchIngestAiResult(id);
    let attempts = 0;
    while (ai.status === "processing" && attempts < POLL_MAX_ATTEMPTS) {
      await sleep(POLL_INTERVAL_MS);
      ai = await fetchIngestAiResult(id);
      attempts += 1;
    }
    return ai;
  }, []);

  // Path A：点击真实待确认任务 → 拉取 AI 建议（与 Path B 同一 ai-result 接口）→ 填入
  // 人工校正区。处理中则轮询；失败/超时给安全提示且不可确认。
  const handleSelectPendingTask = useCallback(async (t: PendingIngestItemDTO) => {
    setSelectedTaskName(t.source_file_name);
    setTaskId(t.id);
    setApiError(null);
    setProcessingNote(null);
    setResultAssetId(null);
    if (t.target_scope === "personal" || t.target_scope === "project" || t.target_scope === "company") {
      setTargetLibrary(t.target_scope);
    }
    if (t.target_project_id) setTargetProjectId(t.target_project_id);
    setFlowState("processing");
    try {
      const ai = await pollAiResult(t.id);
      applyAiResult(ai, t.source_file_name);
      if (ai.status === "processing") {
        setProcessingNote("后台仍在处理该企微微盘文件（抽取 / LLM 内容处理），请稍后刷新重试，暂不可确认。");
        setFlowState("processing");
        return;
      }
      if (ai.status === "failed") {
        setProcessingNote(`文件处理失败：${ai.error_message ?? "无法从该文件抽取内容"}。请检查文件后重试，当前不可确认入库。`);
        setFlowState("failed");
        return;
      }
      setFlowState("ready");
    } catch (e) {
      setApiError(e instanceof ApiError ? e.message : "加载该任务的 AI 建议失败");
      setFlowState("idle");
    }
  }, [applyAiResult, pollAiResult]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setSelectedFile(file);
    setFileName(file.name);
    setFileSize(file.size);
    setFileType(file.type || file.name.split(".").pop()?.toUpperCase() || "未知");
    setFlowState("file_selected");
  }, []);

  // Path B：上传真实文件字节 + 创建入库任务 + 异步轮询 AI 建议（worker 抽取 + 外部 LLM）
  const handleStart = useCallback(async () => {
    if (!selectedFile) {
      setApiError("请先选择本地文件");
      return;
    }
    setFlowState("processing");
    setApiError(null);
    setProcessingNote(null);
    try {
      const up = await createIngestUpload({ file: selectedFile });
      setTaskId(up.ingest_task_id);
      const ai = await pollAiResult(up.ingest_task_id);
      if (ai.status === "processing") {
        setProcessingNote("后台仍在处理该上传（抽取 / LLM 内容处理），请稍后刷新重试，暂不可提交。");
        setFlowState("processing");
        return;
      }
      applyAiResult(ai, fileName);
      if (ai.status === "failed") {
        setProcessingNote(`文件处理失败：${ai.error_message ?? "无法从该文件抽取内容"}。请检查文件后重新上传，当前不可提交入库。`);
        setFlowState("failed");
        return;
      }
      setFlowState("ready");
    } catch (e) {
      setApiError(e instanceof ApiError ? e.message : "创建入库任务失败（请确认后端已启动）");
      setFlowState("file_selected");
    }
  }, [selectedFile, fileName, applyAiResult, pollAiResult]);

  // 两条路径共用同一 confirm 链路（同一后端 service）。确认成功后展示真实资产链接；
  // Path A 额外刷新待确认列表。
  const handleSubmit = useCallback(async () => {
    if (!taskId) return;
    setApiError(null);
    if (targetLibrary === "project" && !targetProjectId) {
      setApiError("请选择目标项目");
      return;
    }
    try {
      const tags = editTags.split(/[·,，、\s]+/).map((t) => t.trim()).filter(Boolean);
      const keyPoints = editKeyPoints.split("\n").map((t) => t.trim()).filter(Boolean);
      const res = await confirmIngest(taskId, {
        title: editTitle,
        one_liner: editOneLiner || undefined,
        summary: editSummary,
        key_points: keyPoints,
        tags,
        target_scope: targetLibrary,
        target_project_id: targetLibrary === "project" ? targetProjectId : undefined,
        target_zone: "material",
        asset_type: editAssetType,
        visibility: visibilityToKey[editVisibility] ?? "project_only",
        confidentiality_level: editConfidentiality,
        ai_access_level: editAiAccess,
        lifecycle_phase_key: editBizStage,
      });
      setResultAssetId(res.result_asset_id);
      setSubmitIndexStatus(res.index_status ?? null);
      setFlowState("submitted");
      if (activePath === "a") void loadPending();
    } catch (e) {
      setApiError(e instanceof ApiError ? e.message : "提交入库失败");
    }
  }, [activePath, taskId, targetLibrary, targetProjectId, editTags, editTitle, editOneLiner, editSummary, editKeyPoints, editBizStage, editAssetType, editVisibility, editConfidentiality, editAiAccess, loadPending]);

  const handleReset = useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
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
    if (fileRef.current) fileRef.current.value = "";
    setSelectedTaskName("");
    setEditTitle("");
    setEditOneLiner("");
    setEditSummary("");
    setEditKeyPoints("");
    setLlmStatus(null);
    setEditTags("");
    setEditVisibility("项目内");
    setEditBizStage("行动辅导");
    setTargetLibrary("personal");
    setConfirmConfidence("—");
    setEditAssetType("methodology");
    setEditConfidentiality("L2");
    setEditAiAccess("A2");
    setTaskId(null);
    setResultAssetId(null);
    setSubmitIndexStatus(null);
    setApiError(null);
  }, []);

  // 切换路径时清空当前流程 / 选中态，避免一条路径的校正数据残留到另一条。
  const switchPath = useCallback((p: PathBranch) => {
    if (p === activePath) return;
    handleReset();
    setActivePath(p);
  }, [activePath, handleReset]);

  const confirmReady = flowState === "ready";
  const requiredFieldsOk =
    editTitle.trim().length > 0 &&
    (editSummary.trim().length > 0 || editOneLiner.trim().length > 0) &&
    (targetLibrary !== "project" || targetProjectId.length > 0);
  const canSubmit = confirmReady && requiredFieldsOk;
  const confirmSubmitted = flowState === "submitted";
  const sourceLabel = activePath === "a" ? "企微微盘" : "本地上传";
  const sourceFile = activePath === "a"
    ? selectedTaskName
    : (fileName || "retail-channel-transformation.pptx");
  const hasFile = flowState !== "idle";

  return {
    activePath, switchPath,
    flowState, fileName, fileSize, fileType, hasFile, extraction, desensitization,
    naming, fileRef, handleFileSelect, handleStart, handleReset,
    pendingTasks, pendingLoading, pendingError, loadPending, handleSelectPendingTask, taskId,
    editTitle, setEditTitle, editOneLiner, setEditOneLiner, editSummary, setEditSummary,
    editKeyPoints, setEditKeyPoints, editTags, setEditTags, editVisibility, setEditVisibility,
    editBizStage, setEditBizStage, editAssetType, setEditAssetType,
    editConfidentiality, setEditConfidentiality, editAiAccess, setEditAiAccess,
    targetLibrary, setTargetLibrary, targetProjectId, setTargetProjectId, projects,
    confirmConfidence, llmStatus, apiError, processingNote,
    confirmReady, confirmSubmitted, canSubmit, sourceLabel, sourceFile,
    resultAssetId, submitIndexStatus, handleSubmit,
  };
}

export type UploadFlow = ReturnType<typeof useUploadFlow>;
