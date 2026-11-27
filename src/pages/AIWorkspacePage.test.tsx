import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AIWorkspacePage from "./AIWorkspacePage";
import * as api from "../api/aiWorkspace";
import { ApiError } from "../api/http";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    authMe: { userId: "user", name: "验收用户", activeCompanyRole: "consultant" },
    reload: vi.fn(),
  }),
}));
vi.mock("./MaintenanceAgentPage", () => ({
  default: ({ embedded }: { embedded?: boolean }) => (
    <p>{embedded ? "内嵌业务页" : "独立业务页"}</p>
  ),
}));
vi.mock("../api/aiWorkspace", () => ({
  getWorkspaceOptions: vi.fn(),
  listWorkspaceSessions: vi.fn(),
  getWorkspaceDetail: vi.fn(),
  getWorkspaceEvents: vi.fn(),
  createWorkspaceSession: vi.fn(),
  sendWorkspaceMessage: vi.fn(),
  stopWorkspaceRun: vi.fn(),
  resumeWorkspaceRun: vi.fn(),
  decideWorkspaceAction: vi.fn(),
  renameWorkspaceSession: vi.fn(),
  deleteWorkspaceSession: vi.fn(),
  saveWorkspaceArtifact: vi.fn(),
  isWorkspaceRunActive: (run: api.WorkspaceRun) =>
    ["running", "queued", "waiting", "awaiting_confirmation"].includes(run.status),
}));

const date = "2026-11-27T02:00:00Z";
const maintenanceAgent = {
  key: "knowledge-maintenance",
  label: "知识维护 Agent",
  description: "检查知识、核对依据并持续跟进",
  tools: [{ key: "list_issues", label: "查看维护问题", description: "查看选定知识库的未解决事项" }],
};
const session = (id = "one"): api.WorkspaceSession => ({
  id,
  title: `会话 ${id}`,
  created_at: date,
  updated_at: date,
});
const run: api.WorkspaceRun = {
  id: "run-one",
  status: "running",
  model_ref: "model-one",
  context_key: null,
  error_code: null,
  created_at: date,
  finished_at: null,
};
const document: api.WorkspaceArtifact = {
  id: "artifact-one",
  title: "工作文档",
  content: "已保存的正文",
  revision: 1,
  run_id: run.id,
  created_at: date,
  updated_at: date,
};
const snapshot = (id = "one"): api.WorkspaceDetail => ({
  session: session(id),
  runs: [run],
  artifacts: [document],
  messages: [
    {
      id: "message-one",
      role: "user",
      content: `整理资料 ${id}`,
      run_id: run.id,
      created_at: date,
    },
  ],
});
async function settle(milliseconds = 1) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}
function CurrentPath() {
  const location = useLocation();
  return (
    <output data-testid="current-path">
      {location.pathname}
      {location.search}
      {location.hash}
    </output>
  );
}
function mount(path = "/ai-workspace?session=one") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="ai-workspace" element={<AIWorkspacePage />}>
          <Route index element={null} />
          <Route path="agents/knowledge-maintenance" element={null} />
        </Route>
      </Routes>
      <CurrentPath />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  vi.mocked(api.createWorkspaceSession).mockReset();
  vi.mocked(api.sendWorkspaceMessage).mockReset();
  vi.mocked(api.getWorkspaceOptions).mockResolvedValue({
    models: [{ model_ref: "model-one", display_name: "模型一", is_default: true }],
    contexts: [{ key: "company", label: "公司知识库" }],
    tools: [],
    agents: [maintenanceAgent],
  });
  vi.mocked(api.listWorkspaceSessions).mockResolvedValue([session(), session("two")]);
  vi.mocked(api.getWorkspaceEvents).mockResolvedValue({
    cursor: 1,
    events: [{ id: 1, run_id: run.id, type: "running", label: "读取资料", created_at: date }],
  });
  vi.mocked(api.getWorkspaceDetail).mockImplementation(async (id) => snapshot(id));
});
afterEach(() => {
  vi.useRealTimers();
});

describe("AI workspace lifecycle", () => {
  it("selects an Agent in the composer without losing the input, model or project context", async () => {
    vi.mocked(api.getWorkspaceOptions).mockResolvedValue({
      models: [
        { model_ref: "model-one", display_name: "模型一", is_default: true },
        { model_ref: "model-two", display_name: "模型二", is_default: false },
      ],
      contexts: [{ key: "project:example", label: "示例项目" }],
      agents: [maintenanceAgent],
      tools: [],
    });
    vi.mocked(api.createWorkspaceSession).mockResolvedValue({
      ...session("picked-agent"),
      agent_key: maintenanceAgent.key,
    });
    vi.mocked(api.sendWorkspaceMessage).mockResolvedValue({ ...run, status: "queued" });
    mount("/ai-workspace");
    await settle();
    const input = screen.getByLabelText("消息");
    fireEvent.change(input, { target: { value: "检查这个项目的资料" } });
    fireEvent.change(screen.getByLabelText("对话模型"), { target: { value: "model-two" } });
    fireEvent.click(screen.getByRole("button", { name: "添加上下文" }));
    fireEvent.click(screen.getByRole("radio", { name: "示例项目" }));
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    const picker = screen.getByRole("button", { name: "添加智能体" });
    expect(picker.textContent).toBe("");
    fireEvent.click(picker);
    fireEvent.click(screen.getByRole("menuitemradio", { name: maintenanceAgent.label }));
    await settle();
    expect(screen.getByLabelText("消息")).toBe(input);
    expect(input).toHaveValue("检查这个项目的资料");
    expect(screen.getByLabelText("对话模型")).toHaveValue("model-two");
    expect(
      screen.queryByRole("heading", { name: "让 Agent 接手一类工作" }),
    ).not.toBeInTheDocument();
    expect(api.createWorkspaceSession).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    await settle();
    expect(api.createWorkspaceSession).toHaveBeenCalledWith(
      expect.any(String),
      maintenanceAgent.key,
    );
    expect(api.sendWorkspaceMessage).toHaveBeenCalledWith(
      "picked-agent",
      expect.objectContaining({
        content: "检查这个项目的资料",
        model_ref: "model-two",
        context_key: "project:example",
      }),
    );
  });

  it("can remove an Agent while retaining the same draft and defaults to an available company library", async () => {
    mount("/ai-workspace");
    await settle();
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "保留这段输入" } });
    fireEvent.click(screen.getByRole("button", { name: "添加智能体" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: maintenanceAgent.label }));
    await settle();
    expect(screen.getByRole("button", { name: "添加上下文" })).toHaveAttribute(
      "data-selected",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: /^(添加|切换)智能体$/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "通用对话" }));
    await settle();
    expect(screen.getByLabelText("消息")).toHaveValue("保留这段输入");
    expect(screen.getByTestId("current-path")).toHaveTextContent(/^\/ai-workspace$/);
    expect(screen.getByRole("heading", { name: "今天，想推进什么？" })).toBeInTheDocument();
    expect(api.createWorkspaceSession).not.toHaveBeenCalled();
  });

  it("keeps Agent selection locked while the first message is being submitted", async () => {
    let finish: ((value: api.WorkspaceSession) => void) | undefined;
    vi.mocked(api.createWorkspaceSession).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    vi.mocked(api.sendWorkspaceMessage).mockResolvedValue({ ...run, status: "queued" });
    mount("/ai-workspace");
    await settle();
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "整理资料" } });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    expect(screen.getByRole("button", { name: "添加智能体" })).toBeDisabled();
    await act(async () => {
      finish?.(session("sent"));
    });
    expect(api.createWorkspaceSession).toHaveBeenCalledWith(expect.any(String), null);
    expect(api.createWorkspaceSession).toHaveBeenCalledTimes(1);
  });

  it("never reuses a failed Agent submission session after switching to general chat", async () => {
    vi.mocked(api.createWorkspaceSession)
      .mockResolvedValueOnce({ ...session("agent-failed"), agent_key: maintenanceAgent.key })
      .mockResolvedValueOnce(session("general-retry"));
    vi.mocked(api.sendWorkspaceMessage)
      .mockRejectedValueOnce(new ApiError(503, "稍后重试"))
      .mockResolvedValueOnce({ ...run, status: "queued" });
    mount("/ai-workspace?agent=knowledge-maintenance");
    await settle();
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "检查资料" } });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: /^(添加|切换)智能体$/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "通用对话" }));
    await settle();
    expect(screen.getByLabelText("消息")).toHaveValue("检查资料");
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    await settle();
    const creates = vi.mocked(api.createWorkspaceSession).mock.calls;
    expect(creates.map((call) => call[1])).toEqual([maintenanceAgent.key, null]);
    expect(creates[0][0]).not.toBe(creates[1][0]);
    expect(vi.mocked(api.sendWorkspaceMessage).mock.calls.map((call) => call[0])).toEqual([
      "agent-failed",
      "general-retry",
    ]);
  });

  it("keeps an existing conversation bound to its server identity", async () => {
    mount("/ai-workspace?session=one&agent=knowledge-maintenance");
    await settle();
    expect(screen.queryByRole("button", { name: /^(添加|切换)智能体$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "知识维护辅助视图" })).not.toBeInTheDocument();
    expect(api.createWorkspaceSession).not.toHaveBeenCalled();
  });

  it("creates an Agent session with its identity and selected library instead of a legacy task", async () => {
    vi.mocked(api.createWorkspaceSession).mockResolvedValue({
      ...session("agent-session"),
      agent_key: maintenanceAgent.key,
    });
    vi.mocked(api.sendWorkspaceMessage).mockResolvedValue({
      ...run,
      status: "queued",
      context_key: "company",
    });
    mount("/ai-workspace/agents/knowledge-maintenance?tab=tasks");
    await settle();
    expect(screen.queryByText("内嵌业务页")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "请跟进未解决的问题" } });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    await settle();
    expect(api.createWorkspaceSession).toHaveBeenCalledWith(
      expect.any(String),
      maintenanceAgent.key,
    );
    expect(api.sendWorkspaceMessage).toHaveBeenCalledWith(
      "agent-session",
      expect.objectContaining({ context_key: "company", content: "请跟进未解决的问题" }),
    );
  });

  it("keeps notification deep links in the maintenance view and returns to the same Agent conversation", async () => {
    vi.mocked(api.getWorkspaceDetail).mockResolvedValue({
      ...snapshot(),
      session: { ...session(), agent_key: maintenanceAgent.key },
      runs: [{ ...run, context_key: "project:example" }],
    });
    mount(
      "/ai-workspace/agents/knowledge-maintenance?tab=issues&library=project%3Aexample&target_id=reminder&session=one#issue-detail",
    );
    await settle();
    expect(screen.getByText("内嵌业务页")).toBeInTheDocument();
    expect(screen.getByTestId("current-path")).toHaveTextContent(
      "target_id=reminder&session=one#issue-detail",
    );
    fireEvent.click(screen.getByRole("button", { name: "返回 Agent 会话" }));
    await settle();
    expect(screen.getByText("整理资料 one")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "维护待办" })).toHaveAttribute(
      "href",
      expect.stringContaining("library=project%3Aexample"),
    );
    expect(screen.getByRole("link", { name: "维护待办" }).getAttribute("href")).not.toContain(
      "target_id=",
    );
  });

  it.each(["digest_id=reminder", "asset_id=asset", "target_id=reminder"])(
    "opens the management view for a bare %s deep link",
    async (query) => {
      mount(`/ai-workspace/agents/knowledge-maintenance?library=company&${query}`);
      await settle();
      expect(screen.getByText("内嵌业务页")).toBeInTheDocument();
      expect(screen.queryByLabelText("消息")).not.toBeInTheDocument();
    },
  );

  it("retains a project scope when a reminder opens without an existing Agent session", async () => {
    vi.mocked(api.createWorkspaceSession).mockResolvedValue({
      ...session("agent-project"),
      agent_key: maintenanceAgent.key,
    });
    vi.mocked(api.sendWorkspaceMessage).mockResolvedValue({ ...run, status: "queued" });
    mount(
      "/ai-workspace/agents/knowledge-maintenance?tab=issues&library=project%3Aexample&target_id=reminder",
    );
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "返回 Agent 会话" }));
    await settle();
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "跟进这个项目的问题" } });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    await settle();
    expect(api.sendWorkspaceMessage).toHaveBeenCalledWith(
      "agent-project",
      expect.objectContaining({ context_key: "project:example" }),
    );
  });

  it("requires a decision on the concrete action and reuses its id after a lost acknowledgement", async () => {
    const pending = {
      id: "action-one",
      tool: "request_recheck",
      label: "复检指定资料",
      summary: "复检合成资料的当前版本，通过后再关闭对应问题。",
      arguments: { issue_id: "issue-one", version_id: "version-one" },
    };
    vi.mocked(api.getWorkspaceDetail).mockResolvedValue({
      ...snapshot(),
      session: { ...session(), agent_key: maintenanceAgent.key },
      runs: [{ ...run, status: "awaiting_confirmation", pending_action: pending }],
    });
    vi.mocked(api.decideWorkspaceAction)
      .mockRejectedValueOnce(new ApiError(503, "确认结果暂未返回"))
      .mockResolvedValueOnce(run);
    mount();
    await settle();
    expect(screen.getByRole("region", { name: "确认本次操作" })).toHaveTextContent(pending.summary);
    expect(screen.queryByRole("button", { name: "发送消息" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }));
    await settle();
    const calls = vi.mocked(api.decideWorkspaceAction).mock.calls;
    expect(calls[0]).toEqual(["one", run.id, "action-one", expect.any(String), "approve"]);
    expect(calls[1][3]).toBe(calls[0][3]);
    expect(api.sendWorkspaceMessage).not.toHaveBeenCalled();
  });

  it("rejects only the pending action and retains the draft", async () => {
    vi.mocked(api.getWorkspaceDetail).mockResolvedValue({
      ...snapshot(),
      runs: [
        {
          ...run,
          status: "awaiting_confirmation",
          pending_action: {
            id: "action-two",
            tool: "scan",
            label: "开展全面巡检",
            summary: "仅检查公司知识库",
            arguments: { library_key: "company" },
          },
        },
      ],
    });
    vi.mocked(api.decideWorkspaceAction).mockResolvedValue(run);
    mount();
    await settle();
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "先保留这个补充要求" } });
    fireEvent.click(screen.getByRole("button", { name: "拒绝本次操作" }));
    await settle();
    expect(api.decideWorkspaceAction).toHaveBeenCalledWith(
      "one",
      run.id,
      "action-two",
      expect.any(String),
      "reject",
    );
    expect(screen.getByLabelText("消息")).toHaveValue("先保留这个补充要求");
  });

  it.each(["running", "waiting"] as const)(
    "adds instructions to the same %s run",
    async (status) => {
      vi.mocked(api.getWorkspaceDetail).mockResolvedValue({
        ...snapshot(),
        runs: [{ ...run, status, waiting_reason: "external_task" }],
      });
      vi.mocked(api.resumeWorkspaceRun).mockResolvedValue(run);
      mount();
      await settle();
      expect(screen.getByRole("combobox", { name: "对话模型" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "添加上下文" })).toBeDisabled();
      expect(screen.getByLabelText("消息")).toBeEnabled();
      fireEvent.change(screen.getByLabelText("消息"), {
        target: { value: "优先检查摘要里的个人信息" },
      });
      fireEvent.click(screen.getByRole("button", { name: "补充并继续" }));
      await settle();
      expect(api.resumeWorkspaceRun).toHaveBeenCalledWith(
        "one",
        run.id,
        expect.any(String),
        "优先检查摘要里的个人信息",
      );
      expect(api.sendWorkspaceMessage).not.toHaveBeenCalled();
    },
  );

  it.each(["failed", "stopped"] as const)(
    "resumes the same %s run without repeating completed actions",
    async (status) => {
      vi.mocked(api.getWorkspaceDetail).mockResolvedValue({
        ...snapshot(),
        runs: [{ ...run, status }],
      });
      vi.mocked(api.resumeWorkspaceRun).mockResolvedValue(run);
      mount();
      await settle();
      fireEvent.click(screen.getByRole("button", { name: "继续任务" }));
      await settle();
      expect(api.resumeWorkspaceRun).toHaveBeenCalledWith("one", run.id, expect.any(String));
      expect(api.createWorkspaceSession).not.toHaveBeenCalled();
    },
  );
  it("keeps the same workspace and unsent drafts while entering and leaving an Agent", async () => {
    mount();
    await settle();
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "保留未发送的追问" } });
    fireEvent.click(screen.getByRole("button", { name: /工作文档.*点击预览和编辑/ }));
    fireEvent.click(screen.getByRole("tab", { name: "编辑" }));
    fireEvent.change(screen.getByLabelText("文档正文"), { target: { value: "保留未保存的文档" } });
    const workspace = window.document.querySelector(".ai-workspace");
    fireEvent.click(screen.getByRole("button", { name: "Agent" }));
    fireEvent.click(screen.getByText("知识维护 Agent", { selector: "strong" }));
    const entry = screen.getByRole("link", { name: "开始任务" });
    expect(entry).not.toHaveAttribute("target");
    expect(entry).toHaveAttribute("href", "/ai-workspace?agent=knowledge-maintenance");
    fireEvent.click(entry);
    await settle();
    expect(screen.getByRole("heading", { name: "交给我一个知识维护目标" })).toBeInTheDocument();
    expect(window.document.querySelector(".ai-workspace")).toBe(workspace);
    expect(screen.getByTestId("current-path")).toHaveTextContent(
      "/ai-workspace?agent=knowledge-maintenance",
    );
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "Agent 自己的任务草稿" } });
    fireEvent.click(screen.getByRole("link", { name: "维护待办" }));
    await settle();
    expect(screen.getByText("内嵌业务页")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回 Agent 会话" }));
    await settle();
    expect(screen.getByLabelText("消息")).toHaveValue("Agent 自己的任务草稿");
    fireEvent.click(screen.getByRole("button", { name: "会话 one" }));
    await settle();
    expect(screen.getByLabelText("消息")).toHaveValue("保留未发送的追问");
    expect(screen.getByLabelText("文档正文")).toHaveValue("保留未保存的文档");
    expect(screen.getByRole("complementary", { name: "文档预览" })).toBeVisible();
  });

  it("updates completed runs in place without disturbing editor, input, preview or reading position", async () => {
    mount();
    await settle();
    fireEvent.click(screen.getByRole("button", { name: /工作文档.*点击预览和编辑/ }));
    fireEvent.click(screen.getByRole("tab", { name: "编辑" }));
    const body = screen.getByLabelText("文档正文");
    fireEvent.change(body, { target: { value: "我正在编辑的内容" } });
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "还没发出的追问" } });
    body.focus();
    const scroll = window.document.querySelector(".aw-chat-scroll") as HTMLElement;
    Object.defineProperty(scroll, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(scroll, "clientHeight", { configurable: true, value: 300 });
    scroll.scrollTop = 100;
    fireEvent.scroll(scroll);
    vi.mocked(api.getWorkspaceDetail).mockResolvedValue({
      ...snapshot(),
      runs: [{ ...run, status: "completed" }],
      messages: [
        ...snapshot().messages,
        { id: "answer", role: "assistant", content: "处理完成", run_id: run.id, created_at: date },
      ],
    });
    await settle(2000);
    expect(screen.getByText("处理完成")).toBeInTheDocument();
    expect(screen.getByLabelText("消息")).toHaveValue("还没发出的追问");
    expect(screen.getByLabelText("文档正文")).toBe(body);
    expect(body).toHaveValue("我正在编辑的内容");
    expect(body).toHaveFocus();
    expect(scroll.scrollTop).toBe(100);
    expect(screen.getByRole("complementary", { name: "文档预览" })).toBeVisible();
  });

  it("keeps an unsent message and reuses submission id after a lost response", async () => {
    vi.mocked(api.createWorkspaceSession).mockResolvedValue(session("created"));
    vi.mocked(api.sendWorkspaceMessage)
      .mockRejectedValueOnce(new ApiError(503, "连接中断，请重试"))
      .mockResolvedValueOnce({ ...run, status: "queued" });
    mount("/ai-workspace");
    await settle();
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "整理成一份工作文档" } });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    await settle();
    expect(screen.getByRole("alert")).toHaveTextContent("连接中断，请重试");
    expect(screen.getByLabelText("消息")).toHaveValue("整理成一份工作文档");
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    await settle();
    expect(api.createWorkspaceSession).toHaveBeenCalledTimes(1);
    expect(api.sendWorkspaceMessage).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.sendWorkspaceMessage).mock.calls[0][1].request_id).toBe(
      vi.mocked(api.sendWorkspaceMessage).mock.calls[1][1].request_id,
    );
    expect(screen.getByLabelText("消息")).toHaveValue("");
  });

  it("ignores a late snapshot from the previous session", async () => {
    let finish: ((value: api.WorkspaceDetail) => void) | undefined;
    vi.mocked(api.getWorkspaceDetail).mockImplementation((id) =>
      id === "one"
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : Promise.resolve(snapshot(id)),
    );
    mount();
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "会话 two" }));
    await settle();
    await act(async () => {
      finish?.(snapshot());
    });
    expect(screen.getByText("整理资料 two")).toBeInTheDocument();
    expect(screen.queryByText("整理资料 one")).not.toBeInTheDocument();
  });

  it("revalidates source access even with unchanged event cursor and removes revoked drafts", async () => {
    mount();
    await settle();
    fireEvent.click(screen.getByRole("button", { name: /工作文档.*点击预览和编辑/ }));
    fireEvent.click(screen.getByRole("tab", { name: "编辑" }));
    fireEvent.change(screen.getByLabelText("文档正文"), {
      target: { value: "权限撤销前的本地草稿" },
    });
    vi.mocked(api.getWorkspaceDetail).mockResolvedValue({ ...snapshot(), artifacts: [] });
    await settle(2000);
    expect(screen.queryByRole("complementary", { name: "文档预览" })).not.toBeInTheDocument();
    vi.mocked(api.getWorkspaceDetail).mockResolvedValue({
      ...snapshot(),
      artifacts: [{ ...document, content: "重新授权后的正文", revision: 2 }],
    });
    await settle(2000);
    fireEvent.click(screen.getByRole("button", { name: /工作文档.*点击预览和编辑/ }));
    expect(screen.getByLabelText("文档正文")).toHaveValue("重新授权后的正文");
    expect(screen.queryByDisplayValue("权限撤销前的本地草稿")).not.toBeInTheDocument();
  });

  it("confirms deleting a conversation and retains it when deletion fails", async () => {
    vi.mocked(api.deleteWorkspaceSession).mockRejectedValueOnce(new ApiError(503, "暂时无法删除"));
    mount();
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "删除会话" }));
    const dialog = screen.getByRole("dialog", { name: "删除会话" });
    expect(api.deleteWorkspaceSession).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "确认删除" }));
    await settle();
    expect(within(dialog).getByRole("alert")).toHaveTextContent("暂时无法删除");
    expect(screen.getByText("整理资料 one")).toBeInTheDocument();
  });

  it("does not navigate away from Agent when an earlier send finishes", async () => {
    let finish: ((value: api.WorkspaceRun) => void) | undefined;
    vi.mocked(api.createWorkspaceSession).mockResolvedValue(session("created"));
    vi.mocked(api.sendWorkspaceMessage).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    mount("/ai-workspace");
    await settle();
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "安排文档" } });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Agent" }));
    await act(async () => {
      finish?.({ ...run, status: "queued" });
    });
    expect(screen.getByRole("heading", { name: "让 Agent 接手一类工作" })).toBeInTheDocument();
  });

  it("does not erase the shared draft if the recipient changes through the Agent directory during a send", async () => {
    let finish: ((value: api.WorkspaceRun) => void) | undefined;
    vi.mocked(api.createWorkspaceSession).mockResolvedValue(session("earlier-chat"));
    vi.mocked(api.sendWorkspaceMessage).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    mount("/ai-workspace");
    await settle();
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "保留这项任务" } });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Agent" }));
    fireEvent.click(screen.getByText("知识维护 Agent", { selector: "strong" }));
    fireEvent.click(screen.getByRole("link", { name: "开始任务" }));
    await settle();
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "另一位智能体的草稿" } });
    await act(async () => {
      finish?.({ ...run, status: "queued" });
    });
    expect(screen.getByLabelText("消息")).toHaveValue("另一位智能体的草稿");
    expect(screen.getByTestId("current-path")).toHaveTextContent("agent=knowledge-maintenance");
    expect(api.createWorkspaceSession).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "会话 earlier-chat" }));
    await settle();
    expect(screen.getByLabelText("消息")).toHaveValue("");
    expect(screen.getByRole("button", { name: "添加上下文" })).toHaveAttribute(
      "data-selected",
      "false",
    );
  });

  it("does not show an earlier recipient's send error in the new Agent draft", async () => {
    let fail: ((cause: Error) => void) | undefined;
    vi.mocked(api.createWorkspaceSession).mockResolvedValue(session("earlier-chat"));
    vi.mocked(api.sendWorkspaceMessage).mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          fail = reject;
        }),
    );
    mount("/ai-workspace");
    await settle();
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "原来的任务" } });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "Agent" }));
    fireEvent.click(screen.getByText("知识维护 Agent", { selector: "strong" }));
    fireEvent.click(screen.getByRole("link", { name: "开始任务" }));
    await settle();
    await act(async () => {
      fail?.(new ApiError(503, "之前的发送失败"));
    });
    expect(screen.queryByText("之前的发送失败")).not.toBeInTheDocument();
    expect(screen.getByLabelText("消息")).toHaveValue("原来的任务");
    expect(screen.getByTestId("current-path")).toHaveTextContent("agent=knowledge-maintenance");
  });

  it("can create a new conversation after the previous session was deleted", async () => {
    vi.mocked(api.getWorkspaceEvents).mockRejectedValueOnce(new ApiError(404, "会话不存在"));
    mount();
    await settle();
    expect(screen.queryByLabelText("消息")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "新建会话" }));
    await settle();
    expect(screen.getByLabelText("消息")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "今天，想推进什么？" })).toBeInTheDocument();
  });

  it("dismisses a keyboard tooltip before navigation and returns focus to its opener", async () => {
    mount();
    await settle();
    const opener = screen.getByRole("button", { name: "打开导航" });
    const closer = screen.getByRole("button", { name: "关闭导航", hidden: true });
    const matches = closer.matches.bind(closer);
    // jsdom does not carry keyboard modality through programmatic dialog focus.
    const keyboardFocus = vi
      .spyOn(closer, "matches")
      .mockImplementation((selector) => selector === ":focus-visible" || matches(selector));
    act(() => opener.focus());
    fireEvent.click(opener, { detail: 0 });
    keyboardFocus.mockRestore();
    const navigation = screen.getByRole("dialog", { name: "工作空间导航" });
    expect(closer).toHaveFocus();
    expect(screen.getByRole("tooltip")).toHaveTextContent("关闭导航");
    fireEvent.keyDown(navigation, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(navigation).toBeInTheDocument();
    fireEvent.keyDown(navigation, { key: "Escape" });
    await settle(20);
    expect(screen.queryByRole("dialog", { name: "工作空间导航" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(window.document.querySelector("main")!.inert).toBe(false);
  });

  it("selects the loaded default model without discarding a draft typed while options load", async () => {
    let finish: ((value: api.WorkspaceOptions) => void) | undefined;
    vi.mocked(api.getWorkspaceOptions).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    mount("/ai-workspace");
    fireEvent.change(screen.getByLabelText("消息"), { target: { value: "正在输入的目标" } });
    await act(async () => {
      finish?.({
        models: [{ model_ref: "loaded", display_name: "已配置模型", is_default: true }],
        contexts: [],
        tools: [],
      });
    });
    expect(screen.getByLabelText("消息")).toHaveValue("正在输入的目标");
    expect(screen.getByLabelText("对话模型")).toHaveValue("loaded");
    expect(screen.getByRole("button", { name: "发送消息" })).toBeEnabled();
  });

  it("opens context from its icon and describes the active knowledge library", async () => {
    mount("/ai-workspace");
    await settle();
    const button = screen.getByRole("button", { name: "添加上下文" });
    expect(button.textContent).toBe("");
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("radio", { name: "公司知识库" }));
    fireEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(button).toHaveAttribute("data-selected", "true");
    fireEvent.pointerOver(button, { pointerType: "mouse" });
    expect(screen.getByRole("tooltip")).toHaveTextContent("上下文：公司知识库");
    expect(screen.getByRole("combobox", { name: "对话模型" })).toHaveValue("model-one");
  });

  it("does not redirect the newly selected session when an earlier deletion completes", async () => {
    let finish: (() => void) | undefined;
    vi.mocked(api.deleteWorkspaceSession).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    mount();
    await settle();
    fireEvent.click(screen.getByRole("button", { name: "删除会话" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    fireEvent.click(screen.getByRole("button", { name: "会话 two" }));
    await settle();
    await act(async () => {
      finish?.();
    });
    expect(screen.getByText("整理资料 two")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "今天，想推进什么？" })).not.toBeInTheDocument();
    expect(api.deleteWorkspaceSession).toHaveBeenCalledWith("one");
  });
});
