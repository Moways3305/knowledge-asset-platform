import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BulkSelectionRail, SelectionCheckbox } from "./BulkSelection";

describe("BulkSelection", () => {
  it("exposes the native indeterminate current-page state accessibly", () => {
    render(
      <SelectionCheckbox
        checked={false}
        indeterminate
        label="全选当前页可操作项"
        onChange={vi.fn()}
      />,
    );
    const checkbox = screen.getByRole("checkbox", {
      name: "全选当前页可操作项",
    }) as HTMLInputElement;
    expect(checkbox.indeterminate).toBe(true);
  });

  it("keeps current-page selection distinct from explicit filtered selection", () => {
    const selectAll = vi.fn();
    render(
      <BulkSelectionRail
        selectedCount={2}
        pageSelectedCount={2}
        matchingCount={27}
        allMatchingSelected={false}
        onSelectAllMatching={selectAll}
        onClear={vi.fn()}
      >
        <button type="button">批量删除（2）</button>
      </BulkSelectionRail>,
    );
    expect(screen.getByText("已选择本页 2 项")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "选择全部符合当前筛选条件的 27 项",
      }),
    );
    expect(selectAll).toHaveBeenCalledTimes(1);
  });
});
