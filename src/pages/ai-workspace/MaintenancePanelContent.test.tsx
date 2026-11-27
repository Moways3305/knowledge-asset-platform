import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import MaintenancePanelContent, { type MaintenancePolicyDraft } from "./MaintenancePanelContent";
import * as api from "../../api/maintenanceAgent";
import { ApiError } from "../../api/http";

vi.mock("../../auth/AuthContext", () => ({
  useAuth: () => ({ capabilities: { isGovernance: true } }),
}));
vi.mock("../../api/maintenanceAgent", () => ({
  cancelAgentRun: vi.fn(),
  retryAgentRun: vi.fn(),
  deleteAgentRun: vi.fn(),
  deleteAgentRuns: vi.fn(),
  fetchAgentPolicies: vi.fn(),
  fetchAgentIssues: vi.fn(),
  fetchAgentRuns: vi.fn(),
  fetchAgentRun: vi.fn(),
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
function mount(
  tab = "issues",
  onDirtyChange?: (dirty: boolean) => void,
  draftCache?: Map<string, MaintenancePolicyDraft>,
) {
  let navigatePanel!: (panel: string) => void;
  function PanelFixture() {
    const [params, setParams] = useSearchParams();
    const onNavigate = (changes: Record<string, string | null>) => {
      const next = new URLSearchParams(params);
      Object.entries(changes).forEach(([key, value]) =>
        value === null ? next.delete(key) : next.set(key, value),
      );
      setParams(next);
    };
    navigatePanel = (panel) => onNavigate({ panel, tab: null });
    return (
      <>
        <output aria-label="当前面板参数">{params.toString()}</output>
        <MaintenancePanelContent
          onNavigate={onNavigate}
          onDirtyChange={onDirtyChange}
          draftCache={draftCache}
        />
      </>
    );
  }
  const result = render(
    <MemoryRouter initialEntries={[`/ai-workspace?tab=${tab}`]}>
      <PanelFixture />
    </MemoryRouter>,
  );
  return { ...result, navigatePanel: (panel: string) => act(() => navigatePanel(panel)) };
}

it.each(["target_id", "digest_id"])(
  "opens a %s reminder in its project library and keeps multi-library filtering scoped to that reminder",
  async (parameter) => {
    const project = { ...policy, library_key: "project:alpha", name: "交付项目库" };
    vi.mocked(api.fetchAgentPolicies).mockResolvedValue([policy, project]);
    const result = {
      items: [],
      total: 0,
      page: 1,
      page_size: 25,
      digest_libraries: [project.library_key],
    };
    vi.mocked(api.fetchAgentIssues).mockResolvedValue(result);
    mount(`issues&${parameter}=day-one&mine=true`);
    const select = await screen.findByRole("combobox", { name: "本次提醒的知识库" });
    await waitFor(() => expect(select).toHaveValue(project.library_key));
    let query = vi.mocked(api.fetchAgentIssues).mock.lastCall![0];
    expect(query.get("digest_id")).toBe("day-one");
    expect(query.has("library_key")).toBe(false);
    expect(screen.getByRole("button", { name: "查看该知识库全部待办" })).toBeEnabled();
    expect(api.fetchAgentRuns).not.toHaveBeenCalled();
    vi.mocked(api.fetchAgentIssues).mockResolvedValue({
      ...result,
      digest_libraries: ["company", project.library_key],
    });
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(select).toHaveValue(""));
    fireEvent.change(select, { target: { value: project.library_key } });
    await waitFor(() =>
      expect(vi.mocked(api.fetchAgentIssues).mock.lastCall![0].get("library_key")).toBe(
        project.library_key,
      ),
    );
    query = vi.mocked(api.fetchAgentIssues).mock.lastCall![0];
    expect(query.get("mine")).toBe("true");
    expect(query.get("digest_id")).toBe("day-one");
    fireEvent.click(screen.getByRole("button", { name: "查看该知识库全部待办" }));
    await waitFor(() => {
      const all = vi.mocked(api.fetchAgentIssues).mock.lastCall![0];
      expect(all.get("library_key")).toBe(project.library_key);
      expect(all.has("digest_id")).toBe(false);
      expect(all.get("mine")).toBe("false");
    });
    expect(screen.getByLabelText("当前面板参数")).not.toHaveTextContent(/target_id=|digest_id=/);
  },
);

it("shows privacy findings as counts and locations with a dedicated category", async () => {
  const item: api.MaintenanceIssue = {
    id: "privacy-issue",
    asset_id: "asset",
    title: "验收资料",
    library_key: "company",
    rule: "personal_information",
    category: "privacy",
    status: "open",
    suspected: true,
    first_seen_at: run.started_at,
    last_seen_at: run.started_at,
    updated_at: run.started_at,
    snooze_until: null,
    responsible: [],
    can_act: true,
  };
  vi.mocked(api.fetchAgentIssues).mockResolvedValue({
    items: [item],
    total: 1,
    page: 1,
    page_size: 25,
  });
  vi.mocked(api.fetchAgentIssue).mockResolvedValue({
    ...item,
    evidence_available: true,
    current_version_matches: true,
    history: [],
    evidence: {
      basis: "local_personal_information_check",
      counts: { phone: 1 },
      total: 1,
      locations: [{ source: "body", category: "phone", start: 5996, end: 6007 }],
    },
  });
  mount();
  expect(await screen.findByRole("option", { name: "敏感个人信息" })).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "疑似包含敏感个人信息" }));
  expect(await screen.findByRole("region", { name: "个人信息检查结果" })).toHaveTextContent(
    "电话：1 处",
  );
  expect(screen.getByRole("region", { name: "个人信息检查结果" })).toHaveTextContent(
    "第 5997—6007 字符",
  );
});

it("keeps replaced-version problems open for recheck and clears detail when access is revoked", async () => {
  const issue: api.IssueDetail = {
    id: "followed-issue",
    asset_id: "asset",
    title: "换版后的资料",
    library_key: "company",
    rule: "summary_mismatch",
    category: "quality",
    status: "open",
    suspected: true,
    first_seen_at: run.started_at,
    last_seen_at: run.started_at,
    updated_at: run.started_at,
    snooze_until: null,
    responsible: [],
    can_act: true,
    evidence_available: true,
    current_version_matches: false,
    requires_recheck: true,
    evidence: {},
    history: [],
  };
  vi.mocked(api.fetchAgentIssues).mockResolvedValue({
    items: [issue],
    total: 1,
    page: 1,
    page_size: 25,
  });
  vi.mocked(api.fetchAgentIssue).mockResolvedValue(issue);
  vi.mocked(api.actOnAgentIssue).mockResolvedValue({ ...issue, status: "awaiting_recheck" });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "摘要与正文可能不符" }));
  await screen.findByText("此问题已随资料换版继续跟踪，复检通过后自动关闭。");
  expect(screen.queryByRole("option", { name: "人工确认已解决" })).not.toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "标记误报" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("处理方式"), { target: { value: "recheck" } });
  fireEvent.click(screen.getByRole("button", { name: "提交处理" }));
  await waitFor(() =>
    expect(api.actOnAgentIssue).toHaveBeenCalledWith(issue.id, {
      action: "recheck",
      expected_updated_at: issue.updated_at,
      reason: "",
    }),
  );
  vi.mocked(api.fetchAgentIssues).mockRejectedValueOnce(new ApiError(403, "知识库不可访问"));
  await waitFor(() => expect(screen.getByRole("button", { name: "刷新" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "刷新" }));
  await screen.findByText("知识库不可访问");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByText("换版后的资料")).not.toBeInTheDocument();
});
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
  vi.mocked(api.fetchAgentRun).mockResolvedValue({
    ...run,
    library_key: "company",
    historical_details_available: false,
    scope_snapshot: null,
    current_scope: {
      assessed_at: run.started_at,
      visible_count: 0,
      target_count: 0,
      excluded_counts: {},
    },
    content_authorized: null,
    settings: null,
    items: [],
    total: 0,
    page: 1,
    page_size: 25,
  });
  vi.mocked(api.fetchAgentModels).mockResolvedValue(choices);
  vi.mocked(api.startAgentRun).mockResolvedValue(run);
});

it("uses the requested panel without rendering the retired page header or navigation tabs", async () => {
  mount("issues&panel=settings");
  await screen.findByLabelText("正文分析模型");
  expect(screen.queryByRole("region", { name: "巡检问题" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "巡检与跟进" })).not.toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "知识维护视图" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "立即全面巡检" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "任务会话" })).not.toBeInTheDocument();
  expect(
    screen.queryByText("定期检查知识资产，记录问题并提醒相应维护人。"),
  ).not.toBeInTheDocument();
});

it.each(["target_id=notice", "digest_id=notice", "asset_id=asset", "view=mine"])(
  "keeps the %s deep link on issues despite a stale settings panel parameter",
  async (query) => {
    mount(`settings&panel=settings&${query}`);
    await screen.findByRole("region", { name: "巡检问题" });
    expect(screen.queryByLabelText("正文分析模型")).not.toBeInTheDocument();
  },
);

it("reports unsaved configuration without resetting edits on a background refresh and clears it after saving", async () => {
  const dirty = vi.fn();
  const panel = mount("settings", dirty);
  const hour = await screen.findByLabelText("每日增量巡检（北京时间）");
  expect(dirty).toHaveBeenLastCalledWith(false);
  fireEvent.change(hour, { target: { value: "4" } });
  expect(dirty).toHaveBeenLastCalledWith(true);
  vi.mocked(api.fetchAgentPolicies).mockResolvedValue([{ ...policy, revision: 99 }]);
  fireEvent.click(screen.getByRole("button", { name: "刷新" }));
  await waitFor(() => expect(api.fetchAgentPolicies).toHaveBeenCalledTimes(2));
  expect(hour).toHaveValue("4");
  expect(dirty).toHaveBeenLastCalledWith(true);
  const saved = { ...policy, revision: 100, settings: { ...policy.settings, daily_hour: 4 } };
  vi.mocked(api.saveAgentPolicy).mockResolvedValue(saved);
  vi.mocked(api.fetchAgentPolicies).mockResolvedValue([saved]);
  fireEvent.click(screen.getByRole("button", { name: "保存巡检设置" }));
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
  expect(api.saveAgentPolicy).toHaveBeenCalledWith(
    "company",
    expect.objectContaining({ settings: expect.objectContaining({ daily_hour: 4 }) }),
  );
  expect(api.startAgentRun).not.toHaveBeenCalled();
  panel.unmount();
  expect(dirty).toHaveBeenLastCalledWith(false);
});

it("saves the selected model and authorization before starting from the configuration panel", async () => {
  let completeSave!: (saved: api.AgentPolicy) => void;
  vi.mocked(api.saveAgentPolicy).mockImplementation(
    () =>
      new Promise((resolve) => {
        completeSave = resolve;
      }),
  );
  mount("settings");
  expect(screen.queryByRole("button", { name: "立即全面巡检" })).not.toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "知识维护视图" })).not.toBeInTheDocument();
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

it("keeps configuration read-only when the current identity cannot manage the library", async () => {
  vi.mocked(api.fetchAgentPolicies).mockResolvedValue([{ ...policy, can_configure: false }]);
  mount("settings");
  await screen.findByText("请由公司知识治理人员或该项目经理配置巡检。");
  expect(screen.getByRole("button", { name: "保存并开始巡检" })).toBeDisabled();
  expect(screen.getByLabelText("正文分析模型")).toBeDisabled();
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

it("shows a running scan without a second standalone start action", async () => {
  vi.mocked(api.fetchAgentPolicies).mockResolvedValue([{ ...policy, id: "policy" }]);
  vi.mocked(api.fetchAgentRuns).mockResolvedValue([run]);
  mount("runs");
  await screen.findByText("等待巡检");
  expect(screen.queryByRole("button", { name: "立即全面巡检" })).not.toBeInTheDocument();
  expect(api.startAgentRun).not.toHaveBeenCalled();
});

it("opens zero-target legacy history and distinguishes today's scope from missing history", async () => {
  vi.mocked(api.fetchAgentRuns).mockResolvedValue([{ ...run, status: "completed" }]);
  mount("runs");
  await screen.findByText("无检查对象");
  fireEvent.click(screen.getByRole("button", { name: "查看巡检详情" }));
  await screen.findByRole("dialog", { name: "巡检详情" });
  expect(await screen.findByText(/这是一条旧版巡检记录/)).toBeInTheDocument();
  expect(screen.getByText(/实时核对，不能用于还原历史扫描范围/)).toBeInTheDocument();
  expect(api.fetchAgentRun).toHaveBeenCalledWith("company", "run", 1, "");
});

it("shows per-category reasons, finding names and a server-filtered result page", async () => {
  vi.mocked(api.fetchAgentRuns).mockResolvedValue([{ ...run, status: "partial", target_count: 1 }]);
  const scope = {
    assessed_at: run.started_at,
    visible_count: 2,
    target_count: 1,
    excluded_counts: { archived: 1 },
  };
  vi.mocked(api.fetchAgentRun).mockResolvedValue({
    ...run,
    status: "partial",
    target_count: 1,
    library_key: "company",
    historical_details_available: true,
    scope_snapshot: scope,
    current_scope: scope,
    content_authorized: true,
    settings: policy.settings,
    items: [
      {
        asset_id: "asset",
        title: "待核对资料",
        status: "incomplete",
        version_id: "old",
        current_version_matches: false,
        coverage: { integrity: "complete", quality: "model_unavailable" },
        findings: { missing_summary: 1 },
        reasons: ["model_unavailable"],
        checked_at: run.started_at,
      },
    ],
    total: 1,
    page: 1,
    page_size: 25,
  });
  mount("runs");
  fireEvent.click(await screen.findByRole("button", { name: "查看巡检详情" }));
  expect(await screen.findByRole("link", { name: /待核对资料/ })).toHaveAttribute(
    "href",
    "/knowledge/asset",
  );
  expect(screen.getByText("缺少摘要")).toBeInTheDocument();
  expect(screen.getAllByText("模型调用失败，请重试或检查模型连接").length).toBeGreaterThan(0);
  expect(screen.getByText(/当前版本已变化/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("检查结果筛选"), { target: { value: "incomplete" } });
  await waitFor(() =>
    expect(api.fetchAgentRun).toHaveBeenCalledWith("company", "run", 1, "incomplete"),
  );
});

it("clears detail data when access is lost during refresh", async () => {
  vi.mocked(api.fetchAgentRuns).mockResolvedValue([run]);
  mount("runs");
  fireEvent.click(await screen.findByRole("button", { name: "查看巡检详情" }));
  await screen.findByText(/这是一条旧版巡检记录/);
  vi.mocked(api.fetchAgentRun).mockRejectedValueOnce(new ApiError(404, "巡检记录不可访问"));
  fireEvent.click(screen.getByRole("button", { name: "刷新详情" }));
  expect(await screen.findByText("巡检记录不可访问")).toBeInTheDocument();
  expect(screen.queryByText(/这是一条旧版巡检记录/)).not.toBeInTheDocument();
});

it("polls in place through completion without unmounting history, detail or expanded content", async () => {
  const timers: Array<() => void> = [];
  const timer = vi.spyOn(window, "setInterval").mockImplementation((callback) => {
    timers.push(callback as () => void);
    return 123;
  });
  try {
    vi.mocked(api.fetchAgentRuns).mockResolvedValue([run]);
    mount("runs");
    const historyButton = await screen.findByRole("button", { name: "查看巡检详情" });
    fireEvent.click(historyButton);
    const summary = await screen.findByText("核对当前知识库范围");
    const expanded = summary.closest("details")!;
    expanded.open = true;
    const drawer = screen.getByRole("dialog", { name: "巡检详情" });
    drawer.scrollTop = 240;
    summary.focus();
    const previous = await vi.mocked(api.fetchAgentRun).mock.results[0].value;
    let finishDetail!: (value: api.ScanRunDetail) => void;
    let finishHistory!: (value: api.ScanRun[]) => void;
    vi.mocked(api.fetchAgentRun).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishDetail = resolve;
        }),
    );
    vi.mocked(api.fetchAgentRuns).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishHistory = resolve;
        }),
    );
    await act(async () => {
      timers.splice(0).forEach((callback) => callback());
    });
    expect(historyButton.isConnected).toBe(true);
    expect(expanded.isConnected).toBe(true);
    expect(expanded.open).toBe(true);
    expect(drawer.scrollTop).toBe(240);
    await act(async () => {
      finishHistory([{ ...run, status: "completed" }]);
      finishDetail({ ...previous, status: "completed" });
    });
    expect(screen.getByRole("button", { name: "查看巡检详情" })).toBe(historyButton);
    expect(screen.getByText("核对当前知识库范围").closest("details")).toBe(expanded);
    expect(expanded.open).toBe(true);
    expect(drawer.scrollTop).toBe(240);
    expect(api.fetchAgentModels).toHaveBeenCalledTimes(1);
  } finally {
    timer.mockRestore();
  }
});

it("keeps detail on transient refresh failure and keeps unsaved settings across policy updates", async () => {
  vi.mocked(api.fetchAgentRuns).mockResolvedValue([run]);
  const panel = mount("runs");
  fireEvent.click(await screen.findByRole("button", { name: "查看巡检详情" }));
  const content = await screen.findByText(/这是一条旧版巡检记录/);
  vi.mocked(api.fetchAgentRun).mockRejectedValueOnce(new ApiError(503, "暂时无法更新"));
  fireEvent.click(screen.getByRole("button", { name: "刷新详情" }));
  await screen.findByText("暂时无法更新");
  expect(content.isConnected).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "关闭详情" }));
  panel.navigatePanel("settings");
  const hour = await screen.findByLabelText("每日增量巡检（北京时间）");
  fireEvent.change(hour, { target: { value: "4" } });
  vi.mocked(api.fetchAgentPolicies).mockResolvedValue([{ ...policy, revision: 99 }]);
  fireEvent.click(screen.getByRole("button", { name: "刷新" }));
  await waitFor(() => expect(api.fetchAgentPolicies).toHaveBeenCalledTimes(3));
  expect(screen.getByLabelText("每日增量巡检（北京时间）")).toBe(hour);
  expect(hour).toHaveValue("4");
});

it("restores a configuration draft after panel unmount and keeps its original revision for conflict checks", async () => {
  const cache = new Map<string, MaintenancePolicyDraft>();
  const dirty = vi.fn();
  const first = mount("settings", dirty, cache);
  const tags = await screen.findByLabelText("必要标签（逗号分隔）");
  fireEvent.change(tags, { target: { value: "交付规范，待确认" } });
  fireEvent.change(screen.getByLabelText("每日增量巡检（北京时间）"), {
    target: { value: "4" },
  });
  expect(cache.get("company")?.expectedRevision).toBe(0);
  expect(dirty).toHaveBeenLastCalledWith(true);
  first.unmount();
  expect(cache.get("company")?.tags).toBe("交付规范，待确认");
  vi.mocked(api.fetchAgentPolicies).mockResolvedValue([{ ...policy, revision: 99 }]);
  mount("settings", dirty, cache);
  expect(await screen.findByLabelText("必要标签（逗号分隔）")).toHaveValue("交付规范，待确认");
  expect(screen.getByLabelText("每日增量巡检（北京时间）")).toHaveValue("4");
  expect(dirty).toHaveBeenLastCalledWith(true);
  vi.mocked(api.saveAgentPolicy).mockRejectedValueOnce(new ApiError(409, "配置已更新，请核对"));
  fireEvent.click(screen.getByRole("button", { name: "保存巡检设置" }));
  await screen.findByText("配置已更新，请核对");
  expect(api.saveAgentPolicy).toHaveBeenLastCalledWith(
    "company",
    expect.objectContaining({
      expected_revision: 0,
      settings: expect.objectContaining({ daily_hour: 4, required_tags: ["交付规范", "待确认"] }),
    }),
  );
  expect(cache.has("company")).toBe(true);
  vi.mocked(api.saveAgentPolicy).mockResolvedValueOnce({
    ...policy,
    revision: 100,
    settings: { ...policy.settings, daily_hour: 4, required_tags: ["交付规范", "待确认"] },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存巡检设置" }));
  await screen.findByText("巡检设置已保存。");
  expect(cache.has("company")).toBe(false);
  expect(dirty).toHaveBeenLastCalledWith(false);
});

it("does not discard a newer restored draft when an old unmounted editor finishes saving", async () => {
  const cache = new Map<string, MaintenancePolicyDraft>();
  let finishSave!: (saved: api.AgentPolicy) => void;
  vi.mocked(api.saveAgentPolicy).mockImplementationOnce(
    () => new Promise((resolve) => (finishSave = resolve)),
  );
  const first = mount("settings", undefined, cache);
  fireEvent.change(await screen.findByLabelText("必要标签（逗号分隔）"), {
    target: { value: "第一次编辑" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存巡检设置" }));
  first.unmount();
  mount("settings", undefined, cache);
  const input = await screen.findByLabelText("必要标签（逗号分隔）");
  fireEvent.change(input, { target: { value: "继续编辑的新草稿" } });
  await act(async () => finishSave({ ...policy, revision: 1 }));
  expect(input).toHaveValue("继续编辑的新草稿");
  expect(cache.get("company")?.tags).toBe("继续编辑的新草稿");
  expect(cache.get("company")?.expectedRevision).toBe(0);
  expect(screen.queryByText("巡检设置已保存。")).not.toBeInTheDocument();
});

it("offers cancellation for active runs and confirmed deletion for terminal history", async () => {
  vi.mocked(api.fetchAgentRuns).mockResolvedValue([run]);
  vi.mocked(api.cancelAgentRun).mockResolvedValue({ ...run, status: "cancelled" });
  mount("runs");
  fireEvent.click(await screen.findByRole("button", { name: "取消巡检" }));
  expect(screen.queryByRole("button", { name: "确认删除记录" })).not.toBeInTheDocument();
  vi.mocked(api.fetchAgentRuns).mockResolvedValue([
    { ...run, status: "cancelled", can_retry: true },
  ]);
  fireEvent.click(screen.getByRole("button", { name: "确认取消巡检" }));
  await screen.findByRole("button", { name: "重试未完成项" });
  fireEvent.click(screen.getByRole("button", { name: "删除" }));
  expect(screen.getByText(/知识资料、维护待办和巡检设置保留/)).toBeInTheDocument();
  vi.mocked(api.deleteAgentRun).mockRejectedValueOnce(new ApiError(409, "记录状态已变化"));
  fireEvent.click(screen.getByRole("button", { name: "确认删除记录" }));
  await screen.findByText("记录状态已变化");
  expect(screen.getByRole("dialog", { name: "删除巡检记录？" })).toBeInTheDocument();
  vi.mocked(api.deleteAgentRun).mockResolvedValueOnce({ deleted_count: 1 });
  vi.mocked(api.fetchAgentRuns).mockResolvedValue([]);
  fireEvent.click(screen.getByRole("button", { name: "确认删除记录" }));
  await screen.findByText("尚无可查看的巡检记录");
});
