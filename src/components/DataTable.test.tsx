import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
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

  it("shows the loading text instead of rows while loading", () => {
    const { container } = render(
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        loading
        loadingText="加载中…"
      />,
    );
    expect(screen.getByText("加载中…")).toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(container.querySelector(".product-table-state-content svg")).toBeInTheDocument();
    expect(screen.queryByText("甲")).not.toBeInTheDocument();
  });
});
