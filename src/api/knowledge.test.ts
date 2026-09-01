import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiGet } from "./http";
import { fetchKnowledgeList, fetchKnowledgePage } from "./knowledge";

vi.mock("./http", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

describe("knowledge query API", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset().mockResolvedValue({
      items: [],
      total: 27,
      page: 2,
      page_size: 10,
      has_next: true,
    });
  });

  it("serializes the complete paged filter and sort contract", async () => {
    const result = await fetchKnowledgePage({
      page: 2,
      pageSize: 10,
      keyword: "供应链 100%",
      scope: "project",
      projectId: "project-alpha",
      zone: "asset",
      assetStatus: "active",
      confidentialityLevel: "L3",
      createdFrom: "2026-01-01T00:00:00Z",
      createdTo: "2026-02-01T00:00:00Z",
      updatedFrom: "2026-03-01T00:00:00Z",
      updatedTo: "2026-04-01T00:00:00Z",
      sortBy: "title",
      sortDirection: "asc",
      includeArchived: true,
    });

    const path = vi.mocked(apiGet).mock.calls[0][0];
    expect(new URL(path, "https://example.test").pathname).toBe(
      "/api/v1/projects/project-alpha/knowledge",
    );
    const query = new URL(path, "https://example.test").searchParams;
    expect(Object.fromEntries(query)).toEqual({
      page: "2",
      page_size: "10",
      keyword: "供应链 100%",
      zone: "asset",
      asset_status: "active",
      confidentiality_level: "L3",
      created_from: "2026-01-01T00:00:00Z",
      created_to: "2026-02-01T00:00:00Z",
      updated_from: "2026-03-01T00:00:00Z",
      updated_to: "2026-04-01T00:00:00Z",
      sort_by: "title",
      sort_direction: "asc",
      include_archived: "true",
    });
    expect(result).toEqual({ items: [], total: 27, page: 2, pageSize: 10, hasNext: true });
  });

  it("keeps existing array consumers on the bounded first-page response", async () => {
    await expect(
      fetchKnowledgeList({ scope: "company", directoryKey: "company.methodology" }),
    ).resolves.toEqual([]);
    expect(apiGet).toHaveBeenCalledWith(
      "/api/v1/knowledge?scope=company&directory_key=company.methodology",
    );
  });
});
