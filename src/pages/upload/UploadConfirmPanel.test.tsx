import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import UploadConfirmPanel, { confirmationSubjectLabel } from "./UploadConfirmPanel";
import type { UploadFlow } from "./useUploadFlow";

describe("confirmation subject label", () => {
  it("uses 主题 for governed libraries and 标题 for personal intake", () => {
    expect(confirmationSubjectLabel("project")).toBe("主题");
    expect(confirmationSubjectLabel("company")).toBe("主题");
    expect(confirmationSubjectLabel("personal")).toBe("标题");
    expect(confirmationSubjectLabel("")).toBe("建议主题");
  });
});

function fakeFlow(overrides: Partial<UploadFlow> = {}): UploadFlow {
  const noop = () => {};
  return {
    sourceLabel: "本地上传",
    sourceFile: "retail.txt",
    extraction: null,
    desensitization: null,
    naming: null,
    namingOptions: null,
    namingCategoryId: "",
    setNamingCategoryId: noop,
    namingFormedOn: "",
    setNamingFormedOn: noop,
    namingVersion: "V1",
    setNamingVersion: noop,
    namingApplicableTo: "",
    setNamingApplicableTo: noop,
    namingPreview: null,
    namingPreviewBusy: false,
    namingPreviewError: null,
    namingRequired: false,
    editTitle: "",
    setEditTitle: noop,
    editOneLiner: "",
    setEditOneLiner: noop,
    editSummary: "",
    setEditSummary: noop,
    editKeyPoints: "",
    setEditKeyPoints: noop,
    editTags: "",
    setEditTags: noop,
    editConfidentiality: "L2",
    setEditConfidentiality: noop,
    targetLibrary: "personal",
    setTargetLibrary: noop,
    targetProjectId: "",
    setTargetProjectId: noop,
    projects: [],
    suggestionGeneration: { status: "needs_manual_completion", reason: "生成失败" },
    targetLocked: false,
    canUseCompanyTarget: false,
    llmStatus: {
      status: "llm",
      provider: "deepseek",
      summaryStatus: "failed",
      generationModelRef: null,
    },
    apiError: null,
    confirmSubmitted: false,
    canSubmit: false,
    resultAssetId: null,
    awaitingProjectReview: false,
    submitIndexStatus: null,
    generationErrorCategory: "response_error",
    regenerating: false,
    regenerationError: null,
    handleRegenerateSuggestions: vi.fn(),
    handleSubmit: vi.fn(),
    handleReset: vi.fn(),
    models: { weknoraDisabled: true } as UploadFlow["models"],
    ...overrides,
  } as UploadFlow;
}

describe("UploadConfirmPanel AI regeneration", () => {
  it("offers regenerate for transient generation failures and wires the click", () => {
    const handleRegenerateSuggestions = vi.fn();
    render(
      <UploadConfirmPanel
        flow={fakeFlow({ handleRegenerateSuggestions })}
        onExit={() => {}}
        onReject={() => {}}
      />,
    );

    const button = screen.getByRole("button", { name: "重新生成建议" });
    fireEvent.click(button);
    expect(handleRegenerateSuggestions).toHaveBeenCalledTimes(1);
  });

  it("shows busy text while regenerating", () => {
    render(
      <UploadConfirmPanel
        flow={fakeFlow({ regenerating: true })}
        onExit={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "正在重新生成…" })).toBeDisabled();
  });

  it("does not offer regenerate for permanent failures", () => {
    render(
      <UploadConfirmPanel
        flow={fakeFlow({ generationErrorCategory: "model_unavailable" })}
        onExit={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: "重新生成建议" })).not.toBeInTheDocument();
    expect(screen.getByText(/当前不可自动重试/)).toBeInTheDocument();
  });

  it("surfaces a regeneration error from the flow", () => {
    render(
      <UploadConfirmPanel
        flow={fakeFlow({ regenerationError: "当前任务暂不可重试，请稍后再试或联系管理员。" })}
        onExit={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("当前任务暂不可重试");
  });
});
