import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  PageHeader,
  PageSection,
  PageToolbar,
  ProductPage,
  SettingsRow,
  StatusStrip,
} from "./ProductLayout";

describe("ProductLayout primitives", () => {
  it("provides one page header, grouped section, toolbar and status strip", () => {
    const { container } = render(
      <ProductPage>
        <PageHeader title="知识资产" description="统一页面说明" actions={<button>新增</button>} />
        <StatusStrip items={[{ label: "待处理", value: 2, tone: "warning" }]} />
        <PageSection title="列表">
          <PageToolbar start={<select aria-label="筛选" />} end={<button>刷新</button>} />
        </PageSection>
      </ProductPage>,
    );
    expect(container.querySelectorAll(".product-page-header")).toHaveLength(1);
    expect(container.querySelectorAll(".product-section")).toHaveLength(1);
    expect(screen.getByText("待处理")).toBeInTheDocument();
  });

  it("settings row explains disabled controls with an actionable entry", () => {
    render(
      <SettingsRow
        title="内容生成模型"
        description="用于摘要生成"
        disabledReason={<button>新增内容生成模型</button>}
        control={<select disabled aria-label="内容生成模型" />}
      />,
    );
    expect(screen.getByRole("button", { name: "新增内容生成模型" })).toBeInTheDocument();
    expect(screen.getByLabelText("内容生成模型")).toBeDisabled();
  });
});
