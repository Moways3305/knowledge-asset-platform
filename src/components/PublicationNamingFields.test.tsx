import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
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
  categories: [
    {
      id: "unmapped-category",
      scope: "project",
      primary: "项目资料",
      secondary: "待治理类别",
      prefix: "项目资料-待治理类别",
      asset_type: "deliverable",
      default_confidentiality: "L2",
      enabled: true,
      sort_order: 10,
      suggested_directory_key: null,
    },
  ],
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
  it("reveals a scoped fallback only after the backend reports a missing mapping", async () => {
    vi.mocked(fetchNamingOptions).mockResolvedValue(options);
    const onPreview = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(422, "需要目录", "directory_required"))
      .mockResolvedValueOnce({
        required: true,
        canonical_name: "【ALPHA-2026-待治理类别】发布主题_20260817_V1_L2.md",
        rule_version: 12,
        fields: { directory_key: "project.deliverables" },
        notices: [],
        message: null,
      });
    render(<Harness onPreview={onPreview} />);

    await screen.findByText("由目录类别规则确定");
    expect(screen.queryByRole("combobox", { name: "正式目录（映射缺失补选）" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "预览目标文件名" }));
    const fallback = await screen.findByRole("combobox", {
      name: "正式目录（映射缺失补选）",
    });
    fireEvent.change(fallback, { target: { value: "project.deliverables" } });
    fireEvent.click(screen.getByRole("button", { name: "预览目标文件名" }));

    await waitFor(() => expect(onPreview).toHaveBeenCalledTimes(2));
    expect(onPreview.mock.calls[1][0].naming).toEqual(
      expect.objectContaining({
        directory_key: "project.deliverables",
        directory_fallback_confirmed: true,
      }),
    );
  });
});
