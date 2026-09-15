import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { login } from "../api/auth";
import { startWecomOAuth } from "../api/admin";
import { ApiError } from "../api/http";
import LoginGate from "../auth/LoginGate";
import { consumeLoginReturn, rememberLoginReturn } from "../auth/loginReturn";

const auth = vi.hoisted(() => ({ status: "anonymous", setAuthMe: vi.fn(), reload: vi.fn() }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../api/auth", () => ({ login: vi.fn() }));
vi.mock("../api/admin", () => ({ startWecomOAuth: vi.fn() }));
function Protected() {
  const loc = useLocation();
  return (
    <div>
      protected:{loc.pathname}
      {loc.search}
    </div>
  );
}
function setup(path = "/upload?page=3") {
  return render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <LoginGate>
        <Protected />
      </LoginGate>
    </MemoryRouter>,
  );
}
function fill() {
  fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "person@example.com" } });
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: "secret" } });
}
beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  auth.status = "anonymous";
});
describe("login page", () => {
  it("hides protected content and uses accessible real fields", () => {
    setup();
    expect(screen.queryByText(/protected:/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("密码")).toHaveAttribute("type", "password");
    fireEvent.click(screen.getByRole("button", { name: "显示密码" }));
    expect(screen.getByLabelText("密码")).toHaveAttribute("type", "text");
  });
  it("submits credentials once and updates shared auth", async () => {
    const me = { userId: "test" } as Awaited<ReturnType<typeof login>>;
    vi.mocked(login).mockResolvedValue(me);
    setup();
    fill();
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    expect(screen.getByRole("button", { name: "正在登录…" })).toBeDisabled();
    await waitFor(() => expect(auth.setAuthMe).toHaveBeenCalledWith(me));
    expect(login).toHaveBeenCalledOnce();
    expect(login).toHaveBeenCalledWith("person@example.com", "secret");
    expect(screen.getByLabelText("密码")).toHaveValue("");
    expect(sessionStorage.length).toBe(0);
  });
  it("shows safe errors and permits retry", async () => {
    vi.mocked(login).mockRejectedValue(new ApiError(401, "internal secret"));
    setup();
    fill();
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("邮箱或密码错误");
    expect(screen.queryByText("internal secret")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "登录" })).toBeEnabled();
    expect(auth.setAuthMe).not.toHaveBeenCalled();
  });
  it("requires a password instead of using the development adapter", () => {
    setup();
    fireEvent.submit(screen.getByLabelText("密码").closest("form")!);
    expect(login).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("请输入邮箱和密码");
  });
  it("starts browser WeCom mode and safely handles an unavailable service", async () => {
    vi.mocked(startWecomOAuth).mockRejectedValue(new Error("secret"));
    setup();
    fireEvent.click(screen.getByRole("button", { name: "企业微信登录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("企业微信登录暂不可用");
    expect(startWecomOAuth).toHaveBeenCalledWith("web_qr");
  });
  it("rejects an unsafe OAuth scheme", async () => {
    vi.mocked(startWecomOAuth).mockResolvedValue({
      authorize_url: "javascript:alert(1)",
    } as Awaited<ReturnType<typeof startWecomOAuth>>);
    setup();
    fireEvent.click(screen.getByRole("button", { name: "企业微信登录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("企业微信登录暂不可用");
    expect(sessionStorage.length).toBe(0);
  });
  it("fails closed while identity is loading or unavailable", () => {
    auth.status = "loading";
    const view = setup();
    expect(screen.getByRole("status")).toHaveTextContent("正在验证");
    expect(screen.queryByLabelText("密码")).not.toBeInTheDocument();
    auth.status = "error";
    view.rerender(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <LoginGate>
          <Protected />
        </LoginGate>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "重新连接" }));
    expect(auth.reload).toHaveBeenCalledOnce();
    expect(screen.queryByText(/protected:/)).not.toBeInTheDocument();
  });
  it("keeps the deep link after authentication", () => {
    auth.status = "authenticated";
    setup();
    expect(screen.getByText("protected:/upload?page=3")).toBeInTheDocument();
  });
  it("restores an OAuth deep link once", async () => {
    rememberLoginReturn("/knowledge?page=4");
    auth.status = "authenticated";
    setup("/");
    await waitFor(() =>
      expect(screen.getByText("protected:/knowledge?page=4")).toBeInTheDocument(),
    );
    expect(consumeLoginReturn()).toBeNull();
  });
});
describe("OAuth return validation", () => {
  it.each(["//evil.test", "https://evil.test", "/\\evil.test", "/login", "javascript:alert(1)"])(
    "rejects %s",
    (path) => {
      rememberLoginReturn(path);
      expect(consumeLoginReturn()).toBeNull();
    },
  );
  it("expires old destinations", () => {
    vi.spyOn(Date, "now").mockReturnValueOnce(1).mockReturnValue(700_000);
    rememberLoginReturn("/upload");
    expect(consumeLoginReturn()).toBeNull();
    vi.restoreAllMocks();
  });
});
