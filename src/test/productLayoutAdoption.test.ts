import { describe, expect, it } from "vitest";

const sourceModules = import.meta.glob(
  ["../App.tsx", "../{pages,components,styles}/**/*.{ts,tsx,css}"],
  {
    eager: true,
    query: "?raw",
    import: "default",
  },
) as Record<string, string>;
const read = (file: string) => sourceModules[`../${file.replace(/^src\//, "")}`];

describe("product layout and route contract", () => {
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
    const source = read("src/components/UnifiedModelConnectionsSection.tsx");
    expect(source).toContain("disabled={!canEdit || loading}");
    expect(source).toContain("当前身份仅可查看，修改需系统管理员");
  });

  it("keeps personal knowledge guidance compact and WorkBuddy row-based", () => {
    const personal = read("src/pages/MyKnowledgePage.tsx");
    const workbuddy = read("src/components/WorkbuddyAccessCard.tsx");
    expect(personal).toContain('<Disclosure summary="个人知识管理说明">');
    expect(personal).not.toContain('className="mk-principle-card"');
    expect(workbuddy).toContain("<SettingsRow");
  });

  it("shows a continuous, product-facing upload flow", () => {
    const source = read("src/pages/UploadPage.tsx");
    expect(source).toContain("本地上传");
    expect(source).toContain("企微微盘待确认");
    expect(source).toContain("confirmReady || confirmSubmitted");
    expect(source).toContain("<UploadConfirmPanel");
    expect(source).not.toContain("storage_ref");
    expect(source).not.toContain("weknora_kb_id");
  });

  it("declares every current product route in the production router", () => {
    const app = read("src/App.tsx");
    expect(app).toContain("<Route index");
    for (const route of [
      "/knowledge",
      "/knowledge/:id",
      "/my/knowledge",
      "/upload",
      "/review",
      "/original-access",
      "/project/:id",
      "/project/:id/knowledge",
      "/project/:id/settings",
      "/admin/ingest",
      "/admin/wecom-scan",
      "/admin/weknora-models",
      "/admin/audit",
      "/admin/auth-security",
      "/admin/alert-settings",
      "/admin/people",
      "/admin/permissions",
      "/help",
    ]) {
      expect(app).toContain(`path="${route.slice(1)}"`);
    }
  });

  it("keeps implementation terms out of the people management copy", () => {
    const source = read("src/pages/AdminPeoplePage.tsx");
    expect(source).toContain(
      "公司角色和项目角色分别管理。项目知识访问以有效项目成员关系为准；系统管理员不因此获得业务原文权限。",
    );
    expect(source).not.toContain("user_company_roles");
    expect(source).not.toContain("project_members</code>");
  });

  it("keeps the upload empty state to one bordered input control", () => {
    const page = read("src/pages/UploadPage.tsx");
    const localUpload = read("src/pages/upload/UploadStepB.tsx");
    const confirmation = read("src/pages/upload/UploadConfirmPanel.tsx");
    expect(page).toContain('title="上传与入库"');
    expect(page).not.toContain("UploadNamingCard");
    expect(localUpload).toContain('className="upload-dropzone upload77-dropzone"');
    expect(localUpload).toContain("className={`upload-inline-info");
    expect(localUpload).not.toContain("dropzone-security");
    expect(localUpload).not.toContain("<section");
    expect(confirmation).not.toContain("保存草稿");
    expect(confirmation).not.toContain("Import from URL");
  });
});
