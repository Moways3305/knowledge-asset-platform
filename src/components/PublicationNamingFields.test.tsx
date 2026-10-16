import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      default_confidentiality: "L4",
      enabled: true,
      sort_order: 10,
    },
    {
      directory_key: "project.key_materials",
      scope: "project",
      display_name: "项目关键资料",
      default_confidentiality: "L5",
      enabled: true,
      sort_order: 20,
    },
  ],
  default_confidentiality: "L3",
  message: null,
};

function Harness({
  onPreview,
  onPreviewed = () => undefined,
  scope = "project",
  projectId = "project-1",
}: {
  onPreview: (value: PublicationNamingValue) => Promise<NamingPreviewDTO>;
  onPreviewed?: (preview: NamingPreviewDTO | null) => void;
  scope?: "project" | "company";
  projectId?: string;
}) {
  const [value, setValue] = useState(() => {
    const initial = createPublicationNamingValue("发布主题");
    return { ...initial, naming: { ...initial.naming, formed_on: "2026-08-31" } };
  });
  return (
    <PublicationNamingFields
      scope={scope}
      projectId={projectId}
      value={value}
      onChange={setValue}
      onPreview={onPreview}
      onPreviewed={onPreviewed}
    />
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function previewResult(canonical: string): NamingPreviewDTO {
  return {
    required: true,
    canonical_name: canonical,
    rule_version: 12,
    fields: {},
    notices: [],
    message: null,
  };
}

describe("PublicationNamingFields directory governance", () => {
  it.each([
    ["project", "主题", "新主题"],
    ["project", "正式目录", "project.key_materials"],
    ["project", "形成日期", "2026-10-16"],
    ["project", "版本", "V2"],
    ["project", "密级", "L3"],
    ["company", "适用对象", "全公司新范围"],
  ] as const)(
    "invalidates an in-flight preview after %s %s changes",
    async (scope, field, next) => {
      vi.mocked(fetchNamingOptions).mockResolvedValue({
        ...options,
        directories: options.directories.map((item) => ({ ...item, scope })),
      });
      const pending = deferred<NamingPreviewDTO>();
      const onPreviewed = vi.fn();
      render(<Harness scope={scope} onPreview={() => pending.promise} onPreviewed={onPreviewed} />);
      await screen.findByRole("combobox", { name: "正式目录" });
      if (scope === "company") {
        fireEvent.change(screen.getByLabelText("适用对象"), { target: { value: "全公司" } });
      }
      fireEvent.click(screen.getByRole("button", { name: "预览目标文件名" }));
      expect(screen.getByRole("button", { name: "校验中…" })).toBeDisabled();
      fireEvent.change(screen.getByLabelText(field), { target: { value: next } });
      await act(async () => pending.resolve(previewResult("过期预览文件名.md")));
      expect(screen.queryByText("过期预览文件名.md")).not.toBeInTheDocument();
      expect(onPreviewed).toHaveBeenLastCalledWith(null);
      expect(screen.getByRole("button", { name: "预览目标文件名" })).toBeEnabled();
    },
  );

  it.each(["success", "failure"] as const)(
    "ignores an older preview %s after a new result",
    async (outcome) => {
      vi.mocked(fetchNamingOptions).mockResolvedValue(options);
      const old = deferred<NamingPreviewDTO>();
      const onPreview = vi
        .fn()
        .mockReturnValueOnce(old.promise)
        .mockResolvedValueOnce(previewResult("当前文件名.md"));
      const onPreviewed = vi.fn();
      render(<Harness onPreview={onPreview} onPreviewed={onPreviewed} />);
      await screen.findByRole("combobox", { name: "正式目录" });
      fireEvent.click(screen.getByRole("button", { name: "预览目标文件名" }));
      fireEvent.change(screen.getByLabelText("主题"), { target: { value: "当前主题" } });
      fireEvent.click(screen.getByRole("button", { name: "预览目标文件名" }));
      await screen.findByText("当前文件名.md");
      await act(async () => {
        if (outcome === "success") old.resolve(previewResult("过期文件名.md"));
        else old.reject(new Error("旧请求失败"));
      });
      expect(screen.getByText("当前文件名.md")).toBeInTheDocument();
      expect(screen.queryByText("过期文件名.md")).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(onPreviewed).toHaveBeenLastCalledWith(previewResult("当前文件名.md"));
    },
  );

  it("does not deliver a preview after the publication session closes", async () => {
    vi.mocked(fetchNamingOptions).mockResolvedValue(options);
    const pending = deferred<NamingPreviewDTO>();
    const onPreviewed = vi.fn();
    const view = render(<Harness onPreview={() => pending.promise} onPreviewed={onPreviewed} />);
    await screen.findByRole("combobox", { name: "正式目录" });
    fireEvent.click(screen.getByRole("button", { name: "预览目标文件名" }));
    view.unmount();
    onPreviewed.mockClear();
    await act(async () => pending.resolve(previewResult("已关闭会话文件名.md")));
    expect(onPreviewed).not.toHaveBeenCalled();
  });

  it.each(["project", "company"] as const)(
    "drops previous project previews when switching to %s",
    async (scope) => {
      vi.mocked(fetchNamingOptions).mockResolvedValue(options);
      const pending = deferred<NamingPreviewDTO>();
      const onPreviewed = vi.fn();
      const onPreview = () => pending.promise;
      const view = render(<Harness onPreview={onPreview} onPreviewed={onPreviewed} />);
      await screen.findByRole("combobox", { name: "正式目录" });
      fireEvent.click(screen.getByRole("button", { name: "预览目标文件名" }));
      vi.mocked(fetchNamingOptions).mockResolvedValue({
        ...options,
        directories: options.directories.map((item) => ({ ...item, scope })),
      });
      view.rerender(
        <Harness
          scope={scope}
          projectId="project-2"
          onPreview={onPreview}
          onPreviewed={onPreviewed}
        />,
      );
      await screen.findByRole("combobox", { name: "正式目录" });
      await act(async () => pending.resolve(previewResult("上个目标的文件名.md")));
      expect(screen.queryByText("上个目标的文件名.md")).not.toBeInTheDocument();
      expect(onPreviewed).toHaveBeenLastCalledWith(null);
    },
  );

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
    expect(screen.getByRole("combobox", { name: "密级" })).toHaveValue("L4");
    fireEvent.change(directory, { target: { value: "project.key_materials" } });
    expect(screen.getByRole("combobox", { name: "密级" })).toHaveValue("L5");
    expect(screen.queryByText("目录类别")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "预览目标文件名" }));

    await waitFor(() => expect(onPreview).toHaveBeenCalledTimes(1));
    expect(onPreview.mock.calls[0][0].naming).toEqual(
      expect.objectContaining({
        directory_key: "project.key_materials",
      }),
    );
    expect(onPreview.mock.calls[0][0].confidentiality_level).toBe("L5");
  });
});
