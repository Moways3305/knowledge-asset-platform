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
  retryWorkspaceRun: vi.fn(),
  renameWorkspaceSession: vi.fn(),
  deleteWorkspaceSession: vi.fn(),
  saveWorkspaceArtifact: vi.fn(),
  isWorkspaceRunActive: (run: api.WorkspaceRun) =>
    run.status === "running" || run.status === "queued",
}));

const date = "2026-11-27T02:00:00Z";
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
  vi.mocked(api.getWorkspaceOptions).mockResolvedValue({
    models: [{ model_ref: "model-one", display_name: "模型一", is_default: true }],
    contexts: [{ key: "company", label: "公司知识库" }],
    tools: [],
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
    const entry = screen.getByRole("link", { name: "打开知识维护 Agent" });
    expect(entry).not.toHaveAttribute("target");
    expect(entry).toHaveAttribute(
      "href",
      "/ai-workspace/agents/knowledge-maintenance?tab=issues&session=one",
    );
    fireEvent.click(entry);
    await settle();
    expect(screen.getByText("内嵌业务页")).toBeInTheDocument();
    expect(window.document.querySelector(".ai-workspace")).toBe(workspace);
    expect(screen.getByTestId("current-path")).toHaveTextContent(
      "/ai-workspace/agents/knowledge-maintenance?tab=issues&session=one",
    );
    fireEvent.click(screen.getByRole("button", { name: "返回 Agent 列表" }));
    expect(screen.getByRole("heading", { name: "让 Agent 接手一类工作" })).toBeInTheDocument();
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
    act(() => opener.focus());
    fireEvent.click(opener);
    const navigation = screen.getByRole("dialog", { name: "工作空间导航" });
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
