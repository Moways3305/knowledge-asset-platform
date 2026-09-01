import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5211);
const externalBase = process.env.UI_QA_BASE?.replace(/\/$/, "") || null;
const base = externalBase || `http://127.0.0.1:${port}`;
const outDir = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "directory-governance",
);
fs.mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1024", width: 1024, height: 900 },
  { name: "768", width: 768, height: 900 },
  { name: "390", width: 390, height: 844 },
];

const directory = (
  directoryKey,
  scope,
  displayName,
  namingCode,
  defaultConfidentiality,
  sortOrder,
) => ({
  directory_key: directoryKey,
  scope,
  display_name: displayName,
  description: `${displayName}资料的正式归属与命名规则`,
  naming_code: namingCode,
  default_confidentiality: defaultConfidentiality,
  enabled: true,
  sort_order: sortOrder,
});

const originalCenter = {
  published: {
    version: 8,
    status: "published",
    base_published_version: 7,
    config: { schema_version: 2, enforced: true, project_codes: [], categories: [] },
    updated_at: "2026-08-31T08:00:00Z",
    published_at: "2026-08-31T08:00:00Z",
  },
  draft: {
    version: 9,
    status: "draft",
    base_published_version: 8,
    config: {
      schema_version: 2,
      enforced: true,
      project_codes: [],
      categories: [],
      directories: [
        directory("company.methodology", "company", "02 方法论", "方法论", "L2", 20),
        directory("company.client_cases", "company", "04 客户案例", "案例", "L3", 40),
        directory("project.deliverables", "project", "03 交付成果", "交付成果", "L2", 30),
        directory("project.retrospective", "project", "05 项目复盘", "项目复盘", "L2", 50),
      ],
    },
    updated_at: "2026-09-01T08:00:00Z",
    published_at: null,
  },
  projects: [],
};

const migration = {
  overview: {
    total: 2,
    migrated: 0,
    clear_match: 1,
    manual_required: 1,
    no_candidate: 1,
    failed: 0,
    rule_version: 8,
  },
  items: [
    {
      id: "migration-safe-1",
      asset_title: "历史项目复盘材料",
      scope: "project",
      project_id: "project-safe-1",
      project_name: "华东增长项目",
      old_category: "历史类别：项目复盘",
      suggested_directory_key: "project.retrospective",
      suggested_directory_name: "05 项目复盘",
      candidate_source: "legacy_metadata",
      confidence: "clear",
      status: "pending",
      failure_code: null,
      updated_at: "2026-09-01T08:00:00Z",
    },
    {
      id: "migration-safe-2",
      asset_title: "待人工识别资料",
      scope: "company",
      project_id: null,
      project_name: null,
      old_category: null,
      suggested_directory_key: null,
      suggested_directory_name: null,
      candidate_source: "none",
      confidence: "manual",
      status: "pending",
      failure_code: null,
      updated_at: "2026-09-01T08:00:00Z",
    },
  ],
  total: 2,
  directories: originalCenter.draft.config.directories,
};

const projectSettingsSource = fs.readFileSync(
  path.join(process.cwd(), "src/pages/ProjectSettingsPage.tsx"),
  "utf8",
);
const projectCodeOwnedByProjectSettings =
  projectSettingsSource.includes("项目代码") && projectSettingsSource.includes("project_code");

let server = null;
let browser = null;
const results = [];
try {
  if (!externalBase) {
    await build({ logLevel: "warn" });
    server = await preview({
      preview: { port, host: "127.0.0.1", strictPort: true },
      logLevel: "warn",
    });
  }
  browser = await chromium.launch({ args: ["--disable-gpu"] });

  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport });
    const center = structuredClone(originalCenter);
    let savedPayload = null;
    let publishPayload = null;
    let migrationCalls = 0;
    await context.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url());
      const method = route.request().method();
      const fulfill = (body, status = 200) =>
        route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "ui-qa" });
      if (url.pathname === "/api/v1/auth/me")
        return fulfill({
          user_id: "directory-governance-user",
          name: "目录治理验收用户",
          email: "directory-governance@example.test",
          status: "active",
          company_roles: ["boss"],
          active_company_role: "boss",
          is_business_user: true,
          can_discover_l5: true,
          project_memberships: [],
        });
      if (url.pathname === "/api/v1/admin/naming-rules/draft" && method === "PUT") {
        savedPayload = route.request().postDataJSON();
        center.draft = {
          ...center.draft,
          config: { ...center.draft.config, directories: savedPayload.directories },
        };
        return fulfill(center.draft);
      }
      if (url.pathname === "/api/v1/admin/naming-rules/publish" && method === "POST") {
        publishPayload = route.request().postDataJSON();
        center.published = {
          ...center.draft,
          status: "published",
          published_at: "2026-09-01T10:00:00Z",
        };
        return fulfill(center);
      }
      if (url.pathname === "/api/v1/admin/naming-rules") return fulfill(center);
      if (url.pathname === "/api/v1/admin/directory-migration") {
        migrationCalls += 1;
        return fulfill(migration);
      }
      return fulfill({ detail: { message: "UI QA route not configured" } }, 404);
    });

    const page = await context.newPage();
    await page.goto(`${base}/admin/naming-rules`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "目录治理" }).waitFor();

    const companyCard = page
      .locator(".naming-project-settings")
      .filter({ hasText: "company.methodology" });
    await companyCard.getByLabel("目录名称").fill("02 方法与工具");
    await companyCard.getByLabel("目录说明").fill("模型、工具与可复用方法");
    await companyCard.getByLabel("命名短码").fill("方法工具");
    await companyCard.getByLabel("默认密级").selectOption("L4");
    await companyCard.getByLabel("排序").fill("25");
    await companyCard.getByLabel("启用目录").uncheck();
    await page.getByRole("button", { name: /保存草稿/ }).click();
    await page.getByText("目录草稿已保存；发布前不会影响新入库资料。").waitFor();

    await page.getByRole("tab", { name: "项目目录" }).click();
    await page.locator('input[value="03 交付成果"]').waitFor();
    const projectDirectoryVisible = await page.locator('input[value="05 项目复盘"]').isVisible();

    await page.getByRole("button", { name: /历史待治理/ }).click();
    await page.getByText(/总计 2 · 待人工 1 · 无明确候选 1/).waitFor();
    const migrationVisible =
      (await page.getByText("历史项目复盘材料").isVisible()) &&
      (await page.getByText("05 项目复盘", { exact: true }).last().isVisible());

    await page.getByRole("button", { name: /发布正式目录/ }).click();
    await page.getByText("正式目录已发布，新上传和项目发布将立即使用本版本。").waitFor();

    const screenshot = path.join(outDir, `directory-governance-${viewport.name}.png`);
    await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
    const metrics = await page.evaluate(() => {
      const root = document.documentElement;
      const bodyText = document.body.innerText;
      const visibleControls = [
        ...document.querySelectorAll(
          ".product-page button, .product-page input, .product-page select, .product-page a",
        ),
      ].filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      });
      return {
        overflowX: root.scrollWidth - root.clientWidth,
        clippedControls: visibleControls.filter((element) => {
          const rect = element.getBoundingClientRect();
          return rect.left < -2 || rect.right > root.clientWidth + 2;
        }).length,
        retiredManagementAbsent:
          !/管理目录类别|新增类别|资产类型配置|管理项目代码|项目代码全局草稿/.test(bodyText),
        formalDirectoryOnly:
          document.querySelectorAll(".naming-directory-governance").length === 1 &&
          document.querySelectorAll(".naming-directory-list article").length === 2,
      };
    });

    const edited = savedPayload?.directories?.find(
      (item) => item.directory_key === "company.methodology",
    );
    const payloadValid = Boolean(
      savedPayload?.expected_base_version === 8 &&
      edited?.display_name === "02 方法与工具" &&
      edited?.description === "模型、工具与可复用方法" &&
      edited?.naming_code === "方法工具" &&
      edited?.default_confidentiality === "L4" &&
      edited?.sort_order === 25 &&
      edited?.enabled === false &&
      !Object.hasOwn(savedPayload ?? {}, "categories") &&
      !Object.hasOwn(savedPayload ?? {}, "project_codes") &&
      publishPayload?.expected_base_version === 8,
    );
    const result = {
      viewport: viewport.name,
      screenshot,
      payloadValid,
      migrationVisible,
      migrationCalls,
      projectDirectoryVisible,
      projectCodeOwnedByProjectSettings,
      ...metrics,
    };
    result.passed =
      result.overflowX <= 2 &&
      result.clippedControls === 0 &&
      result.retiredManagementAbsent &&
      result.formalDirectoryOnly &&
      result.payloadValid &&
      result.migrationVisible &&
      result.migrationCalls === 1 &&
      result.projectDirectoryVisible &&
      result.projectCodeOwnedByProjectSettings;
    results.push(result);
    await context.close();
  }
} finally {
  await browser?.close();
  await server?.close();
}

const report = {
  generatedAt: new Date().toISOString(),
  total: results.length,
  passed: results.filter((result) => result.passed).length,
  results,
};
fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
if (results.some((result) => !result.passed)) process.exitCode = 1;
