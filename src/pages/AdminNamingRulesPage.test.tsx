import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchNamingRuleCenter, publishNamingRuleDraft, saveNamingRuleDraft } from "../api/naming";
import type { NamingRuleCenterDTO } from "../types/naming";
import AdminNamingRulesPage from "./AdminNamingRulesPage";

vi.mock("../api/naming", () => ({
  fetchNamingRuleCenter: vi.fn(),
  publishNamingRuleDraft: vi.fn(),
  saveNamingRuleDraft: vi.fn(),
}));

const center: NamingRuleCenterDTO = {
  published: {
    version: 1,
    status: "published",
    base_published_version: 0,
    config: { schema_version: 1, enforced: false, project_codes: [], categories: [] },
    updated_at: "2026-08-02T00:00:00Z",
    published_at: "2026-08-02T00:00:00Z",
  },
  draft: {
    version: 2,
    status: "draft",
    base_published_version: 1,
    config: {
      schema_version: 1,
      enforced: false,
      project_codes: [],
      categories: [
        {
          id: "10000000-0000-0000-0000-000000000001",
          scope: "project",
          primary: "项目资料",
          secondary: "交付件",
          prefix: "项目资料-交付件",
          default_confidentiality: "L2",
          enabled: true,
          sort_order: 10,
        },
      ],
    },
    updated_at: "2026-08-02T00:00:00Z",
    published_at: null,
  },
  projects: [
    {
      id: "20000000-0000-0000-0000-000000000001",
      name: "示例项目",
      status: "active",
      project_code: null,
      project_code_active: false,
      default_confidentiality: "L2",
    },
  ],
};

describe("AdminNamingRulesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchNamingRuleCenter).mockResolvedValue(structuredClone(center));
    vi.mocked(saveNamingRuleDraft).mockImplementation(async (base, config) => ({
      ...structuredClone(center.draft),
      base_published_version: base,
      config,
    }));
    vi.mocked(publishNamingRuleDraft).mockResolvedValue({
      ...structuredClone(center),
      published: { ...structuredClone(center.draft), status: "published" },
    });
  });

  it("keeps edits in the draft until an explicit publish", async () => {
    render(<AdminNamingRulesPage />);

    const code = await screen.findByPlaceholderText("如 BW-2601");
    fireEvent.change(code, { target: { value: "bw-2601" } });
    fireEvent.click(screen.getAllByLabelText("启用")[0]);
    fireEvent.click(screen.getByLabelText(/发布后强制/));
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));

    await waitFor(() => expect(saveNamingRuleDraft).toHaveBeenCalledTimes(1));
    expect(saveNamingRuleDraft).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        enforced: true,
        project_codes: [expect.objectContaining({ code: "BW-2601", enabled: true })],
      }),
    );
    expect(publishNamingRuleDraft).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /发布规则/ }));
    await waitFor(() => expect(publishNamingRuleDraft).toHaveBeenCalledWith(1));
  });

  it("shows the project canonical-name shape without customer names", async () => {
    render(<AdminNamingRulesPage />);
    expect(await screen.findByText(/【PRJ-2026-交付件】/)).toBeInTheDocument();
  });
});
