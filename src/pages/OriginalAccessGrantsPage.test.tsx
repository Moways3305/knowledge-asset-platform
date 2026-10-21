import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { fetchOriginalAccessGrants, revokeOriginalAccessGrant } from "../api/knowledge";
import type { AccessGrantHistoryDTO, GrantsListResponseDTO } from "../types/originalAccess";
import OriginalAccessGrantsPage from "./OriginalAccessGrantsPage";

vi.mock("../api/knowledge", () => ({
  fetchOriginalAccessGrants: vi.fn(),
  revokeOriginalAccessGrant: vi.fn(),
}));
const grant: AccessGrantHistoryDTO = {
  grant_id: "secret-grant",
  asset_id: "secret-asset",
  grantee_user_id: "secret-user",
  grant_type: "original_access",
  source_request_id: "secret-request",
  status: "active",
  expires_at: "2026-10-27T02:00:00Z",
  created_at: "2026-10-20T02:00:00Z",
  revoked_at: null,
  asset_title: "验收资料",
  scope: "company",
  grantee_name: "验收申请人",
  granted_by_name: "验收审批人",
  revoked_by_name: null,
  revoke_reason: null,
  can_revoke: true,
};
const result = (items = [grant], total = items.length): GrantsListResponseDTO => ({
  items,
  total,
  offset: 0,
  limit: 20,
});
function mount() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <OriginalAccessGrantsPage />
    </MemoryRouter>,
  );
}

describe("original authorization management", () => {
  beforeEach(() => {
    vi.mocked(fetchOriginalAccessGrants).mockReset().mockResolvedValue(result());
    vi.mocked(revokeOriginalAccessGrant)
      .mockReset()
      .mockResolvedValue({ ...grant, status: "revoked" });
  });

  it("shows safe records and the existing workspace route, not technical identifiers", async () => {
    mount();
    expect(await screen.findByRole("link", { name: "验收资料" })).toHaveAttribute(
      "href",
      "/knowledge/secret-asset",
    );
    expect(screen.getByRole("link", { name: "授权记录" })).toHaveAttribute(
      "href",
      "/original-access/grants",
    );
    expect(screen.getByText("验收申请人")).toBeVisible();
    expect(document.body.textContent).not.toMatch(/secret-|original_access/);
    expect(fetchOriginalAccessGrants).toHaveBeenCalledWith("", 0);
  });

  it("does not offer revocation when the server denies it or status is terminal", async () => {
    vi.mocked(fetchOriginalAccessGrants).mockResolvedValue(
      result([
        { ...grant, can_revoke: false },
        { ...grant, grant_id: "expired", status: "expired" },
        {
          ...grant,
          grant_id: "revoked",
          status: "revoked",
          revoke_reason: "到期前结束使用",
          revoked_by_name: "处理人",
          revoked_at: grant.created_at,
        },
      ]),
    );
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "查看撤销记录" }));
    expect(
      within(screen.getByRole("dialog", { name: "撤销记录" })).getByText("到期前结束使用"),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "撤销授权" })).not.toBeInTheDocument();
  });

  it("requires a reason and explicit confirmation, then reloads real state", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "撤销授权" }));
    const dialog = screen.getByRole("dialog", { name: "撤销原文授权" });
    const submit = within(dialog).getByRole("button", { name: "确认撤销授权" });
    expect(submit).toBeDisabled();
    expect(revokeOriginalAccessGrant).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "撤销理由" }), {
      target: { value: "  验收完成  " },
    });
    vi.mocked(fetchOriginalAccessGrants).mockResolvedValue(
      result([{ ...grant, status: "revoked", can_revoke: false }]),
    );
    fireEvent.click(submit);
    await waitFor(() => expect(revokeOriginalAccessGrant).toHaveBeenCalledTimes(1));
    expect(revokeOriginalAccessGrant).toHaveBeenCalledWith("secret-grant", "验收完成");
    expect(await screen.findByText(/原文授权已撤销；/)).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "撤销授权" })).not.toBeInTheDocument();
  });

  it("cancels without sending any write", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "撤销授权" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "取消" }));
    expect(revokeOriginalAccessGrant).not.toHaveBeenCalled();
  });

  it("blocks duplicate submissions while the request is pending", async () => {
    let finish!: (value: typeof grant) => void;
    vi.mocked(revokeOriginalAccessGrant).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "撤销授权" }));
    fireEvent.change(screen.getByRole("textbox", { name: "撤销理由" }), {
      target: { value: "结束验收" },
    });
    const button = screen.getByRole("button", { name: "确认撤销授权" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(revokeOriginalAccessGrant).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "处理中…" })).toBeDisabled();
    await act(async () => finish(grant));
  });

  it("refreshes permission conflicts instead of announcing success", async () => {
    vi.mocked(revokeOriginalAccessGrant).mockRejectedValue(new ApiError(409, "hidden diagnostic"));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "撤销授权" }));
    fireEvent.change(screen.getByRole("textbox", { name: "撤销理由" }), {
      target: { value: "结束验收" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认撤销授权" }));
    expect(await screen.findByText(/授权状态或操作权限已变化/)).toBeVisible();
    expect(screen.queryByText(/原文授权已撤销；/)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("hidden diagnostic");
  });

  it("does not assume a network failure means the write did not happen", async () => {
    vi.mocked(revokeOriginalAccessGrant).mockRejectedValue(new Error("lost acknowledgement"));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "撤销授权" }));
    fireEvent.change(screen.getByRole("textbox", { name: "撤销理由" }), {
      target: { value: "结束验收" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认撤销授权" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("未能确认撤销结果");
    expect(document.body.textContent).not.toContain("lost acknowledgement");
  });

  it("ignores an old list response after filtering", async () => {
    let finish!: (value: GrantsListResponseDTO) => void;
    vi.mocked(fetchOriginalAccessGrants).mockImplementation((status) =>
      status === "expired"
        ? Promise.resolve(
            result([{ ...grant, asset_title: "已到期资料", status: "expired", can_revoke: false }]),
          )
        : new Promise((resolve) => {
            finish = resolve;
          }),
    );
    mount();
    fireEvent.change(screen.getByRole("combobox", { name: "授权状态" }), {
      target: { value: "expired" },
    });
    expect(await screen.findByText("已到期资料")).toBeVisible();
    await act(async () => finish(result()));
    expect(screen.queryByText("验收资料")).not.toBeInTheDocument();
  });

  it("paginates and resets the offset when changing the status", async () => {
    vi.mocked(fetchOriginalAccessGrants).mockResolvedValue(result([grant], 21));
    mount();
    await screen.findByText("验收资料");
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(fetchOriginalAccessGrants).toHaveBeenCalledWith("", 20));
    fireEvent.change(screen.getByRole("combobox", { name: "授权状态" }), {
      target: { value: "revoked" },
    });
    await waitFor(() => expect(fetchOriginalAccessGrants).toHaveBeenCalledWith("revoked", 0));
  });

  it("fails closed and does not expose backend diagnostics", async () => {
    vi.mocked(fetchOriginalAccessGrants).mockRejectedValue(
      new ApiError(403, "secret server diagnostic"),
    );
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("当前身份不能查看");
    expect(document.body.textContent).not.toContain("secret server diagnostic");
    expect(screen.queryByRole("button", { name: "撤销授权" })).not.toBeInTheDocument();
  });
});
