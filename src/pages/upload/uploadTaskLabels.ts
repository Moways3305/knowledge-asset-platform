import type { IngestTaskStage } from "../../types/ingest";

export const PROCESSING_STAGE_LABELS: Partial<Record<IngestTaskStage, string>> = {
  upload_saved: "原件已接收",
  processing_claimed: "任务已领取",
  text_extraction: "正在提取正文",
  ocr_queued: "OCR 等待中",
  ocr_in_progress: "正在 OCR 识别",
  ocr_failed: "OCR 识别失败",
  ocr_too_complex: "文件过大或过于复杂",
  ocr_complete: "OCR 已完成",
  processing_interrupted: "处理中断，等待恢复",
  source_unavailable: "原文件不可用，需重新上传",
  canonical_markdown_generation: "正在生成 Markdown",
  content_generation_queued: "内容生成等待中",
  content_generation: "正在生成内容建议",
  waiting_generation_config: "等待内容生成模型配置",
  content_generation_failed: "内容生成失败",
  content_result_persistence_failed: "内容生成结果保存失败",
  processing_state_persistence_failed: "处理状态保存失败",
};

export function queueFailureReason(
  error: string | null,
  stage?: IngestTaskStage,
  errorCode?: string | null,
): string {
  const code = errorCode?.trim().toLowerCase();
  if (code) {
    if (code === "extraction_process_terminated")
      return "文件解析进程被终止，原件已保留；请管理员检查内存与进程资源后重试";
    if (code === "extraction_memory_limit")
      return "文件解析达到内存限制，原件已保留；请管理员检查资源，或拆分文件后重试";
    if (code === "extraction_password_protected") return "文件受密码保护，请解锁后重新上传";
    if (code === "extraction_permission_restricted")
      return "PDF 可直接打开，但限制内容提取；请取得授权后的可提取版本再上传";
    if (
      code === "extraction_format_mismatch" ||
      code === "file_format_unsupported" ||
      code === "unsupported_file_type"
    )
      return "文件格式不符合处理要求，请检查后重新上传";
    if (
      code === "extraction_structure_limit" ||
      code === "extraction_archive_limit" ||
      code === "ocr_resource_limit"
    )
      return "文件页数、图像或版面过于复杂，请拆分文件后重试";
    if (
      code === "file_parse_failed" ||
      code === "extraction_corrupt" ||
      code === "ocr_source_invalid"
    )
      return "文件可能损坏或无法解析，请确认扩展名后重新上传";
    if (code === "processing_timeout" || code === "ocr_timeout") return "处理超时，稍后可重试";
    if (code === "source_file_unavailable") return "原文件暂时不可用，请重新选择原文件";
  }

  const value = `${stage ?? ""} ${error ?? ""}`.toLowerCase();
  if (
    value.includes("password") ||
    value.includes("encrypt") ||
    value.includes("密码") ||
    value.includes("加密") ||
    value.includes("受保护")
  )
    return "文件受密码保护，请解锁后重新上传";
  if (value.includes("confidence") || value.includes("置信度"))
    return "OCR 识别置信度不足，请上传更清晰的文件或改为人工校对";
  if (
    stage === "ocr_too_complex" ||
    value.includes("too_complex") ||
    value.includes("too complex") ||
    value.includes("解压后体积异常") ||
    value.includes("过于复杂") ||
    value.includes("复杂度")
  )
    return "文件页数、图像或版面过于复杂，请拆分文件后重试";
  if (value.includes("timeout") || value.includes("超时")) return "处理超时，稍后可重试";
  if (stage === "source_unavailable" || value.includes("原文件"))
    return "原文件暂时不可用，请重新选择原文件";
  if (
    value.includes("unsupported") ||
    value.includes("不支持") ||
    value.includes("格式不符") ||
    value.includes("扩展名不匹配")
  )
    return "文件格式不符合处理要求，请检查后重新上传";
  if (
    value.includes("corrupt") ||
    value.includes("damaged") ||
    value.includes("损坏") ||
    value.includes("无法读取") ||
    value.includes("无法解析")
  )
    return "文件可能损坏或无法解析，请确认扩展名后重新上传";
  if (
    value.includes("network") ||
    value.includes("interrupted") ||
    value.includes("传输失败") ||
    value.includes("连接中断") ||
    value.includes("网关") ||
    value.includes("上传失败")
  )
    return "文件传输失败，请检查网络后重试";
  if (
    value.includes("temporarily unavailable") ||
    value.includes("service_unavailable") ||
    value.includes("暂时不可用") ||
    value.includes("服务不可用")
  )
    return "处理服务暂时不可用，请稍后重试";
  return "本文件暂未完成处理，请按操作重试或重新选择原文件";
}
