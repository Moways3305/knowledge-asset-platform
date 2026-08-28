import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchWorkbuddyToken } from "../api/workbuddy";
import WorkbuddyStatusPanel from "./WorkbuddyStatusPanel";

vi.mock("../api/workbuddy", () => ({ fetchWorkbuddyToken: vi.fn() }));

function renderPanel() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <WorkbuddyStatusPanel />
    </MemoryRouter>,
  );
}

describe("WorkbuddyStatusPanel", () => {
  beforeEach(() => vi.mocked(fetchWorkbuddyToken).mockReset());

  it("shows the disabled state from enabled=false", async () => {
    vi.mocked(fetchWorkbuddyToken).mockResolvedValue({
      enabled: false,
      boundUserName: null,
      lastRotatedAt: null,
      lastConnectedAt: null,
    });
    renderPanel();
    expect(await screen.findByText("尚未启用")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /前往设置/ })).toHaveAttribute("href", "/my/workbuddy");
  });

  it("does not claim connection before the first successful connection", async () => {
    vi.mocked(fetchWorkbuddyToken).mockResolvedValue({
      enabled: true,
      boundUserName: "用户",
      lastRotatedAt: "2026-08-28T01:00:00Z",
      lastConnectedAt: null,
    });
    renderPanel();
    expect(await screen.findByText("已启用，等待首次成功连接")).toBeInTheDocument();
    expect(screen.queryByText(/^已连接/)).not.toBeInTheDocument();
  });

  it("shows only the backend last-connected time for a connected token", async () => {
    vi.mocked(fetchWorkbuddyToken).mockResolvedValue({
      enabled: true,
      boundUserName: "用户",
      lastRotatedAt: "2026-08-28T01:00:00Z",
      lastConnectedAt: "2026-08-28T02:30:00Z",
    });
    renderPanel();
    expect(
      await screen.findByText(/已连接 · 最近成功连接 2026-08-28 10:30:00/),
    ).toBeInTheDocument();
  });
});
