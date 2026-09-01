import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchDirectoryMigration, fetchNamingRuleCenter, saveNamingRuleDraft } from "../api/naming";
import type { NamingRuleCenterDTO } from "../types/naming";
import AdminNamingRulesPage from "./AdminNamingRulesPage";

vi.mock("../api/naming", () => ({
  confirmDirectoryMigration: vi.fn(),
  fetchDirectoryMigration: vi.fn(),
  fetchNamingRuleCenter: vi.fn(),
  publishNamingRuleDraft: vi.fn(),
  saveNamingRuleDraft: vi.fn(),
}));

const legacyCategory = {
  id: "10000000-0000-0000-0000-000000000001",
  scope: "company" as const,
  primary: "方法论",
  secondary: "模型工具",
  prefix: "方法论-模型工具",
  asset_type: "methodology" as const,
  default_confidentiality: "L2",
  enabled: true,
  sort_order: 20,
};

const center: NamingRuleCenterDTO = {
  published: {
    version: 1,
    status: "published",
    base_published_version: 0,
    config: { schema_version: 2, enforced: true, project_codes: [], categories: [] },
    updated_at: "2026-08-31T00:00:00Z",
    published_at: "2026-08-31T00:00:00Z",
  },
  draft: {
    version: 2,
    status: "draft",
    base_published_version: 1,
    config: {
      schema_version: 2,
      enforced: true,
      project_codes: [],
      categories: [legacyCategory],
      directories: [
        {
          directory_key: "company.methodology",
          scope: "company",
          display_name: "02 方法论",
          description: "模型与工具",
          naming_code: "方法论",
          default_confidentiality: "L2",
          enabled: true,
          sort_order: 20,
        },
        {
          directory_key: "project.deliverables",
          scope: "project",
          display_name: "03 交付成果",
          enabled: true,
          sort_order: 30,
        },
      ],
    },
    updated_at: "2026-08-31T00:00:00Z",
    published_at: null,
  },
  projects: [],
};

describe("AdminNamingRulesPage directory governance", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchNamingRuleCenter).mockResolvedValue(structuredClone(center));
    vi.mocked(saveNamingRuleDraft).mockImplementation(async (base, config) => ({
      ...structuredClone(center.draft),
      base_published_version: base,
      config,
    }));
  });

  it("shows formal directories without category or project-code management", async () => {
    render(<AdminNamingRulesPage />);
    expect(await screen.findByText("目录治理")).toBeInTheDocument();
    expect(screen.getByDisplayValue("02 方法论")).toBeInTheDocument();
    expect(screen.queryByText("目录类别")).not.toBeInTheDocument();
    expect(screen.queryByText("项目代码")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "项目目录" }));
    expect(screen.getByDisplayValue("03 交付成果")).toBeInTheDocument();
  });

  it("round-trips historical categories unchanged while saving directory edits", async () => {
    render(<AdminNamingRulesPage />);
    const name = await screen.findByDisplayValue("02 方法论");
    fireEvent.change(name, { target: { value: "02 方法与工具" } });
    fireEvent.click(screen.getByRole("button", { name: /保存草稿/ }));

    await waitFor(() => expect(saveNamingRuleDraft).toHaveBeenCalledTimes(1));
    const config = vi.mocked(saveNamingRuleDraft).mock.calls[0][1];
    expect(config.categories).toEqual([legacyCategory]);
    expect(config.directories?.[0].display_name).toBe("02 方法与工具");
  });

  it("reports the auditable pending-governance counts", async () => {
    vi.mocked(fetchDirectoryMigration).mockResolvedValue({
      overview: {
        total: 3,
        migrated: 1,
        clear_match: 1,
        manual_required: 1,
        no_candidate: 1,
        failed: 0,
        rule_version: 1,
      },
      items: [],
      total: 0,
      directories: [],
    });
    render(<AdminNamingRulesPage />);
    await screen.findByText("目录治理");
    fireEvent.click(screen.getByRole("button", { name: /历史待治理/ }));
    expect(await screen.findByText(/总计 3 · 待人工 1 · 无明确候选 1/)).toBeInTheDocument();
  });
});
