import { describe, expect, it } from "vitest";

const modules = import.meta.glob("../pages/upload/UploadStepB.tsx", {
  eager: true,
  query: "?raw",
  import: "default",
}) as Record<string, string>;

const source = modules["../pages/upload/UploadStepB.tsx"];

describe("upload format support copy", () => {
  it("allows Markdown and plain text in the local upload file picker", () => {
    expect(source).toContain(".md");
    expect(source).toContain(".markdown");
    expect(source).toContain(".txt");
  });

  it("distinguishes PPTX extraction from the legacy PPT fallback", () => {
    expect(source).toContain("支持 Markdown、PDF、Word、PPTX 自动提取及 Excel、纯文本等资料");
    expect(source).toContain(".ppt 仅保存，需人工补全");
    expect(source).not.toContain("支持 Markdown、PDF、Word、PPT、Excel、纯文本等资料");
    expect(source).not.toContain("支持 .pptx .pdf .docx .xlsx 等格式");
  });
});

const confirmModules = import.meta.glob("../pages/upload/UploadConfirmPanel.tsx", {
  eager: true,
  query: "?raw",
  import: "default",
}) as Record<string, string>;

describe("upload summary generation copy", () => {
  const confirmSource = confirmModules["../pages/upload/UploadConfirmPanel.tsx"];

  it("does not label degraded extracted text as an AI generated summary", () => {
    expect(confirmSource).toContain("摘要待生成：当前未配置内容生成模型。");
    expect(confirmSource).toContain(
      "摘要生成失败，当前不可自动重试，请稍后再试或联系管理员检查内容生成模型配置。",
    );
    expect(confirmSource).toContain("内容建议预览");
    expect(confirmSource).not.toContain("AI 生成预览");
  });
});
