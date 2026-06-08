import { useState, useRef, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  confirmIngest,
  createIngestUpload,
  fetchAuthMe,
  fetchIngestAiResult,
  fetchPendingIngestTasks,
} from "../api/client";
import type { NamingFields, PendingIngestItemDTO } from "../types/ingest";
import { formatBeijingTime } from "../utils/time";

type PathBranch = "a" | "b";
type FlowState = "idle" | "file_selected" | "processing" | "ready" | "failed" | "submitted";

// R8_FIX：异步 worker 处理时，上传后轮询 ai-result 直至处理完成/失败/超时。
const POLL_INTERVAL_MS = 2000;
const POLL_MAX_ATTEMPTS = 30; // 约 60s 上限
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
type TargetLibrary = "personal" | "project" | "company";

const targetLibraryOptions: { value: TargetLibrary; label: string }[] = [
  { value: "personal", label: "个人知识库" },
  { value: "project", label: "项目知识库" },
  { value: "company", label: "公司知识库" },
];

// Path A 待确认任务状态中文标签（来自后端 IngestStatus）。
const pendingStatusLabel: Record<string, string> = {
  processing: "处理中",
  pending_confirmation: "待确认",
  pending: "待处理",
  waiting_review: "待审核",
  failed: "处理失败",
};

const extractionLabel: Record<string, string> = {
  extracted: "抽取成功",
  unsupported: "暂不支持该格式（已落盘，请人工补全）",
  empty: "未抽取到文本（可能为扫描件/纯图片）",
  failed: "抽取失败（文件可能损坏）",
};

// 入库前置脱敏类别 → 中文标签（仅展示类别计数，不含原值）。
const desensCategoryLabel: Record<string, string> = {
  email: "邮箱",
  phone: "手机号",
  landline: "固话",
  id_card: "身份证号",
  bank_card: "银行卡号",
  account: "账号",
  amount: "金额",
  contact: "联系人",
  customer: "客户",
};

const visibilityOptions = ["公开", "项目内", "机密"];
// 前端中文可见性 → 后端 enum key（不要把中文发给 API）。
const visibilityToKey: Record<string, "public" | "project_only" | "confidential"> = {
  公开: "public",
  项目内: "project_only",
  机密: "confidential",
};
const assetTypeOptions: { value: string; label: string }[] = [
  { value: "methodology", label: "方法论" },
  { value: "deliverable", label: "交付物" },
  { value: "case", label: "案例" },
  { value: "template", label: "模板" },
  { value: "insight", label: "洞察" },
];
const confidentialityOptions = ["L1", "L2", "L3", "L4", "L5"];
const aiAccessOptions = ["A1", "A2", "A3", "A4"];
const bizStageOptions = ["售前", "诊断", "启动共识", "定题", "目标计划", "行动辅导", "阶段评估", "年度复盘", "专项诊断"];

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function flowLabel(state: FlowState): { text: string; cls: string } {
  switch (state) {
    case "idle": return { text: "等待选择文件", cls: "flow-idle" };
    case "file_selected": return { text: "文件已选择，待处理", cls: "flow-selected" };
    case "processing": return { text: "处理中…", cls: "flow-processing" };
    case "ready": return { text: "待人工校正", cls: "flow-ready" };
    case "failed": return { text: "处理失败", cls: "flow-failed" };
    case "submitted": return { text: "已提交", cls: "flow-submitted" };
  }
}

export default function UploadPage() {
  const [activePath, setActivePath] = useState<PathBranch>("b");

  // Path B local upload state
  const [flowState, setFlowState] = useState<FlowState>("idle");
  const [fileName, setFileName] = useState("");
  const [fileSize, setFileSize] = useState(0);
  const [fileType, setFileType] = useState("");
  // 保留选中的真实 File 对象，用于以 multipart 发送字节。
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  // 抽取结果展示（状态 / 预览 / 重复软提示 / 错误）。
  const [extraction, setExtraction] = useState<{
    status: string | null;
    preview: string | null;
    charCount: number | null;
    errorMessage: string | null;
    isDuplicate: boolean;
    duplicateTaskId: string | null;
  } | null>(null);
  // 规范命名解析结果（来自真实后端 ai-result）。
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
  // R2 三层摘要：一句话 / 详细 / 关键知识点（每行一条）。
  const [editOneLiner, setEditOneLiner] = useState("");
  const [editSummary, setEditSummary] = useState("");
  const [editKeyPoints, setEditKeyPoints] = useState("");
  const [llmStatus, setLlmStatus] = useState<{ status: string | null; provider: string | null } | null>(null);
  // 入库前置规则脱敏安全元数据（状态 + 类别计数 + 人读文案）。
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
  // confirm 返回的平台级索引状态（indexed | index_failed | skipped）。
  // index_failed = 资产已落库但底座索引失败，前端如实提示而非伪装完全成功。
  const [submitIndexStatus, setSubmitIndexStatus] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  // R8_FIX：处理中/超时/失败的安全提示（不含内部引用）。
  const [processingNote, setProcessingNote] = useState<string | null>(null);
  // 人工校正：资产类型 / 保密级别 / AI 调用级别（初值取 AI 建议，可编辑并提交）
  const [editAssetType, setEditAssetType] = useState("methodology");
  const [editConfidentiality, setEditConfidentiality] = useState("L2");
  const [editAiAccess, setEditAiAccess] = useState("A2");
  // 当前用户可选目标项目（来自 /auth/me 的 active 成员关系）
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

  // confirmReady / confirmSubmitted 现在两条路径统一由 flowState 驱动（Path A 选中真实
  // 任务并拉取到 AI 建议后置 ready；提交成功置 submitted；处理中/失败不可编辑）。
  const confirmReady = flowState === "ready";
  // R8_FIX：提交闸——仅在可编辑 + 必填字段满足时可提交（禁止空标题/空摘要/缺项目；
  // failed/processing 态 confirmReady=false 即不可提交，避免把空结果当人工确认）。
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

  // Path A：点击真实待确认任务 → 拉取 AI 建议（与 Path B 同一 ai-result 接口）→ 填入
  // 人工校正区。处理中则轮询；失败/超时给安全提示且不可确认。
  const handleSelectPendingTask = useCallback(async (t: PendingIngestItemDTO) => {
    setSelectedTaskName(t.source_file_name);
    setTaskId(t.id);
    setApiError(null);
    setProcessingNote(null);
    setResultAssetId(null);
    // 预置目标库 / 项目（来自扫描配置；用户仍可在下方修改）。
    if (t.target_scope === "personal" || t.target_scope === "project" || t.target_scope === "company") {
      setTargetLibrary(t.target_scope);
    }
    if (t.target_project_id) setTargetProjectId(t.target_project_id);
    setFlowState("processing");
    try {
      let ai = await fetchIngestAiResult(t.id);
      let attempts = 0;
      while (ai.status === "processing" && attempts < POLL_MAX_ATTEMPTS) {
        await sleep(POLL_INTERVAL_MS);
        ai = await fetchIngestAiResult(t.id);
        attempts += 1;
      }
      setLlmStatus({ status: ai.content_processing_status, provider: ai.llm_provider });
      setDesensitization({
        status: ai.desensitization_status,
        counts: ai.desensitization_counts,
        message: ai.desensitization_message,
      });
      setEditTitle(ai.suggested_title ?? t.source_file_name);
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
  }, []);

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
      // R8_FIX：异步 worker 模式下不能只拉一次——轮询直到 pending_confirmation / failed / 超时。
      let ai = await fetchIngestAiResult(up.ingest_task_id);
      let attempts = 0;
      while (ai.status === "processing" && attempts < POLL_MAX_ATTEMPTS) {
        await sleep(POLL_INTERVAL_MS);
        ai = await fetchIngestAiResult(up.ingest_task_id);
        attempts += 1;
      }
      if (ai.status === "processing") {
        // 超时仍在处理：明确提示，禁止提交空结果（可稍后刷新）。
        setProcessingNote("后台仍在处理该上传（抽取 / LLM 内容处理），请稍后刷新重试，暂不可提交。");
        setFlowState("processing");
        return;
      }
      // 填入（无论 pending_confirmation 还是 failed，都把已有建议填入，便于人工补全/判断）。
      setLlmStatus({ status: ai.content_processing_status, provider: ai.llm_provider });
      setDesensitization({
        status: ai.desensitization_status,
        counts: ai.desensitization_counts,
        message: ai.desensitization_message,
      });
      setEditTitle(ai.suggested_title ?? fileName);
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
      if (ai.status === "failed") {
        // 抽取/处理失败：展示失败原因，禁止提交入库，引导重新上传。
        setProcessingNote(`文件处理失败：${ai.error_message ?? "无法从该文件抽取内容"}。请检查文件后重新上传，当前不可提交入库。`);
        setFlowState("failed");
        return;
      }
      setFlowState("ready");
    } catch (e) {
      setApiError(e instanceof ApiError ? e.message : "创建入库任务失败（请确认后端已启动）");
      setFlowState("file_selected");
    }
  }, [selectedFile, fileName]);

  // 两条路径共用同一 confirm 链路（同一后端 service）：Path A 的 taskId 来自选中的待确认
  // 任务，Path B 来自本地上传任务。确认成功后展示真实资产链接；Path A 额外刷新待确认列表。
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
      // Path A：已确认任务的 result_asset_id 已填，会退出待确认列表，刷新以反映。
      if (activePath === "a") void loadPending();
    } catch (e) {
      setApiError(e instanceof ApiError ? e.message : "提交入库失败");
    }
  }, [activePath, taskId, targetLibrary, targetProjectId, editTags, editTitle, editOneLiner, editSummary, editKeyPoints, editBizStage, editAssetType, editVisibility, editConfidentiality, editAiAccess, loadPending]);

  const handleReset = useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    // Reset Path B
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
    // Reset Path A selection（保留已加载的待确认列表本身）
    setSelectedTaskName("");
    // Reset shared fields
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
    // Reset ingest task state
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

  const flow = flowLabel(flowState);
  const hasFile = flowState !== "idle";

  return (
    <div className="upload-page">
      {/* Unified header */}
      <div className="up-header">
        <div className="up-header-text">
          <h2>资产化确认工作台</h2>
          <p>路径 A 企微微盘待确认任务与路径 B 本地上传，在此统一进行 AI 预览、人工校正、目标库确认和提交入库</p>
        </div>
      </div>

      {/* Path branch selector */}
      <div className="up-path-branches">
        <button
          className={`up-path-card ${activePath === "a" ? "active" : ""}`}
          onClick={() => switchPath("a")}
        >
          <div className="up-path-card-title">路径A：企微微盘自动检测</div>
          <div className="up-path-card-desc">企微微盘扫描项目目录，检测新增文件并落入待确认队列，在此完成人工校正与确认入库</div>
        </button>
        <button
          className={`up-path-card ${activePath === "b" ? "active" : ""}`}
          onClick={() => switchPath("b")}
        >
          <div className="up-path-card-title">路径B：本地上传资产化</div>
          <div className="up-path-card-desc">手动选择本地文件，上传至平台受控存储后由 worker 异步抽取 + 外部 LLM 生成建议，人工校正后提交入库</div>
        </button>
      </div>
      <p className="up-path-shared-note">两条路径共享相同的 AI 提取 → 人工校正 → 入库/审核分流 模型</p>

      {/* ════════ Naming convention & confidentiality ════════ */}
      <section className="upload-section">
        <h3>命名规范与保密分级</h3>
        <p className="page-help-line">
          命名格式、保密级别（L1–L5）/ AI 调用级别（A1–A4）与命名异常处理见 <Link to="/help#ingest" className="page-help-link">使用说明 →</Link>
        </p>

        <div className="naming-parse-card">
          <div className="naming-parse-title">当前文件命名解析结果</div>
          {naming ? (
            <>
              <div className="naming-parse-row">
                <span className="naming-parse-label">规范化标题</span>
                <span className="naming-parse-value"><code>{naming.normalized_title}</code></span>
              </div>
              <div className="naming-parse-grid">
                <div className="naming-parse-row">
                  <span className="naming-parse-label">原始文件名</span>
                  <span className="naming-parse-value"><code>{naming.source_file_name}</code></span>
                </div>
                <div className="naming-parse-row">
                  <span className="naming-parse-label">命名状态</span>
                  <span className="naming-parse-value">
                    <span className={`naming-status-badge ${naming.original_naming_compliant ? "naming-status-compliant" : "naming-status-anomaly"}`}>
                      {naming.original_naming_compliant ? "原文件名合规" : "原文件名命名异常（已自动规范化）"}
                    </span>
                  </span>
                </div>
                {([
                  ["primary_category", "一级类", naming.primary_category],
                  ["secondary_category", "二级类", naming.secondary_category],
                  ["topic", "主题", naming.topic],
                  ["subject_or_client", "对象/客户", naming.subject_or_client],
                  ["date", "日期", naming.date],
                  ["version", "版本号", naming.version],
                ] as const).map(([key, label, value]) => (
                  <div className="naming-parse-row" key={key}>
                    <span className="naming-parse-label">{label}</span>
                    <span className="naming-parse-value">
                      {value}
                      {naming.missing_fields.includes(key) ? (
                        <span className="naming-field-flag naming-field-todo">待人工校正</span>
                      ) : naming.inferred_fields.includes(key) ? (
                        <span className="naming-field-flag naming-field-inferred">AI 推断</span>
                      ) : null}
                    </span>
                  </div>
                ))}
                <div className="naming-parse-row">
                  <span className="naming-parse-label">保密级别</span>
                  <span className="naming-parse-value"><span className={`confidentiality-badge confidentiality-${naming.confidentiality_level}`}>{naming.confidentiality_level}</span></span>
                </div>
                <div className="naming-parse-row">
                  <span className="naming-parse-label">AI 调用级别</span>
                  <span className="naming-parse-value"><span className={`ai-access-badge ai-access-${naming.ai_access_level}`}>{naming.ai_access_level}</span></span>
                </div>
                <div className="naming-parse-row">
                  <span className="naming-parse-label">置信度</span>
                  <span className="naming-parse-value">{confirmConfidence}</span>
                </div>
              </div>
              <div className="naming-parse-note">
                规范化标题由 AI 根据文件名 + 抽取正文 + 平台命名规范生成；标「AI 推断」为模型/默认推断字段，标「待人工校正」为缺乏依据的字段，请在下方人工校正区核对后提交。AI 调用级别由保密级别推导。
              </div>
            </>
          ) : (
            <div className="naming-parse-note">
              选择文件并启动资产化后，平台将异步抽取正文并由 AI 生成规范化命名解析结果（一级类 / 二级类 / 主题 / 对象/客户 / 日期 / 版本 / 保密级别 / AI 调用级别）。字段待后端返回。
            </div>
          )}
        </div>

      </section>

      {/* ════════ Path A: WeCom Drive pending tasks (real backend) ════════ */}
      {activePath === "a" && (
        <section className="upload-section">
          <div className="up-agent-head">
            <h3>企微微盘待确认文件</h3>
            <button className="btn-secondary" onClick={() => void loadPending()} disabled={pendingLoading}>
              {pendingLoading ? "刷新中…" : "刷新"}
            </button>
          </div>
          <p className="correction-hint">
            以下文件由企微微盘扫描自动检测并完成 AI 抽取与内容处理，请选择一项进行人工校正与确认入库。仅显示你有权确认的任务。
          </p>

          {pendingLoading ? (
            <div className="up-agent-state up-agent-loading">正在加载企微微盘待确认任务…</div>
          ) : pendingError ? (
            <div className="up-agent-state up-agent-error">
              <span>{pendingError}</span>
              <button className="btn-secondary" onClick={() => void loadPending()}>重试</button>
            </div>
          ) : pendingTasks.length === 0 ? (
            <div className="up-agent-state up-agent-empty">
              <div className="up-agent-empty-title">暂无待确认的企微微盘文件</div>
              <p>企微微盘扫描尚未产出待确认任务，或你对现有任务没有确认权限。</p>
              <Link to="/admin/wecom-scan" className="up-path-a-queue-link">前往企微微盘扫描配置 / 手动扫描 →</Link>
            </div>
          ) : (
            <div className="up-agent-file-list">
              {pendingTasks.map((t) => {
                const selected = taskId === t.id;
                const loadingThis = selected && flowState === "processing";
                return (
                  <button
                    key={t.id}
                    className={`up-agent-file-item ${selected ? "active" : ""} ${t.status === "failed" ? "failed" : ""}`}
                    onClick={() => { if (!loadingThis) void handleSelectPendingTask(t); }}
                    disabled={loadingThis}
                  >
                    <div className="up-agent-file-main">
                      <span className="up-agent-file-name">{t.source_file_name}</span>
                      <span className="ig-src-badge ig-src-wecom">企微微盘</span>
                      <span className={`up-agent-status up-agent-status-${t.status}`}>
                        {pendingStatusLabel[t.status] ?? t.status}
                      </span>
                    </div>
                    {t.suggested_title && (
                      <div className="up-agent-file-suggest">建议标题：{t.suggested_title}</div>
                    )}
                    <div className="up-agent-file-meta">
                      {t.confidence != null && <span>置信度 {Math.round(t.confidence * 100)}%</span>}
                      {t.created_at && <span>检测时间：{formatBeijingTime(t.created_at)}</span>}
                      {loadingThis && <span>正在加载 AI 建议…</span>}
                    </div>
                    {t.error_message && (
                      <div className="up-agent-file-error">处理异常：{t.error_message}</div>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </section>
      )}

      {/* ════════ Path B: Local upload flow ════════ */}
      {activePath === "b" && <>
        {/* Flow status bar */}
        <div className={`up-flow-bar ${flow.cls}`}>
          <span className="up-flow-indicator" />
          <span className="up-flow-text">{flow.text}</span>
          {flowState === "processing" && <span className="up-flow-spinner" />}
          <span className="up-flow-note">真实上传 · 文件字节写入平台受控本地存储（dev）</span>
        </div>

        {/* Upload entry */}
        <section className="upload-section">
          <h3>上传入口</h3>
          {!hasFile ? (
            <div className="upload-dropzone" onClick={() => fileRef.current?.click()}>
              <input ref={fileRef} type="file" className="up-file-input" accept=".pptx,.pdf,.docx,.xlsx,.doc,.xls,.ppt" onChange={handleFileSelect} />
              <p className="dropzone-main">点击选择文件或拖拽到此区域</p>
              <p className="dropzone-hint">支持 .pptx .pdf .docx .xlsx 等格式，单文件最大 25 MiB</p>
              <div className="dropzone-security">
                <span className="dropzone-security-badge">受控上传</span>
                <span>选中文件的字节会上传至平台受控本地存储（dev）；后端只返回安全元数据，不返回存储路径或对象 URL</span>
              </div>
            </div>
          ) : (
            <div className="up-file-info">
              <div className="up-file-detail">
                <div className="up-file-name">{fileName}</div>
                <div className="up-file-meta">
                  <span>{formatFileSize(fileSize)}</span>
                  <span>{fileType}</span>
                </div>
              </div>
              <div className="up-file-actions">
                {flowState === "file_selected" && (
                  <button className="btn-primary" onClick={handleStart}>开始资产化</button>
                )}
                {flowState === "processing" && (
                  <button className="btn-secondary" disabled>处理中…</button>
                )}
                {(flowState === "file_selected" || flowState === "processing") && (
                  <button className="btn-secondary" onClick={handleReset}>取消</button>
                )}
              </div>
            </div>
          )}

          {/* 文本抽取结果（真实抽取；后续内容处理由外部 LLM，失败时降级为确定性建议） */}
          {extraction && (
            <div className={`up-extraction up-extraction-${extraction.status ?? "unknown"}`}>
              <div className="up-extraction-head">
                <span className="up-extraction-label">文本抽取</span>
                <span className="up-extraction-status">{extractionLabel[extraction.status ?? ""] ?? extraction.status}</span>
                {extraction.charCount != null && extraction.status === "extracted" && (
                  <span className="up-extraction-meta">{extraction.charCount} 字</span>
                )}
              </div>
              {extraction.isDuplicate && (
                <div className="up-extraction-dup">检测到内容相同的既有任务（软提示，不阻断）：任务 {extraction.duplicateTaskId}</div>
              )}
              {extraction.errorMessage && (
                <div className="up-extraction-error">{extraction.errorMessage}</div>
              )}
              {extraction.preview && (
                <pre className="up-extraction-preview">{extraction.preview}</pre>
              )}
            </div>
          )}
        </section>

        {/* Security & desensitization（短诚实边界，详情入帮助页） */}
        <section className="upload-section">
          <h3>安全与脱敏</h3>
          <p className="page-help-line">
            文本抽取与外部 LLM 内容处理<strong>已真实接入</strong>（不可用时 fail-closed 降级）；抽取成功后<strong>入库前已做规则实体脱敏</strong>，平台侧外部 LLM 内容建议仅使用脱敏后文本；不可抽取文本则无法做文本级前置脱敏。WeKnora 底座按已确认信任边界仍可接触原文做索引。未实现：OCR、结构保持式文件重写、Ollama/LLM 脱敏、历史资产全量重索引。详见 <Link to="/help#ingest" className="page-help-link">使用说明 →</Link>
          </p>
          {desensitization && desensitization.status && (
            <div className={`up-desensitization up-desensitization-${desensitization.status}`}>
              <span className="up-desensitization-label">前置脱敏</span>
              <span className="up-desensitization-status">
                {desensitization.message ?? desensitization.status}
              </span>
              {desensitization.counts && Object.keys(desensitization.counts).length > 0 && (
                <span className="up-desensitization-counts">
                  {Object.entries(desensitization.counts)
                    .map(([cat, n]) => `${desensCategoryLabel[cat] ?? cat}×${n}`)
                    .join("，")}
                </span>
              )}
            </div>
          )}
        </section>
      </>}

      {/* ════════ Shared confirmation area ════════ */}
      {(confirmReady || confirmSubmitted) && <>
        {/* Source context bar */}
        <div className="up-source-bar">
          <span className={`ig-src-badge ${activePath === "a" ? "ig-src-wecom" : "ig-src-local"}`}>{sourceLabel}</span>
          <span className="up-source-file">{sourceFile}</span>
        </div>

        {/* AI preview card */}
        <section className="upload-section">
          <h3>AI 生成预览</h3>
          <div className="preview-card">
            <div className="card-header">
              <span className="card-title">{editTitle}</span>
              <div className="card-header-badges">
                <span className="asset-type-badge">交付物</span>
                <span className="visibility-badge project-only">{editVisibility}</span>
              </div>
            </div>
            <p className="card-summary">{editSummary}</p>
            <div className="card-tags">
              {editTags.split(/[·,，、\s]+/).filter(Boolean).map((t) => (
                <span key={t} className="tag">{t.trim()}</span>
              ))}
            </div>
            <div className="card-meta">
              <span>置信度 {confirmConfidence}</span>
              <span>来源：{sourceFile}</span>
              <span>来源渠道：{sourceLabel}</span>
            </div>
            <p className="preview-hint">* 以上为真实抽取 + 外部 LLM 内容处理建议（失败时降级为确定性建议），下方可编辑校正</p>
          </div>
        </section>

        {/* Human correction */}
        <section className="upload-section">
          <h3>人工校正</h3>
          <p className="correction-hint">
            {confirmReady
              ? "以下字段来自真实抽取 + 外部 LLM 内容处理（降级时为确定性建议），可直接编辑修改后提交。"
              : "处理中 / 已提交 / 处理失败时字段不可编辑。"}
          </p>
          {llmStatus && (
            <div className={`up-llm-status up-llm-${llmStatus.status ?? "unknown"}`}>
              {llmStatus.status === "llm"
                ? `内容建议由外部 LLM 生成（${llmStatus.provider ?? "—"}）`
                : "外部 LLM 未启用或调用失败，已降级为确定性建议，请人工补全三层摘要"}
            </div>
          )}
          <div className="correction-grid">
            <div className="correction-row">
              <div className="correction-field">标题</div>
              <div className="correction-value">
                {confirmReady ? (
                  <input className="up-edit-input" value={editTitle} onChange={(e) => setEditTitle(e.target.value)} />
                ) : (
                  <span className="up-edit-disabled">{editTitle}</span>
                )}
              </div>
              <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
                {confirmReady ? "可编辑" : "只读"}
              </div>
            </div>
            <div className="correction-row">
              <div className="correction-field">一句话摘要</div>
              <div className="correction-value">
                {confirmReady ? (
                  <input className="up-edit-input" value={editOneLiner} onChange={(e) => setEditOneLiner(e.target.value)} />
                ) : (
                  <span className="up-edit-disabled">{editOneLiner}</span>
                )}
              </div>
              <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
                {confirmReady ? "可编辑" : "只读"}
              </div>
            </div>
            <div className="correction-row">
              <div className="correction-field">详细摘要</div>
              <div className="correction-value">
                {confirmReady ? (
                  <textarea className="up-edit-textarea" value={editSummary} onChange={(e) => setEditSummary(e.target.value)} />
                ) : (
                  <span className="up-edit-disabled">{editSummary}</span>
                )}
              </div>
              <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
                {confirmReady ? "可编辑" : "只读"}
              </div>
            </div>
            <div className="correction-row">
              <div className="correction-field">关键知识点<br /><span className="correction-hint">每行一条</span></div>
              <div className="correction-value">
                {confirmReady ? (
                  <textarea className="up-edit-textarea" value={editKeyPoints} placeholder="每行一条关键知识点" onChange={(e) => setEditKeyPoints(e.target.value)} />
                ) : (
                  <span className="up-edit-disabled">{editKeyPoints}</span>
                )}
              </div>
              <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
                {confirmReady ? "可编辑" : "只读"}
              </div>
            </div>
            <div className="correction-row">
              <div className="correction-field">标签</div>
              <div className="correction-value">
                {confirmReady ? (
                  <input className="up-edit-input" value={editTags} onChange={(e) => setEditTags(e.target.value)} />
                ) : (
                  <span className="up-edit-disabled">{editTags}</span>
                )}
              </div>
              <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
                {confirmReady ? "可编辑" : "只读"}
              </div>
            </div>
            <div className="correction-row">
              <div className="correction-field">可见性</div>
              <div className="correction-value">
                {confirmReady ? (
                  <select className="up-edit-select" value={editVisibility} onChange={(e) => setEditVisibility(e.target.value)}>
                    {visibilityOptions.map((o) => <option key={o}>{o}</option>)}
                  </select>
                ) : (
                  <span className="up-edit-disabled">{editVisibility}</span>
                )}
              </div>
              <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
                {confirmReady ? "可编辑" : "只读"}
              </div>
            </div>
            <div className="correction-row">
              <div className="correction-field">业务阶段</div>
              <div className="correction-value">
                {confirmReady ? (
                  <select className="up-edit-select" value={editBizStage} onChange={(e) => setEditBizStage(e.target.value)}>
                    {bizStageOptions.map((o) => <option key={o}>{o}</option>)}
                  </select>
                ) : (
                  <span className="up-edit-disabled">{editBizStage}</span>
                )}
              </div>
              <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
                {confirmReady ? "可编辑" : "只读"}
              </div>
            </div>
            <div className="correction-row">
              <div className="correction-field">资产类型</div>
              <div className="correction-value">
                {confirmReady ? (
                  <select className="up-edit-select" value={editAssetType} onChange={(e) => setEditAssetType(e.target.value)}>
                    {assetTypeOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                ) : (
                  <span className="up-edit-disabled">{assetTypeOptions.find((o) => o.value === editAssetType)?.label ?? editAssetType}</span>
                )}
              </div>
              <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>{confirmReady ? "可编辑" : "只读"}</div>
            </div>
            <div className="correction-row">
              <div className="correction-field">保密级别</div>
              <div className="correction-value">
                {confirmReady ? (
                  <select className="up-edit-select" value={editConfidentiality} onChange={(e) => setEditConfidentiality(e.target.value)}>
                    {confidentialityOptions.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : (
                  <span className="up-edit-disabled">{editConfidentiality}</span>
                )}
              </div>
              <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>{confirmReady ? "可编辑" : "只读"}</div>
            </div>
            <div className="correction-row">
              <div className="correction-field">AI 调用级别</div>
              <div className="correction-value">
                {confirmReady ? (
                  <select className="up-edit-select" value={editAiAccess} onChange={(e) => setEditAiAccess(e.target.value)}>
                    {aiAccessOptions.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : (
                  <span className="up-edit-disabled">{editAiAccess}</span>
                )}
              </div>
              <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>{confirmReady ? "可编辑" : "只读"}</div>
            </div>
            <div className="correction-row">
              <div className="correction-field">置信度</div>
              <div className="correction-value">
                <span className="up-edit-disabled">{confirmConfidence}</span>
              </div>
              <div className="correction-status readonly">只读</div>
            </div>
          </div>
        </section>

        {/* AI recommendation + actions */}
        <section className="upload-section">
          <h3>AI 建议目标知识库</h3>
          <p className="correction-hint">
            {confirmReady
              ? "以下目标由 AI 根据文件内容、项目上下文与可见性自动推荐。如有偏差，可直接修正。"
              : "已提交，目标不可修改。"}
          </p>
          <div className="up-target-library">
            <label className="up-target-label">AI 建议</label>
            {confirmReady ? (
              <select
                className="up-edit-select"
                value={targetLibrary}
                onChange={(e) => setTargetLibrary(e.target.value as TargetLibrary)}
              >
                {targetLibraryOptions.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            ) : (
              <span className="up-edit-disabled">
                {targetLibraryOptions.find((o) => o.value === targetLibrary)!.label}
              </span>
            )}
            {confirmReady && <span className="up-target-adjust-hint">如不准确可修改</span>}
          </div>
          {targetLibrary === "project" && confirmReady && (
            <div className="up-target-library">
              <label className="up-target-label">目标项目</label>
              {projects.length > 0 ? (
                <select
                  className="up-edit-select"
                  value={targetProjectId}
                  onChange={(e) => setTargetProjectId(e.target.value)}
                >
                  {projects.map((p) => (
                    <option key={p.projectId} value={p.projectId}>{p.projectName}</option>
                  ))}
                </select>
              ) : (
                <span className="up-edit-disabled">你不是任何项目的有效成员，无法提交到项目知识库</span>
              )}
            </div>
          )}
          <p className="page-help-line">
            目标库与资料区 / 资产区分区规则、入库 / 审核分流说明见 <Link to="/help#ingest" className="page-help-link">使用说明 →</Link>
          </p>
          {apiError && <div className="up-submit-notice" style={{ color: "var(--color-danger-fg, #b00)" }}>{apiError}</div>}
          {processingNote && (
            <div className="up-submit-notice" style={{ color: "var(--color-warning-fg, #8a6d00)" }}>{processingNote}</div>
          )}
          <div className="detail-actions-bar">
            <button className="btn-primary" disabled={!canSubmit} onClick={handleSubmit}>提交入库</button>
            <button className="btn-secondary" disabled>保存草稿</button>
            <button className="btn-secondary" onClick={handleReset}>{confirmSubmitted ? "再入库一条" : "取消"}</button>
          </div>
          {confirmSubmitted && resultAssetId && (
            submitIndexStatus === "index_failed" ? (
              <div className="up-submit-notice" style={{ color: "var(--color-warning-fg, #8a6d00)" }}>
                已确认入库并保存校正内容（zone = material），但知识底座索引暂未完成，稍后可重试或联系管理员；在此之前该资产可能暂不可被语义检索召回。
                <Link to={`/knowledge/${resultAssetId}`}>查看新资产 →</Link>
              </div>
            ) : (
              <div className="up-submit-notice">
                已真实入库（zone = material）{submitIndexStatus === "skipped" ? "；知识底座未启用，已跳过索引" : ""}。
                <Link to={`/knowledge/${resultAssetId}`}>查看新资产 →</Link>
              </div>
            )
          )}
        </section>
      </>}

      {/* Path B placeholder when not yet ready */}
      {activePath === "b" && !confirmReady && !confirmSubmitted && (
        <section className="upload-section">
          <h3>AI 生成预览</h3>
          <div className="up-preview-placeholder">
            <div className="up-preview-placeholder-title">
              {flowState === "processing" ? "AI 正在提取中…" : "待生成"}
            </div>
            <p>
              {flowState === "processing"
                ? "文件已上传至平台受控存储，worker 正在异步抽取文本并调用外部 LLM 生成建议，请稍候…"
                : "选择文件并启动资产化后，平台将异步抽取文本并由外部 LLM 生成标题、摘要、标签等结构化建议（LLM 不可用时降级为确定性建议）"}
            </p>
          </div>
        </section>
      )}
    </div>
  );
}

