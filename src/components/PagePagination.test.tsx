import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import PagePagination from "./PagePagination";

describe("PagePagination", () => {
  it.each([0, 1])("omits navigation for %s pages", (totalPages) => {
    const { container } = render(
      <PagePagination
        ariaLabel="测试分页"
        page={1}
        totalPages={totalPages}
        summary="共 0 条"
        onPageChange={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("uses page buttons without a jump form for short lists", () => {
    const onPageChange = vi.fn();
    render(
      <PagePagination ariaLabel="测试分页" page={1} totalPages={2} onPageChange={onPageChange} />,
    );
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "第 1 页" }));
    expect(onPageChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it("keeps a way back when the result shrinks while viewing a later page", () => {
    const onPageChange = vi.fn();
    render(
      <PagePagination ariaLabel="测试分页" page={3} totalPages={1} onPageChange={onPageChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "第 1 页" }));
    expect(onPageChange).toHaveBeenCalledWith(1);
  });

  it("does not submit a jump while the list is busy", () => {
    const onPageChange = vi.fn();
    render(
      <PagePagination
        ariaLabel="测试分页"
        page={1}
        totalPages={10}
        disabled
        onPageChange={onPageChange}
      />,
    );
    const target = screen.getByRole("spinbutton");
    fireEvent.change(target, { target: { value: "10" } });
    fireEvent.submit(target.closest("form")!);
    expect(onPageChange).not.toHaveBeenCalled();
  });
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
