import { act, within, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchAlertRules, updateAlertRule } from "../api/admin";
import { ApiError } from "../api/http";
import type { AlertRuleDTO } from "../types/alert";
import AdminAlertSettingsPage from "./AdminAlertSettingsPage";

vi.mock("../api/admin", () => ({
  fetchAlertRules: vi.fn(),
  updateAlertRule: vi.fn(),
}));

const rule: AlertRuleDTO = {
  id: "rule-secret",
  rule_name: "连续登录失败",
  severity: "critical",
  threshold: 5,
  threshold_unit: "次",
  enabled: true,
  notification_channels: ["in_app"],
  dedup_strategy: "cooldown",
  updated_at: "2026-07-20T01:00:00Z",
};
describe("AdminAlertSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchAlertRules).mockResolvedValue({ items: [rule] });
    vi.mocked(updateAlertRule).mockImplementation(async (_id, patch) => ({ ...rule, ...patch }));
  });

  it("renders a focused rules workspace without a redundant notification log", async () => {
    const { container } = render(<AdminAlertSettingsPage />);
    expect(await screen.findByText("连续登录失败")).toBeInTheDocument();
    const main = container.querySelector<HTMLElement>(".secops-main-workspace");
    const sections = container.querySelectorAll<HTMLElement>(".secops-workspace");
    expect(container.querySelector(".secops-console")?.children).toHaveLength(1);
    expect(container.querySelector(".secops-summary-panel")).not.toBeInTheDocument();
    expect(main).toContainElement(sections[0]);
    expect(sections).toHaveLength(1);
    expect(screen.queryByText("通知记录")).not.toBeInTheDocument();
    for (const secret of ["rule-secret"]) expect(container.innerHTML).not.toContain(secret);
  });

  it("saves thresholds only on explicit save and toggles only the selected rule", async () => {
    render(<AdminAlertSettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "编辑连续登录失败阈值" }));
    const input = screen.getByLabelText("连续登录失败阈值");
    fireEvent.change(input, { target: { value: "8" } });
    fireEvent.blur(input);
    expect(updateAlertRule).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "保存阈值" }));
    await waitFor(() =>
      expect(updateAlertRule).toHaveBeenCalledWith("rule-secret", { threshold: 8 }),
    );
    fireEvent.click(screen.getByRole("button", { name: "连续登录失败停用" }));
    await waitFor(() =>
      expect(updateAlertRule).toHaveBeenCalledWith("rule-secret", { enabled: false }),
    );
  });

  it("recovers the edited row after a safe update failure", async () => {
    vi.mocked(updateAlertRule).mockRejectedValueOnce(new ApiError(500, "raw webhook credential"));
    render(<AdminAlertSettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "编辑连续登录失败阈值" }));
    const input = screen.getByLabelText("连续登录失败阈值");
    fireEvent.change(input, { target: { value: "9" } });
    fireEvent.blur(input);
    expect(updateAlertRule).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "保存阈值" }));
    expect(await screen.findByText("保存失败，请重试。")).toBeInTheDocument();
    expect(input).toHaveValue(5);
    expect(document.body.innerHTML).not.toContain("raw webhook credential");
  });

  it.each([
    { threshold: 5, unit: "versions" },
    { threshold: 120, unit: "minutes" },
    { threshold: 360, unit: "minutes" },
  ])(
    "cancels an edited $threshold $unit threshold without writing or toggling it",
    async ({ threshold, unit }) => {
      vi.mocked(fetchAlertRules).mockResolvedValue({
        items: [{ ...rule, threshold, threshold_unit: unit }],
      });
      render(<AdminAlertSettingsPage />);
      fireEvent.click(await screen.findByRole("button", { name: "编辑连续登录失败阈值" }));
      const actions = screen.getByRole("group", { name: "连续登录失败阈值操作" });
      const status = screen.getByRole("button", { name: "连续登录失败停用" });
      expect(status).toBeDisabled();
      expect(actions).not.toContainElement(status);
      fireEvent.change(screen.getByLabelText("连续登录失败阈值"), { target: { value: "11" } });
      fireEvent.click(within(actions).getByRole("button", { name: "取消" }));
      expect(updateAlertRule).not.toHaveBeenCalled();
      expect(screen.queryByLabelText("连续登录失败阈值")).not.toBeInTheDocument();
      expect(status).toBeEnabled();
      expect(screen.getByText(unit)).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "编辑连续登录失败阈值" }));
      expect(screen.getByLabelText("连续登录失败阈值")).toHaveValue(threshold);
    },
  );

  it("keeps another row's draft when an earlier save resolves", async () => {
    const other = { ...rule, id: "second-rule", rule_name: "上传失败", threshold: 3 };
    vi.mocked(fetchAlertRules).mockResolvedValue({ items: [rule, other] });
    let finish!: (value: AlertRuleDTO) => void;
    vi.mocked(updateAlertRule).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(<AdminAlertSettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "编辑连续登录失败阈值" }));
    const firstInput = screen.getByLabelText("连续登录失败阈值");
    fireEvent.change(firstInput, { target: { value: "8" } });
    fireEvent.click(within(firstInput.closest("tr")!).getByRole("button", { name: "保存阈值" }));
    fireEvent.click(screen.getByRole("button", { name: "编辑上传失败阈值" }));
    const otherInput = screen.getByLabelText("上传失败阈值");
    fireEvent.change(otherInput, { target: { value: "9" } });
    await act(async () => finish({ ...rule, threshold: 8 }));
    expect(screen.getByLabelText("上传失败阈值")).toHaveValue(9);
    expect(screen.queryByLabelText("连续登录失败阈值")).not.toBeInTheDocument();
    expect(updateAlertRule).toHaveBeenCalledTimes(1);
    fireEvent.click(within(otherInput.closest("tr")!).getByRole("button", { name: "保存阈值" }));
    await waitFor(() =>
      expect(updateAlertRule).toHaveBeenLastCalledWith("second-rule", { threshold: 9 }),
    );
  });

  it.each([
    ["empty", "暂无符合条件的告警规则"],
    [new ApiError(503, "raw alert token"), "告警设置暂时无法加载，请稍后重试。"],
    [new ApiError(403, "raw forbidden", "raw_reason"), "当前身份没有告警设置查看权限。"],
  ])("handles empty, failure and forbidden safely", async (result, expected) => {
    if (result === "empty") {
      vi.mocked(fetchAlertRules).mockResolvedValueOnce({ items: [] });
    } else {
      vi.mocked(fetchAlertRules).mockRejectedValueOnce(result);
    }
    const { container } = render(<AdminAlertSettingsPage />);
    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/raw alert token|raw forbidden|raw_reason/);
  });
});
