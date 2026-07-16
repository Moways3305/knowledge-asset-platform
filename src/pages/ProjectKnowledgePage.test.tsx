import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchKnowledgeList } from "../api/knowledge";
import { fetchProjectQaModelOptions, projectQa } from "../api/project";
import { requestCompanyUpgrade } from "../api/review";
import ProjectKnowledgePage from "./ProjectKnowledgePage";

const PROJECT_A = "00000000-0000-0000-0000-0000000000a1";
const PROJECT_B = "00000000-0000-0000-0000-0000000000b2";

const authState = {
  status: "authenticated",
  authMe: {
    userId: "user-1",
    name: "测试顾问",
    projects: [
      { projectId: PROJECT_A, projectName: "甲项目", projectRole: "consultant" },
      { projectId: PROJECT_B, projectName: "乙项目", projectRole: "project_manager" },
    ],
  },
};

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => authState,
}));

vi.mock("../api/knowledge", () => ({
  fetchKnowledgeList: vi.fn(),
}));

vi.mock("../api/project", () => ({
  fetchProjectQaModelOptions: vi.fn(),
  projectQa: vi.fn(),
}));

vi.mock("../api/review", () => ({
  requestCompanyUpgrade: vi.fn(),
}));

function HistoryControls() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output aria-label="当前路径">{location.pathname}</output>
      <button onClick={() => navigate(-1)}>后退</button>
    </>
  );
}

function renderPage(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <HistoryControls />
      <Routes>
        <Route path="/project/:id/knowledge" element={<ProjectKnowledgePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProjectKnowledgePage project context", () => {
  beforeEach(() => {
    authState.status = "authenticated";
    authState.authMe.projects = [
      { projectId: PROJECT_A, projectName: "甲项目", projectRole: "consultant" },
      { projectId: PROJECT_B, projectName: "乙项目", projectRole: "project_manager" },
    ];
    vi.mocked(fetchKnowledgeList).mockReset().mockResolvedValue([]);
    vi.mocked(fetchProjectQaModelOptions)
      .mockReset()
      .mockResolvedValue({
        items: [{ model_ref: "system_default", display_name: "系统默认模型", is_default: true }],
        total: 1,
      });
    vi.mocked(projectQa).mockReset().mockResolvedValue({
      call_id: "call-1",
      response_text: "回答",
      model_key: "system_default",
      decision_status: "allowed",
      citations: [],
      trace_id: null,
      created_at: "2026-07-14T00:00:00Z",
    });
    vi.mocked(requestCompanyUpgrade)
      .mockReset()
      .mockResolvedValue({} as never);
  });

  it("binds direct URLs and list/model requests to the exact project id", async () => {
    renderPage(`/project/${PROJECT_B}/knowledge`);

    expect(await screen.findAllByText("乙项目", { selector: "strong" })).toHaveLength(2);
    await waitFor(() => {
      expect(fetchKnowledgeList).toHaveBeenCalledWith({ scope: "project", projectId: PROJECT_B });
      expect(fetchProjectQaModelOptions).toHaveBeenCalledWith(PROJECT_B);
    });
    expect(screen.getByRole("option", { name: "系统默认模型" })).toBeInTheDocument();
    expect(screen.queryByText(/DeepSeek-R1|通义千问企业版/)).not.toBeInTheDocument();
  });

  it("switches URL, data and QA context together and follows browser history", async () => {
    renderPage(`/project/${PROJECT_A}/knowledge`);
    expect(await screen.findAllByText("甲项目", { selector: "strong" })).toHaveLength(2);

    fireEvent.change(screen.getByRole("combobox", { name: "切换项目" }), {
      target: { value: PROJECT_B },
    });
    await waitFor(() => expect(screen.getByLabelText("当前路径")).toHaveTextContent(PROJECT_B));
    await waitFor(() =>
      expect(fetchKnowledgeList).toHaveBeenLastCalledWith({
        scope: "project",
        projectId: PROJECT_B,
      }),
    );

    fireEvent.change(screen.getByPlaceholderText("输入你的问题…"), {
      target: { value: "乙项目有哪些交付物？" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提问" }));
    await waitFor(() =>
      expect(projectQa).toHaveBeenCalledWith(PROJECT_B, {
        query: "乙项目有哪些交付物？",
        modelRef: "system_default",
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "后退" }));
    await waitFor(() => expect(screen.getByLabelText("当前路径")).toHaveTextContent(PROJECT_A));
    await waitFor(() =>
      expect(fetchKnowledgeList).toHaveBeenLastCalledWith({
        scope: "project",
        projectId: PROJECT_A,
      }),
    );
  });

  it("does not fall back or load business data for an invalid project route", async () => {
    renderPage("/project/current/knowledge");

    expect(await screen.findByText("无法打开该项目")).toBeInTheDocument();
    expect(screen.getByLabelText("当前路径")).toHaveTextContent("/project/current/knowledge");
    expect(fetchKnowledgeList).not.toHaveBeenCalled();
    expect(fetchProjectQaModelOptions).not.toHaveBeenCalled();
  });

  it("shows a secure empty state without projects and disables QA without real models", async () => {
    authState.authMe.projects = [];
    const first = renderPage(`/project/${PROJECT_A}/knowledge`);
    expect(await screen.findByText("暂无可访问项目")).toBeInTheDocument();
    expect(fetchKnowledgeList).not.toHaveBeenCalled();
    first.unmount();

    authState.authMe.projects = [
      { projectId: PROJECT_A, projectName: "甲项目", projectRole: "consultant" },
    ];
    vi.mocked(fetchProjectQaModelOptions).mockResolvedValue({ items: [], total: 0 });
    renderPage(`/project/${PROJECT_A}/knowledge`);
    expect(await screen.findByText(/当前没有可用问答模型，请联系管理员/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提问" })).toBeDisabled();
  });

  it("lets only the project manager request company upgrade for a project asset", async () => {
    vi.mocked(fetchKnowledgeList).mockResolvedValue([
      {
        id: "asset-1",
        title: "可复用项目资产",
        scope: "project",
        zone: "asset",
        assetType: "case",
        confidentialityLevel: "L2",
        aiAccessLevel: "A2",
        assetStatus: "active",
        visibility: "project-only",
        tags: [],
        summary: "安全摘要",
        projectName: "乙项目",
        lifecyclePhase: "阶段评估",
        confidence: null,
        lastCalledAt: "",
        updatedAt: "",
        access: {
          discovery: true,
          summary: true,
          original: true,
          effectiveSource: "project_member",
          canRequestOriginal: false,
          existingRequestStatus: null,
          existingGrantExpiresAt: null,
          canDelete: true,
          canManageLifecycle: true,
          canRetryIndex: false,
        },
        indexStatus: "indexed",
        parseStatus: null,
        indexErrorMessage: null,
        indexedAt: null,
      },
    ]);
    renderPage(`/project/${PROJECT_B}/knowledge`);
    fireEvent.click(await screen.findByRole("button", { name: "申请升格公司资产" }));
    await waitFor(() => expect(requestCompanyUpgrade).toHaveBeenCalledWith(PROJECT_B, "asset-1"));
    expect(await screen.findByText(/等待总经理与咨询总监分别确认/)).toBeInTheDocument();
  });
});
