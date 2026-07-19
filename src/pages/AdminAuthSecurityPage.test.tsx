import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchAuthSecurityOverview, unlockAuthLockout } from "../api/admin";
import { ApiError } from "../api/http";
import type { AuthSecurityOverviewDTO } from "../types/authSecurity";
import AdminAuthSecurityPage from "./AdminAuthSecurityPage";

vi.mock("../api/admin", () => ({ fetchAuthSecurityOverview: vi.fn(), unlockAuthLockout: vi.fn() }));

const overview: AuthSecurityOverviewDTO = {
  window_minutes: 60,
  counts: {
    failed: 2,
    locked: 1,
    rate_limited: 0,
    success: 5,
    unlocked: 1,
    unique_identifier_count: 3,
    unique_ip_count: 4,
  },
  recent_events: [
    {
      attempt_id: "attempt-secret",
      identifier_hash_prefix: "identifier-secret",
      ip_hash_prefix: "ip-secret",
      user_id: "user-secret",
      user_name: "李顾问",
      user_status: "active",
      login_method: "password_secret",
      result: "locked",
      reason_code: "identifier_locked",
      created_at: "2026-07-20T01:00:00Z",
    },
    {
      attempt_id: "success-secret",
      identifier_hash_prefix: null,
      ip_hash_prefix: null,
      user_id: null,
      user_name: "王经理",
      user_status: "active",
      login_method: "oauth_secret",
      result: "success",
      reason_code: "success",
      created_at: "2026-07-20T02:00:00Z",
    },
  ],
};

describe("AdminAuthSecurityPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchAuthSecurityOverview).mockResolvedValue(overview);
    vi.mocked(unlockAuthLockout).mockResolvedValue({
      ok: true,
      unlocked: true,
      user_id: "user-secret",
      identifier_hash_prefix: null,
      reset_at: "2026-07-20T03:00:00Z",
    });
  });

  it("renders counts and safe attempts without identifiers", async () => {
    const { container } = render(<AdminAuthSecurityPage />);
    expect(await screen.findByText("李顾问")).toBeInTheDocument();
    expect(screen.getByText("账号短时锁定")).toBeInTheDocument();
    const console = container.querySelector(".secops-console");
    expect(console?.children).toHaveLength(2);
    expect(container.querySelector(".secops-main-workspace")).toContainElement(
      container.querySelector(".secops-workspace"),
    );
    for (const secret of [
      "attempt-secret",
      "identifier-secret",
      "ip-secret",
      "user-secret",
      "password_secret",
      "oauth_secret",
    ])
      expect(container.innerHTML).not.toContain(secret);
    expect(screen.getAllByRole("button", { name: "解除锁定" })).toHaveLength(1);
  });

  it("changes time range and unlocks only unlockable attempts", async () => {
    render(<AdminAuthSecurityPage />);
    await screen.findByText("李顾问");
    fireEvent.change(screen.getByLabelText("时间范围"), { target: { value: "360" } });
    await waitFor(() =>
      expect(fetchAuthSecurityOverview).toHaveBeenLastCalledWith({ windowMinutes: 360, limit: 50 }),
    );
    fireEvent.click(screen.getByRole("button", { name: "解除锁定" }));
    await waitFor(() => expect(unlockAuthLockout).toHaveBeenCalledWith({ user_id: "user-secret" }));
  });

  it.each([
    [{ ...overview, recent_events: [] }, "该时间范围内暂无登录尝试"],
    [new ApiError(503, "raw auth token"), "登录安全状态暂时无法加载，请稍后重试。"],
    [new ApiError(403, "raw forbidden"), "当前身份没有登录安全运营权限。"],
  ])("handles empty, failure and forbidden safely", async (result, expected) => {
    if (result instanceof Error) vi.mocked(fetchAuthSecurityOverview).mockRejectedValueOnce(result);
    else vi.mocked(fetchAuthSecurityOverview).mockResolvedValueOnce(result);
    const { container } = render(<AdminAuthSecurityPage />);
    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/raw auth token|raw forbidden/);
  });
});
