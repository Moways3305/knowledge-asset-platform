import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import MaintenanceAgentPage from "./MaintenanceAgentPage";
import * as api from "../api/maintenanceAgent";
import { ApiError } from "../api/http";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ capabilities: { isGovernance: true } }),
}));
vi.mock("../api/maintenanceAgent", () => ({
  fetchAgentPolicies: vi.fn(),
  fetchAgentIssues: vi.fn(),
  fetchAgentRuns: vi.fn(),
  fetchAgentModels: vi.fn(),
  saveAgentPolicy: vi.fn(),
  startAgentRun: vi.fn(),
  fetchAgentIssue: vi.fn(),
  actOnAgentIssue: vi.fn(),
}));
const policy: api.AgentPolicy = {
  id: null,
  library_key: "company",
  name: "公司知识库",
  enabled: false,
  content_authorized: false,
  revision: 0,
  last_error: null,
  can_configure: true,
  settings: {
    model_ref: "system_default",
    daily_hour: 2,
    weekly_day: 6,
    digest_hour: 9,
    overdue_days: 7,
    required_tags: [],
    required_sections: [],
    similarity_threshold: 0.85,
    max_body_chars: 24000,
  },
};
const choices: api.AgentModelOptions = {
  default_missing: false,
  items: [
    {
      model_ref: "a".repeat(64),
      display_name: "平台通用模型",
      provider: "aliyun",
      model_name: "qwen-default",
      enabled: true,
      is_default: true,
    },
    {
      model_ref: "b".repeat(64),
      display_name: "质量审核模型",
      provider: "custom",
      model_name: "quality-model",
      enabled: true,
      is_default: false,
    },
  ],
};
const run: api.ScanRun = {
  id: "run",
  policy_id: "policy",
  kind: "full",
  status: "queued",
  target_count: 0,
  completed_count: 0,
  incomplete_count: 0,
  skipped_count: 0,
  reasons: {},
  started_at: "2026-11-16T02:00:00Z",
  finished_at: null,
};
function mount(tab = "issues") {
  return render(
    <MemoryRouter initialEntries={[`/agents/knowledge-maintenance?tab=${tab}`]}>
      <MaintenanceAgentPage />
    </MemoryRouter>,
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.fetchAgentPolicies).mockResolvedValue([structuredClone(policy)]);
  vi.mocked(api.fetchAgentIssues).mockResolvedValue({
    items: [],
    total: 0,
    page: 1,
    page_size: 25,
  });
  vi.mocked(api.fetchAgentRuns).mockResolvedValue([]);
  vi.mocked(api.fetchAgentModels).mockResolvedValue(choices);
  vi.mocked(api.startAgentRun).mockResolvedValue(run);
});

it("provides an enabled first-use action, shared refresh style, and saves the selected model before starting", async () => {
  let completeSave!: (saved: api.AgentPolicy) => void;
  vi.mocked(api.saveAgentPolicy).mockImplementation(
    () =>
      new Promise((resolve) => {
        completeSave = resolve;
      }),
  );
  mount();
  const configure = await screen.findByRole("button", { name: "配置并开始" });
  await waitFor(() => expect(configure).toBeEnabled());
  expect(screen.getByRole("button", { name: "刷新" })).toHaveClass(
    "product-button",
    "is-secondary",
  );
  fireEvent.click(configure);
  const model = await screen.findByLabelText("正文分析模型");
  fireEvent.change(model, { target: { value: "b".repeat(64) } });
  fireEvent.click(screen.getByLabelText("授权检查可访问的原始文件，并使用所选模型分析正文"));
  fireEvent.click(screen.getByRole("button", { name: "保存并开始巡检" }));
  await waitFor(() =>
    expect(api.saveAgentPolicy).toHaveBeenCalledWith(
      "company",
      expect.objectContaining({
        content_authorized: true,
        settings: expect.objectContaining({ model_ref: "b".repeat(64) }),
      }),
    ),
  );
  expect(api.startAgentRun).not.toHaveBeenCalled();
  const saved = {
    ...policy,
    id: "policy",
    revision: 1,
    content_authorized: true,
    settings: { ...policy.settings, model_ref: "b".repeat(64) },
  };
  vi.mocked(api.fetchAgentPolicies).mockResolvedValue([saved]);
  await act(async () => completeSave(saved));
  await waitFor(() => expect(api.startAgentRun).toHaveBeenCalledOnce());
  expect(api.startAgentRun).toHaveBeenCalledWith("company");
  expect(
    await screen.findByText("巡检已加入后台队列，可在巡检记录中查看进度。"),
  ).toBeInTheDocument();
});

it("explains permission restrictions beside the action without allowing a scan", async () => {
  vi.mocked(api.fetchAgentPolicies).mockResolvedValue([{ ...policy, can_configure: false }]);
  mount();
  await screen.findByText("需由公司知识治理人员或该项目经理操作");
  expect(screen.getByRole("button", { name: "配置并开始" })).toBeDisabled();
  expect(api.startAgentRun).not.toHaveBeenCalled();
});

it("keeps issue browsing available when the model catalog fails and offers a retry", async () => {
  vi.mocked(api.fetchAgentModels).mockRejectedValueOnce(new ApiError(503, "模型信息暂时不可用"));
  mount("settings");
  expect(await screen.findByText("模型信息暂时不可用")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重新读取模型" }));
  await waitFor(() => expect(api.fetchAgentModels).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByLabelText("正文分析模型")).toBeEnabled());
});

it("retains an unavailable explicit selection instead of silently selecting the default", async () => {
  vi.mocked(api.fetchAgentPolicies).mockResolvedValue([
    { ...policy, id: "policy", settings: { ...policy.settings, model_ref: "c".repeat(64) } },
  ]);
  mount("settings");
  await screen.findByRole("option", { name: "原选模型已不可用，请重新选择" });
  expect(screen.getByLabelText("正文分析模型")).toHaveValue("c".repeat(64));
});

it("opens progress for a running scan instead of submitting another run", async () => {
  vi.mocked(api.fetchAgentPolicies).mockResolvedValue([{ ...policy, id: "policy" }]);
  vi.mocked(api.fetchAgentRuns).mockResolvedValue([run]);
  mount();
  const progress = await screen.findByRole("button", { name: "查看巡检进度" });
  fireEvent.click(progress);
  await screen.findByText("等待巡检");
  expect(api.startAgentRun).not.toHaveBeenCalled();
});
