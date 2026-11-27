import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import ArtifactPanel, { draftDifference, type ArtifactDraft } from "./ArtifactPanel";
import {
  getWorkspaceDetail,
  saveWorkspaceArtifact,
  type WorkspaceArtifact,
} from "../../api/aiWorkspace";
import { ApiError } from "../../api/http";

vi.mock("../../api/aiWorkspace", () => ({
  saveWorkspaceArtifact: vi.fn(),
  getWorkspaceDetail: vi.fn(),
}));
const artifact: WorkspaceArtifact = {
  id: "artifact",
  title: "项目文档",
  content: "初始正文",
  revision: 3,
  run_id: "run",
  created_at: "2026-11-27T00:00:00Z",
  updated_at: "2026-11-27T00:00:00Z",
};
function Editor() {
  const [draft, setDraft] = useState<ArtifactDraft>();
  return (
    <ArtifactPanel
      sessionId="session"
      artifact={artifact}
      draft={draft}
      updateDraft={(_id, update) => setDraft(update)}
      tab="edit"
      setTab={() => {}}
      open
      full={false}
      setFull={() => {}}
      onClose={() => {}}
      onSaved={() => {}}
    />
  );
}
describe("artifact draft", () => {
  it("sends optimistic revision and preserves local changes on save conflict", async () => {
    vi.mocked(saveWorkspaceArtifact).mockRejectedValueOnce(new ApiError(409, "conflict"));
    render(<Editor />);
    fireEvent.change(screen.getByLabelText("文档正文"), { target: { value: "本地修改" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("文档已有更新"));
    expect(saveWorkspaceArtifact).toHaveBeenCalledWith("session", "artifact", {
      title: "项目文档",
      content: "本地修改",
      expected_revision: 3,
    });
    expect(screen.getByLabelText("文档正文")).toHaveValue("本地修改");
    vi.mocked(getWorkspaceDetail).mockResolvedValue({
      session: {
        id: "session",
        title: "会话",
        created_at: artifact.created_at,
        updated_at: artifact.updated_at,
      },
      messages: [],
      runs: [],
      artifacts: [{ ...artifact, revision: 4, content: "另一标签页的新版本" }],
    });
    fireEvent.click(screen.getByRole("button", { name: "载入最新版本" }));
    expect(screen.getByLabelText("文档正文")).toHaveValue("本地修改");
    fireEvent.click(screen.getByRole("button", { name: "确认放弃本地修改" }));
    await waitFor(() =>
      expect(screen.getByLabelText("文档正文")).toHaveValue("另一标签页的新版本"),
    );
    expect(screen.getByRole("button", { name: "保存修改" })).toBeDisabled();
  });
  it("compares the changed section without discarding surrounding lines", () => {
    expect(
      draftDifference("共同开头\n旧段落\n共同结尾", "共同开头\n新段落\n新增行\n共同结尾"),
    ).toEqual({ start: 1, removed: "旧段落", added: "新段落\n新增行" });
  });

  it("does not restore a draft after the artifact panel was revoked or unmounted", async () => {
    let finish: ((value: WorkspaceArtifact) => void) | undefined;
    vi.mocked(saveWorkspaceArtifact).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const updateDraft = vi.fn();
    const { unmount } = render(
      <ArtifactPanel
        sessionId="session"
        artifact={artifact}
        draft={{
          title: artifact.title,
          content: "待保存",
          baseContent: artifact.content,
          baseTitle: artifact.title,
          revision: artifact.revision,
        }}
        updateDraft={updateDraft}
        tab="edit"
        setTab={() => {}}
        open
        full={false}
        setFull={() => {}}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    unmount();
    finish?.({ ...artifact, content: "待保存", revision: 4 });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(updateDraft).not.toHaveBeenCalled();
  });
});
