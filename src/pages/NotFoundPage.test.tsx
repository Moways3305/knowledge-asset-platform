import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import NotFoundPage from "./NotFoundPage";

const safeNavigation = vi.hoisted(() => ({ goBack: vi.fn() }));
vi.mock("../routing/SafeNavigation", () => ({
  useSafeNavigation: () => safeNavigation,
}));

describe("NotFoundPage", () => {
  it("提供安全说明和两个真实恢复动作", () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/private/token-should-not-render"]}>
        <NotFoundPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "页面不存在或已不可用" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回上一页" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "返回今日工作台" })).toHaveAttribute("href", "/");
    expect(container.querySelector(".global-state-graphic svg")).toBeInTheDocument();
    expect(screen.queryByText(/token-should-not-render/i)).not.toBeInTheDocument();
  });

  it("返回上一页委托统一安全返回路由", () => {
    safeNavigation.goBack.mockReset().mockResolvedValue(undefined);
    render(
      <MemoryRouter initialEntries={["/missing"]}>
        <NotFoundPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "返回上一页" }));
    expect(safeNavigation.goBack).toHaveBeenCalledTimes(1);
  });
});
