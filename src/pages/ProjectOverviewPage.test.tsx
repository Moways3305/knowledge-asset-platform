import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProjectOverviewPage from "./ProjectOverviewPage";

const api = vi.hoisted(() => ({
  fetchProjects: vi.fn(),
  fetchProjectOverview: vi.fn(),
  fetchProjectQaModelOptions: vi.fn(),
  projectQa: vi.fn(),
}));

vi.mock("../api/project", () => api);

const PROJECT_A = "00000000-0000-0000-0000-000000000078";
const PROJECT_B = "00000000-0000-0000-0000-000000000079";

const projects = [
  {
    id: PROJECT_A,
    name: "华东增长项目",
    client_name: "华东客户中心",
    status: "active",
    lifecycle_route_key: "route_A",
    lifecycle_phase_key: "诊断",
    created_at: "2026-07-01T08:00:00Z",
    project_role: "consultant",
    can_manage: false,
  },
  {
    id: PROJECT_B,
    name: "年度辅导项目",
    client_name: null,
    status: "active",
    lifecycle_route_key: "route_B",
    lifecycle_phase_key: "年度复盘",
    created_at: "2026-07-02T08:00:00Z",
    project_role: "project_manager",
    can_manage: true,
  },
];

function overview(projectId = PROJECT_A, overrides: Record<string, unknown> = {}) {
  const source = projects.find((project) => project.id === projectId) ?? projects[0];
  return {
    project: {
      project_id: source.id,
      name: source.name,
      client_name: source.client_name,
      status: source.status,
      project_role: source.project_role,
      lifecycle_route_key: source.lifecycle_route_key,
      lifecycle_phase_key: source.lifecycle_phase_key,
      can_manage: source.can_manage,
    },
    capabilities: {
      can_view_knowledge: true,
      can_upload_material: true,
      can_manage_members: false,
      can_manage_kb: false,
      can_confirm_assets: false,
    },
    counts: {
      material_count: 12,
      asset_count: 7,
      pending_confirmation_count: 3,
      pending_review_count: 2,
      original_access_request_count: 1,
    },
    knowledge_base: { configured: true, status: "active" },
    members: [],
    recent_activity: [],
    ...overrides,
  };
}

const modelOptions = {
  items: [
    { model_ref: "qa-secondary-secret", display_name: "备用问答模型", is_default: false },
    { model_ref: "qa-default-secret", display_name: "项目默认问答模型", is_default: true },
  ],
  total: 2,
};

const qaAnswer = {
  call_id: "call-secret-78",
  response_text: "访谈材料显示，客户当前最关注交付节奏与复盘机制。",
  model_key: "qa-default-secret",
  decision_status: "allowed",
  citations: [
    {
      asset_id: "asset-secret-78",
      asset_title: "客户访谈纪要",
      scope: "project",
      cited_zone: "material",
      used_access_layer: "summary",
      is_pending_review: true,
      is_asset_zone: false,
      citation_order: 1,
      snippet: "original text must not render",
    },
  ],
  trace_id: "trace-secret-78",
  created_at: "2026-07-16T08:00:00Z",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function renderPage(path = `/project/${PROJECT_A}`) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/project/:id" element={<ProjectOverviewPage />} />
        <Route path="/" element={<div>今日工作台</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProjectOverviewPage project assistant workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchProjects.mockResolvedValue({ items: projects });
    api.fetchProjectOverview.mockImplementation(async (projectId: string) => overview(projectId));
    api.fetchProjectQaModelOptions.mockResolvedValue(modelOptions);
    api.projectQa.mockResolvedValue(qaAnswer);
  });

  it("uses the strict context-and-assistant skeleton for an ordinary member", async () => {
    const { container } = renderPage();

    expect(await screen.findByRole("heading", { name: "华东增长项目" })).toBeInTheDocument();
    expect(screen.getByRole("main", { name: "项目 AI 助手" })).toBeInTheDocument();
    expect(screen.getByText("可以围绕“华东增长项目”的项目知识提问。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "项目知识库" })).toHaveAttribute(
      "href",
      `/project/${PROJECT_A}/knowledge`,
    );
    const modelSelect = await screen.findByRole("combobox", { name: "问答模型" });
    expect(modelSelect).toHaveValue("qa-default-secret");
    expect(screen.getByRole("textbox", { name: "向项目 AI 助手提问" })).toBeEnabled();
    expect(container.querySelector(".project78-context")).toBeInTheDocument();
    expect(container.querySelector(".project78-assistant")).toBeInTheDocument();
    expect(container.querySelector(".project78-composer")).toBeInTheDocument();
    expect(container.querySelector(".project78-counts")).not.toBeInTheDocument();
    expect(container.querySelector(".project78-members")).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/route_A|诊断|consultant/);
  });

  it("shows real members and the real review action only for manager capabilities", async () => {
    api.fetchProjectOverview.mockResolvedValue(
      overview(PROJECT_B, {
        capabilities: {
          can_view_knowledge: true,
          can_upload_material: true,
          can_manage_members: true,
          can_manage_kb: false,
          can_confirm_assets: true,
        },
        members: [
          {
            user_id: "member-hidden-id",
            name: "周项目经理",
            project_role: "project_manager",
            status: "active",
          },
        ],
      }),
    );
    renderPage(`/project/${PROJECT_B}`);

    expect(await screen.findByText("周项目经理")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "处理待审核（2）" })).toHaveAttribute(
      "href",
      `/project/${PROJECT_B}/settings`,
    );
    expect(screen.getByRole("link", { name: "项目设置" })).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("member-hidden-id");
  });

  it("keeps pending confirmation as context without creating a processing action", async () => {
    api.fetchProjectOverview.mockResolvedValue(
      overview(PROJECT_B, {
        capabilities: {
          can_view_knowledge: true,
          can_upload_material: true,
          can_manage_members: true,
          can_manage_kb: false,
          can_confirm_assets: true,
        },
        counts: {
          material_count: 12,
          asset_count: 7,
          pending_confirmation_count: 3,
          pending_review_count: 0,
          original_access_request_count: 1,
        },
      }),
    );
    renderPage(`/project/${PROJECT_B}`);

    expect(await screen.findByRole("heading", { name: "项目 AI 助手" })).toBeInTheDocument();
    expect(screen.getByText("待确认").nextElementSibling).toHaveTextContent("3");
    expect(screen.queryByText(/处理待确认|处理待审核/)).not.toBeInTheDocument();
  });

  it("renders only the safe QA answer and citation fields", async () => {
    renderPage();
    const input = await screen.findByRole("textbox", { name: "向项目 AI 助手提问" });
    fireEvent.change(input, { target: { value: "客户当前最关注什么？" } });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));

    expect(await screen.findByText(qaAnswer.response_text)).toBeInTheDocument();
    expect(screen.getByText("客户当前最关注什么？")).toBeInTheDocument();
    expect(screen.getByText("客户访谈纪要")).toBeInTheDocument();
    expect(screen.getByText("资料区")).toBeInTheDocument();
    expect(screen.getByText("内容待审核，请谨慎参考")).toBeInTheDocument();
    expect(api.projectQa).toHaveBeenCalledWith(PROJECT_A, {
      query: "客户当前最关注什么？",
      modelRef: "qa-default-secret",
    });
    expect(document.body).not.toHaveTextContent(
      /call-secret-78|trace-secret-78|qa-default-secret|allowed|asset-secret-78|summary|original text/,
    );
  });

  it("disables asking for empty input, no models and while a request is in flight", async () => {
    const pending = deferred<typeof qaAnswer>();
    api.projectQa.mockReturnValue(pending.promise);
    const first = renderPage();
    const input = await screen.findByRole("textbox", { name: "向项目 AI 助手提问" });
    expect(screen.getByRole("button", { name: "提问" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "请总结项目风险" } });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));
    expect(screen.getByRole("button", { name: "提问中" })).toBeDisabled();
    expect(input).toBeDisabled();
    pending.resolve(qaAnswer);
    expect(await screen.findByText(qaAnswer.response_text)).toBeInTheDocument();
    first.unmount();

    api.fetchProjectQaModelOptions.mockResolvedValue({ items: [], total: 0 });
    renderPage();
    expect(await screen.findByText("当前项目暂无可用问答模型")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "向项目 AI 助手提问" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "提问" })).toBeDisabled();
  });

  it("recovers from model loading and QA failures without exposing upstream errors", async () => {
    api.fetchProjectQaModelOptions
      .mockRejectedValueOnce(new Error("provider endpoint secret"))
      .mockResolvedValueOnce(modelOptions);
    const first = renderPage();
    expect(await screen.findByText("问答模型暂时不可用")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("provider endpoint secret");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByRole("option", { name: "项目默认问答模型" })).toBeInTheDocument();
    first.unmount();

    api.projectQa
      .mockRejectedValueOnce(new Error("upstream trace secret"))
      .mockResolvedValueOnce(qaAnswer);
    renderPage();
    const input = await screen.findByRole("textbox", { name: "向项目 AI 助手提问" });
    fireEvent.change(input, { target: { value: "项目风险是什么？" } });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));
    expect(await screen.findByText("暂时无法完成回答，请稍后重试。")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("upstream trace secret");
    fireEvent.click(screen.getByRole("button", { name: "重新提问" }));
    expect(await screen.findByText(qaAnswer.response_text)).toBeInTheDocument();
  });

  it("unmounts the old project conversation and ignores its late answer on switch", async () => {
    const lateAnswer = deferred<typeof qaAnswer>();
    api.projectQa.mockReturnValue(lateAnswer.promise);
    renderPage();
    const input = await screen.findByRole("textbox", { name: "向项目 AI 助手提问" });
    fireEvent.change(input, { target: { value: "项目 A 的风险？" } });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));
    expect(screen.getByText("项目 A 的风险？")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("切换项目"), { target: { value: PROJECT_B } });
    expect(await screen.findByRole("heading", { name: "年度辅导项目" })).toBeInTheDocument();
    expect(screen.queryByText("项目 A 的风险？")).not.toBeInTheDocument();
    expect(screen.getByText("可以围绕“年度辅导项目”的项目知识提问。")).toBeInTheDocument();
    lateAnswer.resolve(qaAnswer);

    await waitFor(() => expect(screen.queryByText(qaAnswer.response_text)).not.toBeInTheDocument());
    expect(api.fetchProjectQaModelOptions).toHaveBeenLastCalledWith(PROJECT_B);
  });

  it("keeps project list, inaccessible and overview failures separate and retryable", async () => {
    api.fetchProjects.mockResolvedValueOnce({ items: [] });
    const empty = renderPage();
    expect(await screen.findByText("暂无可访问项目")).toBeInTheDocument();
    expect(api.fetchProjectOverview).not.toHaveBeenCalled();
    empty.unmount();

    api.fetchProjects.mockResolvedValueOnce({ items: projects });
    const inaccessible = renderPage("/project/not-accessible");
    expect(await screen.findByText("项目不可访问")).toBeInTheDocument();
    expect(api.fetchProjectOverview).not.toHaveBeenCalled();
    inaccessible.unmount();

    api.fetchProjectOverview
      .mockRejectedValueOnce(new Error("internal project id secret"))
      .mockResolvedValueOnce(overview(PROJECT_A));
    renderPage();
    expect(await screen.findByText("项目概览加载失败")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("internal project id secret");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByRole("heading", { name: "项目 AI 助手" })).toBeInTheDocument();
  });
});
