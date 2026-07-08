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

  it("describes Markdown and plain text as supported upload materials", () => {
    expect(source).toContain("支持 Markdown、PDF、Word、PPT、Excel、纯文本等资料");
    expect(source).not.toContain("支持 .pptx .pdf .docx .xlsx 等格式");
  });
});
