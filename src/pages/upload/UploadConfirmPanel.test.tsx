import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
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

describe("UploadConfirmPanel intake destination", () => {
  it("keeps the edited destination and content connected to confirmation", () => {
    const submit = vi.fn();
    const exit = vi.fn();
    function Confirmation() {
      const [draft, setDraft] = useState({
        targetLibrary: "" as UploadFlow["targetLibrary"],
        targetProjectId: "",
        directoryKey: "",
        editConfidentiality: "L2",
        editSummary: "初始摘要",
      });
      return (
        <UploadConfirmPanel
          flow={fakeFlow({
            ...draft,
            projects: [{ projectId: "project-a", projectName: "项目 A" }],
            namingOptions: {
              required: false,
              rule_version: 1,
              default_confidentiality: "L2",
              message: null,
              directories: [
                {
                  directory_key: "project.reference",
                  display_name: "参考资料",
                  scope: "project",
                  sort_order: 1,
                  enabled: true,
                },
              ],
            },
            setTargetLibrary: (targetLibrary) =>
              setDraft((value) => ({
                ...value,
                targetLibrary:
                  typeof targetLibrary === "function"
                    ? targetLibrary(value.targetLibrary)
                    : targetLibrary,
              })),
            setTargetProjectId: (targetProjectId) =>
              setDraft((value) => ({
                ...value,
                targetProjectId:
                  typeof targetProjectId === "function"
                    ? targetProjectId(value.targetProjectId)
                    : targetProjectId,
              })),
            setDirectoryKey: (directoryKey) => setDraft((value) => ({ ...value, directoryKey })),
            setEditConfidentiality: (editConfidentiality) =>
              setDraft((value) => ({
                ...value,
                editConfidentiality:
                  typeof editConfidentiality === "function"
                    ? editConfidentiality(value.editConfidentiality)
                    : editConfidentiality,
              })),
            setEditSummary: (editSummary) =>
              setDraft((value) => ({
                ...value,
                editSummary:
                  typeof editSummary === "function" ? editSummary(value.editSummary) : editSummary,
              })),
            canSubmit: true,
            handleSubmit: () => submit(draft),
          })}
          onExit={exit}
          onReject={() => {}}
        />
      );
    }
    render(<Confirmation />);
    fireEvent.change(screen.getByLabelText("目标知识库"), { target: { value: "project" } });
    fireEvent.change(screen.getByLabelText("目标项目"), { target: { value: "project-a" } });
    fireEvent.change(screen.getByLabelText(/^正式目录/), {
      target: { value: "project.reference" },
    });
    fireEvent.change(screen.getByLabelText("密级"), { target: { value: "L3" } });
    fireEvent.change(screen.getByLabelText("详细摘要"), { target: { value: "人工核对后的摘要" } });
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认入库" }));
    expect(submit).toHaveBeenCalledWith({
      targetLibrary: "project",
      targetProjectId: "project-a",
      directoryKey: "project.reference",
      editConfidentiality: "L3",
      editSummary: "人工核对后的摘要",
    });
    fireEvent.click(screen.getByRole("button", { name: "返回文件任务" }));
    expect(exit).toHaveBeenCalledOnce();
    expect(submit).toHaveBeenCalledOnce();
  });

  it("preserves a source-locked project and hides unavailable company intake", () => {
    render(
      <UploadConfirmPanel
        flow={fakeFlow({
          targetLibrary: "project",
          targetProjectId: "source-project",
          targetLocked: true,
          projects: [{ projectId: "source-project", projectName: "来源项目" }],
        })}
        onExit={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByLabelText("目标知识库")).toBeDisabled();
    expect(screen.getByLabelText("目标项目")).toBeDisabled();
    expect(screen.getByLabelText("目标项目")).toHaveValue("source-project");
    expect(screen.queryByRole("option", { name: /公司/ })).not.toBeInTheDocument();
  });
});
