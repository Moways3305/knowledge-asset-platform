import { beforeEach, expect, it, vi } from "vitest";
import { announceAuthChange } from "../auth/authChanges";
import { apiGet, apiPost, apiPostNoBody, clearCsrfToken } from "./http";
import { logout, switchActiveCompanyRole } from "./auth";

vi.mock("../auth/authChanges", () => ({ announceAuthChange: vi.fn() }));
vi.mock("./http", () => ({
  BASE_URL: "",
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPostNoBody: vi.fn(),
  clearCsrfToken: vi.fn(),
  devHeaders: vi.fn(),
  ensureCsrfToken: vi.fn(),
  handleResponse: vi.fn(),
}));
beforeEach(() => vi.resetAllMocks());

it("invalidates other tabs after a role cookie changes even when confirmation fails", async () => {
  vi.mocked(apiPost).mockResolvedValue({});
  vi.mocked(apiGet).mockRejectedValue(new Error("offline"));
  await expect(switchActiveCompanyRole("consultant")).rejects.toThrow("offline");
  expect(clearCsrfToken).toHaveBeenCalledOnce();
  expect(announceAuthChange).toHaveBeenCalledOnce();
  expect(announceAuthChange).toHaveBeenCalledWith();
});

it("does not announce a rejected role switch", async () => {
  vi.mocked(apiPost).mockRejectedValue(new Error("rejected"));
  await expect(switchActiveCompanyRole("boss")).rejects.toThrow("rejected");
  expect(announceAuthChange).not.toHaveBeenCalled();
});

it("invalidates other tabs only after logout succeeds", async () => {
  vi.mocked(apiPostNoBody).mockResolvedValue({ ok: true });
  await logout();
  expect(announceAuthChange).toHaveBeenCalledOnce();
  expect(clearCsrfToken).toHaveBeenCalledOnce();
  vi.mocked(apiPostNoBody).mockRejectedValue(new Error("rejected"));
  await expect(logout()).rejects.toThrow("rejected");
  expect(announceAuthChange).toHaveBeenCalledOnce();
});
