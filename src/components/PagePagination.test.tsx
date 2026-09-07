import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PagePagination from "./PagePagination";

describe("PagePagination", () => {
  it("jumps to a specified valid page from the keyboard form", () => {
    const onPageChange = vi.fn();
    render(
      <PagePagination ariaLabel="测试分页" page={5} totalPages={19} onPageChange={onPageChange} />,
    );

    const target = screen.getByRole("spinbutton", { name: "跳至指定页" });
    fireEvent.change(target, { target: { value: "19" } });
    fireEvent.submit(target.closest("form")!);

    expect(onPageChange).toHaveBeenCalledWith(19);
  });

  it("does not request an out-of-range page", () => {
    const onPageChange = vi.fn();
    render(
      <PagePagination ariaLabel="测试分页" page={5} totalPages={19} onPageChange={onPageChange} />,
    );

    fireEvent.change(screen.getByRole("spinbutton", { name: "跳至指定页" }), {
      target: { value: "20" },
    });
    expect(screen.getByRole("button", { name: "跳转" })).toBeDisabled();
    expect(onPageChange).not.toHaveBeenCalled();
  });
});
