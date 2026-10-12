import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import McpAuthorizePage from "./McpAuthorizePage";
import { apiGet, apiPost } from "../api/http";

vi.mock("../api/http", () => ({ apiGet: vi.fn(), apiPost: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiGet).mockResolvedValue({
    client_name: "外部助理",
    redirect_origin: "assistant.example",
    operations_requested: true,
  });
});
function show(url = "/mcp-authorize?request=test-request") {
  render(
    <MemoryRouter initialEntries={[url]}>
      <McpAuthorizePage />
    </MemoryRouter>,
  );
}
describe("OAuth consent", () => {
  it("does not pre-authorize writes and clearly displays the destination", async () => {
    show();
    expect(await screen.findByText(/assistant.example/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "同意并连接" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("button", { name: "同意并连接" })).toBeEnabled();
    expect(apiPost).not.toHaveBeenCalled();
  });
  it("allows refusal without granting operations", async () => {
    vi.mocked(apiPost).mockRejectedValue(new Error("测试终止跳转"));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "拒绝授权" }));
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/api/v1/auth/mcp-oauth/requests/test-request", {
        approved: false,
        operations: false,
      }),
    );
  });
  it("rejects missing requests without loading anything", async () => {
    show("/mcp-authorize");
    expect(await screen.findByRole("alert")).toHaveTextContent("缺少授权请求");
    expect(apiGet).not.toHaveBeenCalled();
  });
});
