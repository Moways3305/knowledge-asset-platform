import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { NamingOptionsDTO, NamingPreviewDTO } from "../types/naming";
import PublicationNamingFields, {
  createPublicationNamingValue,
  type PublicationNamingValue,
} from "./PublicationNamingFields";

vi.mock("../api/naming", () => ({ fetchNamingOptions: vi.fn() }));
import { fetchNamingOptions } from "../api/naming";

const options: NamingOptionsDTO = {
  required: true,
  rule_version: 12,
  directories: [
    {
      directory_key: "project.deliverables",
      scope: "project",
      display_name: "项目交付物",
      enabled: true,
      sort_order: 10,
    },
  ],
  default_confidentiality: "L2",
  message: null,
};

function Harness({
  onPreview,
}: {
  onPreview: (value: PublicationNamingValue) => Promise<NamingPreviewDTO>;
}) {
  const [value, setValue] = useState(createPublicationNamingValue("发布主题"));
  return (
    <PublicationNamingFields
      scope="project"
      projectId="project-1"
      value={value}
      onChange={setValue}
      onPreview={onPreview}
      onPreviewed={() => undefined}
    />
  );
}

describe("PublicationNamingFields directory governance", () => {
  it("selects a formal directory before preview without a category fallback", async () => {
    vi.mocked(fetchNamingOptions).mockResolvedValue(options);
    const onPreview = vi.fn().mockResolvedValue({
      required: true,
      canonical_name: "【ALPHA-2026-交付成果】发布主题_20260831_V1_L2.md",
      rule_version: 12,
      fields: { directory_key: "project.deliverables" },
      notices: [],
      message: null,
    });
    render(<Harness onPreview={onPreview} />);

    const directory = await screen.findByRole("combobox", { name: "正式目录" });
    expect(directory).toHaveValue("project.deliverables");
    expect(screen.queryByText("目录类别")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "预览目标文件名" }));

    await waitFor(() => expect(onPreview).toHaveBeenCalledTimes(1));
    expect(onPreview.mock.calls[0][0].naming).toEqual(
      expect.objectContaining({
        directory_key: "project.deliverables",
      }),
    );
  });
});
