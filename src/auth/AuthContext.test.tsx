import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useState } from "react";
import { fetchAuthMe, type AuthMeVM } from "../api/auth";
import { ApiError } from "../api/http";
import { AuthProvider, useAuth } from "./AuthContext";
import { AUTH_CHANGE_KEY } from "./authChanges";

vi.mock("../api/auth", () => ({ fetchAuthMe: vi.fn() }));
const identity: AuthMeVM = {
  userId: "test-user",
  name: "Test",
  email: "test@example.test",
  companyRoles: ["boss", "consultant"],
  activeCompanyRole: "boss",
  isBusinessUser: true,
  canDiscoverL5: true,
  projects: [],
};
const consultant = { ...identity, activeCompanyRole: "consultant", canDiscoverL5: false };

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function ProtectedDraft() {
  const [draft, setDraft] = useState("");
  return (
    <input aria-label="草稿" value={draft} onChange={(event) => setDraft(event.target.value)} />
  );
}
function Probe() {
  const { authMe, status, setAuthMe } = useAuth();
  return (
    <>
      <p>{status}</p>
      <p>{authMe?.activeCompanyRole}</p>
      <button onClick={() => setAuthMe(consultant)}>本地身份更新</button>
      {status === "authenticated" && <ProtectedDraft />}
    </>
  );
}
function setup() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}
function crossTabChange(revision: string) {
  fireEvent(window, new StorageEvent("storage", { key: AUTH_CHANGE_KEY, newValue: revision }));
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(fetchAuthMe).mockResolvedValue(identity);
});

it("retains a mounted draft through silent foreground revalidation of the same identity", async () => {
  setup();
  const draft = await screen.findByLabelText("草稿");
  fireEvent.change(draft, { target: { value: "尚未发送的内容" } });
  const request = deferred<AuthMeVM>();
  vi.mocked(fetchAuthMe).mockReturnValueOnce(request.promise);
  fireEvent.focus(window);
  expect(screen.getByLabelText("草稿")).toBe(draft);
  expect(screen.queryByText("loading")).not.toBeInTheDocument();
  await act(async () => request.resolve({ ...identity }));
  expect(screen.getByLabelText("草稿")).toBe(draft);
  expect(draft).toHaveValue("尚未发送的内容");
});

it("retains drafts on a silent network failure, but fails closed on an explicit logout", async () => {
  setup();
  const draft = await screen.findByLabelText("草稿");
  fireEvent.change(draft, { target: { value: "保留草稿" } });
  vi.mocked(fetchAuthMe).mockRejectedValueOnce(new TypeError("offline"));
  fireEvent.focus(window);
  await waitFor(() => expect(fetchAuthMe).toHaveBeenCalledTimes(2));
  expect(draft).toHaveValue("保留草稿");
  vi.mocked(fetchAuthMe).mockRejectedValueOnce(new ApiError(401, ""));
  fireEvent.focus(window);
  expect(await screen.findByText("anonymous")).toBeInTheDocument();
  expect(screen.queryByLabelText("草稿")).not.toBeInTheDocument();
});

it("hides old protected content immediately after cross-tab invalidation and clears it on role change", async () => {
  setup();
  fireEvent.change(await screen.findByLabelText("草稿"), { target: { value: "旧身份的草稿" } });
  const request = deferred<AuthMeVM>();
  vi.mocked(fetchAuthMe).mockReturnValueOnce(request.promise);
  crossTabChange("test-revision-1");
  expect(screen.queryByLabelText("草稿")).not.toBeInTheDocument();
  expect(screen.queryByText("boss")).not.toBeInTheDocument();
  await act(async () => request.resolve(consultant));
  expect(screen.getByLabelText("草稿")).toHaveValue("");
  expect(screen.getByText("consultant")).toBeInTheDocument();
});

it("cannot restore an earlier privileged identity from an out-of-order request", async () => {
  setup();
  await screen.findByLabelText("草稿");
  const older = deferred<AuthMeVM>();
  const newer = deferred<AuthMeVM>();
  vi.mocked(fetchAuthMe).mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
  fireEvent.focus(window);
  crossTabChange("test-revision-2");
  await act(async () => newer.resolve(consultant));
  await act(async () => older.resolve(identity));
  expect(screen.getByText("consultant")).toBeInTheDocument();
  expect(screen.queryByText("boss")).not.toBeInTheDocument();
});

it("fences pending reads when login or role selection supplies a newer identity", async () => {
  setup();
  await screen.findByLabelText("草稿");
  const old = deferred<AuthMeVM>();
  vi.mocked(fetchAuthMe).mockReturnValueOnce(old.promise);
  fireEvent.focus(window);
  fireEvent.click(screen.getByRole("button", { name: "本地身份更新" }));
  await act(async () => old.resolve(identity));
  expect(screen.getByText("consultant")).toBeInTheDocument();
  expect(screen.queryByText("boss")).not.toBeInTheDocument();
});

it("discards cached protected content when memberships change on foreground revalidation", async () => {
  setup();
  fireEvent.change(await screen.findByLabelText("草稿"), { target: { value: "项目资料" } });
  vi.mocked(fetchAuthMe).mockResolvedValueOnce({
    ...identity,
    projects: [{ projectId: "project", projectName: "Project", projectRole: "member" }],
  });
  fireEvent.focus(window);
  await waitFor(() => expect(screen.getByLabelText("草稿")).toHaveValue(""));
});

it("deduplicates transport revisions and removes listeners on unmount", async () => {
  const mounted = setup();
  await screen.findByLabelText("草稿");
  crossTabChange("one-change");
  await screen.findByLabelText("草稿");
  crossTabChange("one-change");
  expect(fetchAuthMe).toHaveBeenCalledTimes(2);
  mounted.unmount();
  crossTabChange("after-unmount");
  fireEvent.focus(window);
  expect(fetchAuthMe).toHaveBeenCalledTimes(2);
});
