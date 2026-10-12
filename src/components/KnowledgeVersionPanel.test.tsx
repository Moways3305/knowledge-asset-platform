import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi, describe, it, expect, beforeEach } from "vitest";
import KnowledgeVersionPanel from "./KnowledgeVersionPanel";
import { fetchVersionHistory, uploadVersion, compareVersions } from "../api/knowledgeVersions";

vi.mock("../api/knowledgeVersions", () => ({
  fetchVersionHistory: vi.fn(),
  uploadVersion: vi.fn(),
  compareVersions: vi.fn(),
}));
vi.mock("../api/knowledgeTrust", () => ({ fetchTrust: vi.fn(), replaceTrust: vi.fn() }));
const history = {
  asset_id: "old",
  updated_at: "2026-10-12T00:00:00Z",
  current_asset_id: "old",
  can_update: true,
  suggested_version: "V2",
  truncated: false,
  updates: [],
  items: [
    {
      asset_id: "old",
      version_id: "v1",
      title: "操作规范",
      version: "V1",
      status: "active",
      version_status: "active",
      created_at: "2026-10-01T00:00:00Z",
      is_current: true,
    },
    {
      asset_id: "new",
      version_id: "v2",
      title: "新操作规范",
      version: "V2",
      status: "active",
      version_status: "active",
      created_at: "2026-10-12T00:00:00Z",
      is_current: false,
    },
  ],
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchVersionHistory).mockResolvedValue(history);
});
describe("version workflow", () => {
  it("opens a historical safe summary without redirecting to the current file", async () => {
    vi.mocked(compareVersions).mockResolvedValue({
      left: { version: "V1", directory: "personal.learning_notes", summary: "历史摘要" },
      right: { version: "V1", directory: "personal.learning_notes", summary: "历史摘要" },
      changed_fields: [],
      scope: "安全摘要",
    });
    render(
      <MemoryRouter>
        <KnowledgeVersionPanel assetId="old" />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "版本历史与差异" }));
    fireEvent.click(screen.getAllByRole("button", { name: "查看版本摘要" })[0]);
    expect(await screen.findByText("历史摘要")).toBeInTheDocument();
    expect(compareVersions).toHaveBeenCalledWith("old", "v1", "v1");
  });
  it("uploads with the original stamp and links to the existing confirmation flow", async () => {
    vi.mocked(uploadVersion).mockResolvedValue({
      ingest_task_id: "task-2",
      status: "processing",
      upload_url: null,
    });
    render(
      <MemoryRouter>
        <KnowledgeVersionPanel assetId="old" />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "更新这份资料" }));
    expect(screen.getByLabelText("新版本号")).toHaveValue("V2");
    const file = new File(["version2"], "V2.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("选择新版原文件"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "上传关联新版" }));
    expect(await screen.findByRole("link", { name: "继续处理并确认入库" })).toHaveAttribute(
      "href",
      "/upload?source=local&task_id=task-2",
    );
    expect(uploadVersion).toHaveBeenCalledWith("old", file, history.updated_at, "V2");
  });
  it("compares explicitly selected versions", async () => {
    vi.mocked(compareVersions).mockResolvedValue({
      left: { version: "V1", directory: "personal.learning_notes", summary: "旧摘要" },
      right: { version: "V2", directory: "personal.learning_notes", summary: "新摘要" },
      changed_fields: ["version", "summary"],
      scope: "摘要与版本元信息，不包含原文件全文",
    });
    render(
      <MemoryRouter>
        <KnowledgeVersionPanel assetId="old" />
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: "版本历史与差异" }));
    fireEvent.change(screen.getByLabelText("原版本"), { target: { value: "v1" } });
    fireEvent.change(screen.getByLabelText("新版本"), { target: { value: "v2" } });
    fireEvent.click(screen.getByRole("button", { name: "查看差异" }));
    await waitFor(() => expect(compareVersions).toHaveBeenCalledWith("old", "v1", "v2"));
    expect(await screen.findByText("旧摘要")).toBeInTheDocument();
    expect(screen.getByText("新摘要")).toBeInTheDocument();
  });
  it("hides upload for readers and shows the current replacement", async () => {
    vi.mocked(fetchVersionHistory).mockResolvedValue({
      ...history,
      can_update: false,
      current_asset_id: "new",
    });
    render(
      <MemoryRouter>
        <KnowledgeVersionPanel assetId="old" />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: "查看当前版本" })).toHaveAttribute(
      "href",
      "/knowledge/new",
    );
    expect(screen.queryByRole("button", { name: "更新这份资料" })).not.toBeInTheDocument();
  });
});
