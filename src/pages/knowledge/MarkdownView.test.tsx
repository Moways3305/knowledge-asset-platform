import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownView, safeMarkdownHref } from "./OnlyOfficePreview";

describe("untrusted Markdown links", () => {
  it.each([
    "javascript:alert%281%29",
    "data:text/html,payload",
    "//outside.example",
    "\\\\outside.example",
    "java\nscript:payload",
    "file:///private",
  ])("rejects %s", (value) => {
    expect(safeMarkdownHref(value)).toBeNull();
  });
  it("renders permitted source links while leaving unsafe links inert", () => {
    render(
      <MarkdownView text="[原资料](/knowledge/asset) [参考](https://example.org/source) [危险](javascript:payload) <script>alert('no')</script>" />,
    );
    expect(screen.getByRole("link", { name: "原资料" })).toHaveAttribute(
      "href",
      "/knowledge/asset",
    );
    expect(screen.getByRole("link", { name: "参考" })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
    expect(screen.queryByRole("link", { name: "危险" })).not.toBeInTheDocument();
    expect(window.document.querySelector("script")).toBeNull();
  });
});
