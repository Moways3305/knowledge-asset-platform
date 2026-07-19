import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchAlertNotifications, fetchAlertRules, updateAlertRule } from "../api/admin";
import { ApiError } from "../api/http";
import type { AlertRuleDTO, NotificationDTO } from "../types/alert";
import AdminAlertSettingsPage from "./AdminAlertSettingsPage";

vi.mock("../api/admin", () => ({
  fetchAlertNotifications: vi.fn(),
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
const notification: NotificationDTO = {
  id: "notification-secret",
  alert_rule_id: "rule-secret",
  audit_event_id: "audit-secret",
  recipient_user_id: "recipient-secret",
  recipient_name: "安全管理员",
  channel: "in_app",
  title: "登录失败告警",
  content: "raw content token=secret",
  send_status: "pending",
  sent_at: null,
  created_at: "2026-07-20T02:00:00Z",
};

describe("AdminAlertSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchAlertRules).mockResolvedValue({ items: [rule] });
    vi.mocked(fetchAlertNotifications).mockResolvedValue({ items: [notification] });
    vi.mocked(updateAlertRule).mockImplementation(async (_id, patch) => ({ ...rule, ...patch }));
  });

  it("renders truthful summaries and no internal notification fields", async () => {
    const { container } = render(<AdminAlertSettingsPage />);
    expect(await screen.findByText("连续登录失败")).toBeInTheDocument();
    const summary = screen.getByLabelText("告警摘要");
    expect(within(summary).getByText("启用规则")).toBeInTheDocument();
    for (const secret of [
      "rule-secret",
      "notification-secret",
      "audit-secret",
      "recipient-secret",
      "raw content",
      "token=secret",
    ])
      expect(container.innerHTML).not.toContain(secret);
  });

  it("saves threshold on blur and toggles only the selected rule", async () => {
    render(<AdminAlertSettingsPage />);
    const input = await screen.findByLabelText("连续登录失败阈值");
    fireEvent.change(input, { target: { value: "8" } });
    fireEvent.blur(input);
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
    const input = await screen.findByLabelText("连续登录失败阈值");
    fireEvent.change(input, { target: { value: "9" } });
    fireEvent.blur(input);
    expect(await screen.findByText("保存失败，请重试。")).toBeInTheDocument();
    expect(input).toHaveValue(5);
    expect(screen.getByText("登录失败告警")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("raw webhook credential");
  });

  it.each([
    ["empty", "暂无符合条件的告警规则"],
    [new ApiError(503, "raw alert token"), "告警设置暂时无法加载，请稍后重试。"],
    [new ApiError(403, "raw forbidden", "raw_reason"), "当前身份没有告警设置查看权限。"],
  ])("handles empty, failure and forbidden safely", async (result, expected) => {
    if (result === "empty") {
      vi.mocked(fetchAlertRules).mockResolvedValueOnce({ items: [] });
      vi.mocked(fetchAlertNotifications).mockResolvedValueOnce({ items: [] });
    } else {
      vi.mocked(fetchAlertRules).mockRejectedValueOnce(result);
    }
    const { container } = render(<AdminAlertSettingsPage />);
    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/raw alert token|raw forbidden|raw_reason/);
  });
});
