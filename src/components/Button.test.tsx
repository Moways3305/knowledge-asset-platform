import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Button from "./Button";

describe("Button", () => {
  it("uses the shared primary and size contract", () => {
    render(
      <Button variant="primary" size="small">
        保存更改
      </Button>,
    );
    expect(screen.getByRole("button", { name: "保存更改" })).toHaveClass(
      "product-button",
      "is-primary",
      "is-small",
    );
  });

  it("keeps disabled and click behavior native", () => {
    const onClick = vi.fn();
    const { rerender } = render(
      <Button disabled onClick={onClick}>
        删除
      </Button>,
    );
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(onClick).not.toHaveBeenCalled();

    rerender(<Button onClick={onClick}>删除</Button>);
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(onClick).toHaveBeenCalledOnce();
  });
});
