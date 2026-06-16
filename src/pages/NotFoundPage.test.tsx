import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import NotFoundPage from "./NotFoundPage";

describe("NotFoundPage", () => {
  it("渲染 404 文案与返回首页链接", () => {
    render(
      <MemoryRouter>
        <NotFoundPage />
      </MemoryRouter>,
    );
    expect(screen.getByText("页面不存在")).toBeInTheDocument();
    const home = screen.getByRole("link", { name: "返回今日工作台" });
    expect(home).toHaveAttribute("href", "/");
  });

  it('未知路由经 path="*" 命中 NotFound', () => {
    render(
      <MemoryRouter initialEntries={["/no-such-route"]}>
        <Routes>
          <Route path="/" element={<div>home</div>} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("页面不存在")).toBeInTheDocument();
  });
});
