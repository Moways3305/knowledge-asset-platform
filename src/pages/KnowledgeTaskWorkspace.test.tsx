import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import KnowledgeTaskWorkspace from "./KnowledgeTaskWorkspace";
import {
  fetchTask,
  recentTasks,
  type KnowledgeTask,
  type KnowledgeTaskDetail,
} from "../api/knowledgeTasks";
import { reportCorrection } from "../api/knowledgeTrust";
import { fetchAgentPolicies } from "../api/maintenanceAgent";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ authMe: { userId: "consultant", activeCompanyRole: "consultant" } }),
}));
vi.mock("../api/maintenanceAgent", () => ({
  fetchAgentPolicies: vi.fn(async () => [{ library_key: "company", name: "公司知识库" }]),
}));

it("keeps the workspace session and fragment when changing business tabs or libraries", async () => {
  vi.mocked(fetchAgentPolicies).mockResolvedValue([
    { library_key: "company", name: "公司知识库" },
    { library_key: "project:alpha", name: "交付项目库" },
  ] as Awaited<ReturnType<typeof fetchAgentPolicies>>);
  vi.mocked(recentTasks).mockResolvedValue([]);
  render(
    <MemoryRouter
      initialEntries={[
        "/ai-workspace/agents/knowledge-maintenance?library=company&tab=tasks&session=one#reading",
      ]}
    >
      <KnowledgeTaskWorkspace embedded />
    </MemoryRouter>,
  );
  const library = await screen.findByRole("combobox", { name: "知识库" });
  await screen.findByRole("option", { name: "交付项目库" });
  fireEvent.change(library, { target: { value: "project:alpha" } });
  const issues = new URL(
    screen.getByRole("link", { name: "维护待办" }).getAttribute("href")!,
    "https://kap.example",
  );
  expect(issues.pathname).toBe("/ai-workspace/agents/knowledge-maintenance");
  expect(issues.searchParams.get("library")).toBe("project:alpha");
  expect(issues.searchParams.get("session")).toBe("one");
  expect(issues.searchParams.get("tab")).toBe("issues");
  expect(issues.hash).toBe("#reading");
});
vi.mock("../api/knowledgeTasks", () => ({
  delegate: vi.fn(),
  fetchTask: vi.fn(),
  recentTasks: vi.fn(),
}));
vi.mock("../api/knowledgeTrust", () => ({ reportCorrection: vi.fn() }));

it("keeps the open evidence and edited correction when a different task finishes", async () => {
  const row: KnowledgeTask = {
    id: "reference",
    instruction: "找访谈提纲",
    status: "ready",
    created_at: "2026-11-01T00:00:00Z",
  };
  const other: KnowledgeTask = { ...row, id: "other", instruction: "另一件事", status: "checking" };
  const data: KnowledgeTaskDetail = {
    ...row,
    failure_reason: null,
    mode: "model",
    candidates: 2,
    inspected: 1,
    availability: "available",
    evidence: {
      title: "制造业访谈提纲",
      asset_id: "asset",
      version_id: "v2",
      version: "V2",
      matched: ["访谈提纲"],
      summary_matched: [],
      unmatched: [],
      summary: "新增产线排程。",
      needs_update: false,
      original: true,
      pending_update: false,
      parsed: true,
      history_truncated: false,
      correction_status: null,
      old_source_links: [],
      compared_version: "V1",
      changed_fields: ["summary"],
      previous_summary: "基础访谈",
      current_summary: "新增产线排程。",
      updated_at: row.created_at,
    },
  };
  vi.mocked(recentTasks)
    .mockResolvedValueOnce([row, other])
    .mockResolvedValue([{ ...other, status: "ready" }, row]);
  vi.mocked(fetchTask).mockResolvedValue(data);
  render(
    <MemoryRouter>
      <KnowledgeTaskWorkspace />
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "预览更新建议" }));
  const edit = screen.getByLabelText("给维护人的更新建议");
  fireEvent.change(edit, { target: { value: "请再核对产线安排。" } });
  edit.focus();
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 2700));
  });
  expect(vi.mocked(recentTasks).mock.calls.length).toBeGreaterThanOrEqual(2);
  expect(screen.getByLabelText("给维护人的更新建议")).toBe(edit);
  expect(edit).toHaveFocus();
  expect(edit).toHaveValue("请再核对产线安排。");
  expect(reportCorrection).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "确认提交给维护人" }));
  expect(reportCorrection).toHaveBeenCalledWith("asset", {
    reason: "请再核对产线安排。",
    expected_updated_at: row.created_at,
  });
});
