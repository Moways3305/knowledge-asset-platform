import { describe, expect, it } from "vitest";

const sourceModules = import.meta.glob(
  ["../App.tsx", "../{pages,components,styles,api}/**/*.{ts,tsx,css}"],
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

  it("keeps every administration workspace on the shared page heading hierarchy", () => {
    for (const page of [
      "AdminIngestPage.tsx",
      "AdminWecomScanPage.tsx",
      "AdminWeKnoraModelsPage.tsx",
      "AdminAuditPage.tsx",
      "AdminAuthSecurityPage.tsx",
      "AdminAlertSettingsPage.tsx",
      "AdminPermissionsPage.tsx",
      "AdminPeoplePage.tsx",
      "AdminNamingRulesPage.tsx",
      "AdminCompanyKbPage.tsx",
    ]) {
      const source = read(`src/pages/${page}`);
      expect(source).toContain("<ProductPage");
      expect(source).toContain("<PageHeader");
    }
  });

  it("keeps the alert settings workspace focused on rules without loading notification history", () => {
    const source = read("src/pages/AdminAlertSettingsPage.tsx");
    expect(source).not.toContain("fetchAlertNotifications");
    expect(source).not.toContain("通知记录");
    expect(read("src/api/admin.ts")).toContain("fetchAlertNotifications");
  });

  it("keeps the admin operations page on the safe two-column reference contract", () => {
    const source = read("src/pages/AdminIngestPage.tsx");
    expect(source).toContain('className="ao84-console"');
    expect(source).toContain('className="ao84-panel ao84-summary"');
    expect(source).toContain('className="ao84-panel ao84-failures"');
    expect(source).toContain('aria-current="page"');
    expect(source).toContain("当前没有索引失败任务");
    expect(source).not.toContain("source_file_name");
    expect(source).not.toContain("project_name");
    expect(source).not.toContain("owner_name");
  });

  it("keeps audit action codes and raw markup patterns out of the rendered workspace", () => {
    const source = read("src/pages/AdminAuditPage.tsx");
    expect(source).not.toContain("au-cell-raw");
    expect(source).not.toContain("<details>");
    expect(source).toContain("auditActionLabel(item.action)");
  });

  it("keeps governance model selectors read-only with an explanation", () => {
    const source = read("src/components/UnifiedModelConnectionsSection.tsx");
    expect(source).toContain("disabled={!effectiveCanEdit || loading");
    expect(source).toContain("当前身份仅可查看，修改需系统管理员");
  });

  it("keeps model administration on the overview, drawer, and modal contract", () => {
    const page = read("src/pages/AdminWeKnoraModelsPage.tsx");
    const connections = read("src/components/UnifiedModelConnectionsSection.tsx");
    expect(page).toContain('className="mf-overview-grid"');
    expect(page).toContain('title="管理知识库配置"');
    expect(page).toContain("<DetailDrawer");
    expect(page).toContain("<TaskModal");
    expect(connections).toContain('className="mf-connection-card"');
    expect(connections).toContain("<TaskModal");
  });

  it("keeps personal knowledge as a compact table with controlled write dialogs", () => {
    const personal = read("src/pages/MyKnowledgePage.tsx");
    expect(personal).toContain('className="mk83-table"');
    expect(personal).toContain("<ConfirmDialog");
    expect(personal).toContain('"已提交，等待项目经理确认"');
    expect(personal).not.toContain("<Disclosure");
    expect(personal).not.toContain("<WorkbuddyAccessCard");
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
      "/admin",
      "/admin/ingest",
      "/admin/wecom-scan",
      "/admin/weknora-models",
      "/admin/audit",
      "/admin/auth-security",
      "/admin/alert-settings",
      "/admin/people",
      "/admin/permissions",
      "/admin/naming-rules",
      "/admin/company-kb",
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
    expect(localUpload).toContain('aria-labelledby="local-pending-title"');
    expect(confirmation).not.toContain("保存草稿");
    expect(confirmation).not.toContain("Import from URL");
  });
});
