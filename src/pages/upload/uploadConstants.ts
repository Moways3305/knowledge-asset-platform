// 资产化确认工作台的常量 / 选项 / 小工具。原散落在 UploadPage 顶部，提取到此。
export type PathBranch = "a" | "b";
export type FlowState = "idle" | "file_selected" | "processing" | "ready" | "failed" | "submitted";
export type TargetLibrary = "personal" | "project" | "company";

// 异步 worker 处理时，上传后轮询 ai-result 直至处理完成/失败/超时。
export const POLL_INTERVAL_MS = 2000;
export const POLL_MAX_ATTEMPTS = 30; // 约 60s 上限
export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export const targetLibraryOptions: { value: TargetLibrary; label: string }[] = [
  { value: "personal", label: "个人知识库" },
  { value: "project", label: "项目知识库" },
  { value: "company", label: "公司知识库" },
];

// Path A 待确认任务状态中文标签（来自后端 IngestStatus）。
export const pendingStatusLabel: Record<string, string> = {
  processing: "处理中",
  pending_confirmation: "待确认",
  pending: "待处理",
  waiting_review: "待审核",
  failed: "处理失败",
};

export const extractionLabel: Record<string, string> = {
  extracted: "抽取成功",
  unsupported: "暂不支持该格式（已落盘，请人工补全）",
  empty: "未抽取到文本（可能为扫描件/纯图片）",
  failed: "抽取失败（文件可能损坏）",
};

// 入库前置脱敏类别 → 中文标签（仅展示类别计数，不含原值）。
export const desensCategoryLabel: Record<string, string> = {
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

export const visibilityOptions = ["公开", "项目内", "机密"];
// 前端中文可见性 → 后端 enum key（不要把中文发给 API）。
export const visibilityToKey: Record<string, "public" | "project_only" | "confidential"> = {
  公开: "public",
  项目内: "project_only",
  机密: "confidential",
};
export const assetTypeOptions: { value: string; label: string }[] = [
  { value: "methodology", label: "方法论" },
  { value: "deliverable", label: "交付物" },
  { value: "case", label: "案例" },
  { value: "template", label: "模板" },
  { value: "insight", label: "洞察" },
];
export const confidentialityOptions = ["L1", "L2", "L3", "L4", "L5"];
export const aiAccessOptions = ["A1", "A2", "A3", "A4"];
export const bizStageOptions = ["售前", "诊断", "启动共识", "定题", "目标计划", "行动辅导", "阶段评估", "年度复盘", "专项诊断"];

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function flowLabel(state: FlowState): { text: string; cls: string } {
  switch (state) {
    case "idle": return { text: "等待选择文件", cls: "flow-idle" };
    case "file_selected": return { text: "文件已选择，待处理", cls: "flow-selected" };
    case "processing": return { text: "处理中…", cls: "flow-processing" };
    case "ready": return { text: "待人工校正", cls: "flow-ready" };
    case "failed": return { text: "处理失败", cls: "flow-failed" };
    case "submitted": return { text: "已提交", cls: "flow-submitted" };
  }
}
