import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import DataTable, { type Column } from "./DataTable";

interface Row {
  id: string;
  name: string;
  n: number;
}
const columns: Column<Row>[] = [
  { key: "name", header: "名称", render: (r) => r.name },
  { key: "n", header: "数量", className: "cell-center", render: (r) => r.n },
];
const rows: Row[] = [
  { id: "a", name: "甲", n: 1 },
  { id: "b", name: "乙", n: 2 },
];

describe("DataTable", () => {
  it("shows scrolling guidance only when the current table actually overflows", () => {
    const { container } = render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />);
    const region = screen.getByRole("region");
    const hint = container.querySelector('[role="note"]')!;
    expect(hint).not.toBeVisible();
    Object.defineProperty(region, "clientWidth", { configurable: true, value: 400 });
    Object.defineProperty(region, "scrollWidth", { configurable: true, value: 800 });
    fireEvent(window, new Event("resize"));
    expect(hint).toBeVisible();
    Object.defineProperty(region, "scrollWidth", { configurable: true, value: 400 });
    fireEvent(window, new Event("resize"));
    expect(hint).not.toBeVisible();
  });
  it("renders headers and one row per item with the default table classes", () => {
    const { container } = render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(screen.getByText("名称")).toBeInTheDocument();
    expect(screen.getByText("甲")).toBeInTheDocument();
    expect(screen.getByText("乙")).toBeInTheDocument();
    expect(
      container.querySelector(".product-table-wrap table.product-data-table"),
    ).toBeInTheDocument();
    expect(container.querySelectorAll("tbody tr")).toHaveLength(2);
  });

  it("applies the per-column cell className", () => {
    const { container } = render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} />);
    expect(container.querySelector("td.cell-center")).toBeInTheDocument();
  });

  it("shows the empty text as a single spanning row when there are no rows", () => {
    const { container } = render(
      <DataTable columns={columns} rows={[]} rowKey={(r) => r.id} emptyText="暂无数据" />,
    );
    expect(screen.getByText("暂无数据")).toBeInTheDocument();
    expect(container.querySelector(".product-table-state-content svg")).toBeInTheDocument();
  });

  it("shows the loading text only before rows are available", () => {
    const { container } = render(
      <DataTable columns={columns} rows={[]} rowKey={(r) => r.id} loading loadingText="加载中…" />,
    );
    expect(screen.getByText("加载中…")).toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(container.querySelector(".product-table-state-content svg")).toBeInTheDocument();
    expect(screen.queryByText("甲")).not.toBeInTheDocument();
  });
});

it("retains mounted rows, expanded details and focus while revalidating", () => {
  const cols: Column<Row>[] = [
    {
      key: "name",
      header: "名称",
      render: (row) => (
        <details>
          <summary>{row.name}</summary>
          <input aria-label={`备注${row.id}`} defaultValue="" />
        </details>
      ),
    },
  ];
  const { rerender } = render(<DataTable columns={cols} rows={rows} rowKey={(row) => row.id} />);
  const summary = screen.getByText("甲");
  fireEvent.click(summary);
  const details = summary.closest("details")!;
  details.open = true;
  const input = screen.getByLabelText("备注a");
  fireEvent.change(input, { target: { value: "未保存的备注" } });
  input.focus();
  rerender(<DataTable columns={cols} rows={rows} rowKey={(row) => row.id} loading />);
  expect(input).toHaveFocus();
  expect(input).toHaveValue("未保存的备注");
  expect(details.open).toBe(true);
  expect(screen.getByLabelText("备注a")).toBe(input);
});
