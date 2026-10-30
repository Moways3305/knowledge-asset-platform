import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { apiDelete, apiGet } from "../api/http";
import McpOAuthGrants from "./McpOAuthGrants";
vi.mock("../api/http", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/http")>()),
  apiGet: vi.fn(),
  apiDelete: vi.fn(),
}));
beforeEach(() => {
  vi.mocked(apiGet)
    .mockReset()
    .mockResolvedValue({
      items: [
        {
          id: "grant-one",
          name: "测试应用",
          operations_enabled: false,
          expires_at: "2026-11-01T00:00:00Z",
        },
      ],
    });
  vi.mocked(apiDelete).mockReset().mockResolvedValue(undefined);
});
it("confirms revocation for the selected application and keeps cancellation read-only", async () => {
  render(<McpOAuthGrants />);
  fireEvent.click(await screen.findByRole("button", { name: "撤销此应用授权" }));
  expect(screen.getByRole("dialog", { name: "撤销“测试应用”的应用授权？" })).toBeInTheDocument();
  expect(apiDelete).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(apiDelete).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "撤销此应用授权" }));
  fireEvent.click(screen.getByRole("button", { name: "确认撤销应用授权" }));
  await waitFor(() =>
    expect(apiDelete).toHaveBeenCalledWith("/api/v1/auth/mcp-oauth/grants/grant-one"),
  );
  expect(await screen.findByText(/暂无应用授权/)).toBeInTheDocument();
});
