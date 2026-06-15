import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

// 框架冒烟：确认 vitest + jsdom + @testing-library/react + jest-dom 断言链路可用。
describe("toolchain smoke", () => {
  it("renders into jsdom and queries the DOM", () => {
    render(<p>知识资产平台</p>);
    expect(screen.getByText("知识资产平台")).toBeInTheDocument();
  });
});
