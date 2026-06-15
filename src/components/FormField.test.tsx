import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import FormField from "./FormField";

describe("FormField", () => {
  it("renders the label and the control children", () => {
    render(
      <FormField label="项目名称">
        <input defaultValue="甲项目" />
      </FormField>
    );
    expect(screen.getByText("项目名称")).toBeInTheDocument();
    expect(screen.getByDisplayValue("甲项目")).toBeInTheDocument();
  });

  it("uses the kl-modal-field class by default", () => {
    const { container } = render(<FormField label="x"><input /></FormField>);
    expect(container.querySelector("label.kl-modal-field")).toBeInTheDocument();
  });

  it("renders hint and error text when provided", () => {
    render(<FormField label="x" hint="可选" error="必填"><input /></FormField>);
    expect(screen.getByText("可选")).toBeInTheDocument();
    expect(screen.getByText("必填")).toBeInTheDocument();
  });
});
