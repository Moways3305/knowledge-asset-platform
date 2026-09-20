import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AdminReleaseNotesPage from "./AdminReleaseNotesPage";
import ReleaseNotesPage from "./ReleaseNotesPage";
import { ApiError } from "../api/http";
import * as api from "../api/releaseNotes";

vi.mock("../api/releaseNotes", () => ({
  fetchReleaseNotes: vi.fn(),
  fetchReleaseStatus: vi.fn(),
  saveReleaseNote: vi.fn(),
  publishReleaseNote: vi.fn(),
  readReleaseNotes: vi.fn(),
  invalidateReleaseNotes: vi.fn(),
}));
const auth = vi.hoisted(() => ({ authMe: { userId: "user-a" }, capabilities: { isAdmin: true } }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth }));
const note: api.ReleaseNote = {
  id: "one",
  version: "v1.0.0",
  title: "上传体验优化",
  entries: [{ kind: "fixed", text: "人工标题不再被覆盖" }],
  notify_users: true,
  revision: 1,
  created_at: "2026-09-20T01:00:00Z",
  updated_at: "2026-09-20T01:00:00Z",
  published_at: null,
  is_unread: false,
};
const list = (items: api.ReleaseNote[], total = items.length): api.ReleaseList => ({
  items,
  total,
  page: 1,
  page_size: 10,
});
function mount(ui: React.ReactNode) {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      {ui}
    </MemoryRouter>,
  );
}
async function openDraft() {
  mount(<AdminReleaseNotesPage />);
  fireEvent.click(await screen.findByRole("button", { name: /上传体验优化/ }));
}

describe("administrator release workflow", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    auth.capabilities.isAdmin = true;
    vi.mocked(api.fetchReleaseNotes).mockResolvedValue(list([note]));
    vi.mocked(api.fetchReleaseStatus).mockResolvedValue({
      running_version: "0.9.0",
      unread_count: 1,
    });
    vi.mocked(api.readReleaseNotes).mockResolvedValue({
      running_version: "0.9.0",
      unread_count: 0,
    });
  });

  it("previews without writing, then saves edited content before publishing its new revision", async () => {
    const updated = { ...note, title: "人工修改保留", revision: 2 };
    vi.mocked(api.saveReleaseNote).mockResolvedValue(updated);
    vi.mocked(api.publishReleaseNote).mockResolvedValue({
      ...updated,
      published_at: "2026-09-20T02:00:00Z",
      revision: 3,
    });
    await openDraft();
    fireEvent.change(screen.getByLabelText("更新标题"), { target: { value: updated.title } });
    fireEvent.click(screen.getByRole("button", { name: "预览并发布" }));
    expect(screen.getByRole("dialog", { name: "发布预览" })).toBeInTheDocument();
    expect(api.saveReleaseNote).not.toHaveBeenCalled();
    expect(api.publishReleaseNote).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认发布" }));
    await waitFor(() => expect(api.publishReleaseNote).toHaveBeenCalledWith(updated));
    expect(api.saveReleaseNote).toHaveBeenCalledWith(
      expect.objectContaining({ title: updated.title }),
      note,
    );
    expect(await screen.findByText("版本日志已发布，所有登录用户均可查看。")).toBeInTheDocument();
  });

  it("keeps user edits when a stale draft is rejected and never publishes", async () => {
    vi.mocked(api.saveReleaseNote).mockRejectedValue(new ApiError(409, "日志已变更，请重新加载"));
    await openDraft();
    fireEvent.change(screen.getByLabelText("更新标题"), { target: { value: "我的修改" } });
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("日志已变更");
    expect(screen.getByLabelText("更新标题")).toHaveValue("我的修改");
    expect(api.publishReleaseNote).not.toHaveBeenCalled();
  });

  it("validates empty content before preview and protects unsaved edits on close", async () => {
    const originalOverflow = document.body.style.overflow;
    await openDraft();
    fireEvent.change(screen.getByLabelText("第 1 条内容"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "预览并发布" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("请至少添加一条");
    fireEvent.click(screen.getByRole("button", { name: "关闭弹窗" }));
    expect(screen.getByRole("dialog", { name: "放弃未保存的修改？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "继续编辑" }));
    expect(screen.getByLabelText("第 1 条内容")).toHaveValue("   ");
    fireEvent.click(screen.getByRole("button", { name: "关闭弹窗" }));
    fireEvent.click(screen.getByRole("button", { name: "放弃修改" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe(originalOverflow);
    await screen.findByRole("button", { name: /上传体验优化/ });
  });

  it("saves a silent draft without publishing", async () => {
    vi.mocked(api.saveReleaseNote).mockResolvedValue({ ...note, notify_users: false, revision: 2 });
    await openDraft();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));
    await waitFor(() =>
      expect(api.saveReleaseNote).toHaveBeenCalledWith(
        expect.objectContaining({ notify_users: false }),
        note,
      ),
    );
    expect(api.publishReleaseNote).not.toHaveBeenCalled();
    expect(await screen.findByRole("status")).toHaveTextContent("草稿已保存");
  });

  it("published history is read-only", async () => {
    vi.mocked(api.fetchReleaseNotes).mockResolvedValue(
      list([{ ...note, published_at: "2026-09-20T02:00:00Z" }]),
    );
    await openDraft();
    expect(screen.getByRole("dialog", { name: "已发布日志" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "保存草稿" })).not.toBeInTheDocument();
  });

  it("only acknowledges displayed notes and preserves the independent running version", async () => {
    auth.capabilities.isAdmin = false;
    vi.mocked(api.fetchReleaseNotes).mockResolvedValue(
      list([{ ...note, published_at: "2026-09-20T02:00:00Z", is_unread: true }], 20),
    );
    mount(<ReleaseNotesPage />);
    expect(await screen.findByText("上传体验优化")).toBeInTheDocument();
    await waitFor(() => expect(api.readReleaseNotes).toHaveBeenCalledWith(["one"]));
    expect(screen.getByText("v0.9.0")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "管理日志" })).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("navigation", { name: "日志分页" })).getByRole("button", {
        name: "下一页",
      }),
    ).toBeEnabled();
  });

  it("failed list fetch never acknowledges history and offers retry", async () => {
    vi.mocked(api.fetchReleaseNotes).mockRejectedValueOnce(new Error("offline"));
    mount(<ReleaseNotesPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法加载");
    expect(api.readReleaseNotes).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("上传体验优化")).toBeInTheDocument();
  });
});
