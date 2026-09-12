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

  it("advertises legacy Office conversion without promising image-only extraction", () => {
    expect(source).toContain("Word（DOC/DOCX）、PPT/PPTX");
    expect(source).toContain("DOC/PPT 自动转换并提取正文");
    expect(source).toContain("纯图片内容可能需要人工补全");
    expect(source).not.toContain(".ppt 仅保存，需人工补全");
  });

  it("shows the 100 MB single-file limit", () => {
    expect(source.replace(/\s+/g, " ")).toContain("单文件最大 100 MB");
    expect(source).not.toContain("单文件最大 25");
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
