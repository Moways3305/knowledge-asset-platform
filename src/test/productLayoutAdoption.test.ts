import { describe, expect, it } from "vitest";

const sourceModules = import.meta.glob("../{pages,components}/**/*.{ts,tsx}", {
  eager: true,
  query: "?raw",
  import: "default",
}) as Record<string, string>;
const read = (file: string) => sourceModules[`../${file.replace(/^src\//, "")}`];

describe("PBC-47 product layout adoption", () => {
  it("shares the product page primitive across representative user and admin routes", () => {
    expect(read("src/pages/KnowledgeListPage.tsx")).toContain("<ProductPage");
    for (const page of [
      "AdminIngestPage.tsx",
      "AdminAuditPage.tsx",
      "AdminWeKnoraModelsPage.tsx",
    ]) {
      const source = read(`src/pages/${page}`);
      expect(source).toContain("<ProductPage");
      expect(source).toContain("<PageHeader");
    }
  });

  it("keeps ingest provenance visible while moving technical fields into details", () => {
    const source = read("src/pages/AdminIngestPage.tsx");
    expect(source).toContain('path_a_wecom: "企业微信微盘"');
    expect(source).toContain('path_b_upload: "本地上传"');
    expect(source).toContain("任务详情（运营元数据）");
    expect(source).toContain('<details className="product-disclosure"');
    expect(source).not.toContain("ig-exception-grid");
  });

  it("collapses audit action codes and trace identifiers by default", () => {
    const source = read("src/pages/AdminAuditPage.tsx");
    expect(source).not.toContain("au-cell-raw");
    expect(source.match(/<details>/g)?.length).toBeGreaterThanOrEqual(3);
    expect(source).toContain("{log.action}");
    expect(source).toContain("{log.trace_id}");
  });

  it("keeps governance model selectors read-only with an explanation", () => {
    const source = read("src/components/DefaultModelsSection.tsx");
    expect(source).toContain("disabled={!canEdit}");
    expect(source).toContain("当前身份仅可查看，修改需系统管理员");
  });
});
