import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import NotFoundPage from "./NotFoundPage";

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

  it("返回上一页会回到浏览历史中的上一入口", () => {
    render(
      <MemoryRouter initialEntries={["/previous", "/missing"]} initialIndex={1}>
        <Routes>
          <Route path="/previous" element={<div>上一入口内容</div>} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "返回上一页" }));
    expect(screen.getByText("上一入口内容")).toBeInTheDocument();
  });
});
