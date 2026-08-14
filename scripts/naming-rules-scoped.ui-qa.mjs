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
  "naming-rules-unified",
);
fs.mkdirSync(outDir, { recursive: true });
const alpha = "20000000-0000-0000-0000-000000000001";
const beta = "20000000-0000-0000-0000-000000000002";
const category = (id, scope, primary, secondary, order) => ({
  id,
  scope,
  primary,
  secondary,
  prefix: scope === "project" ? secondary : `${primary}-${secondary}`,
  description: `${secondary}资料归档规范`,
  asset_type: scope === "project" ? "deliverable" : "methodology",
  default_confidentiality: "L2",
  enabled: true,
  sort_order: order,
});
const companyCategories = Array.from({ length: 12 }, (_, index) =>
  category(
    `10000000-0000-0000-0000-${String(index + 1).padStart(12, "0")}`,
    "company",
    index < 7 ? "方法论" : "洞察",
    `公司类别${index + 1}`,
    (index + 1) * 10,
  ),
);
const projectCategories = [
  category("30000000-0000-0000-0000-000000000001", "project", "项目资料", "交付成果", 10),
  category("30000000-0000-0000-0000-000000000002", "project", "项目资料", "访谈纪要", 20),
];
const makeCenter = (emptyProject = false) => ({
  published: {
    version: 4,
    status: "published",
    base_published_version: 3,
    config: { schema_version: 1, enforced: true, project_codes: [], categories: [] },
    updated_at: "2026-08-08T08:00:00Z",
    published_at: "2026-08-08T08:00:00Z",
  },
  draft: {
    version: 5,
    status: "draft",
    base_published_version: 4,
    config: {
      schema_version: 1,
      enforced: true,
      project_codes: [
        { project_id: alpha, code: "ALPHA-26", enabled: true, default_confidentiality: "L2" },
        { project_id: beta, code: "BETA-26", enabled: true, default_confidentiality: "L3" },
      ],
      categories: [...companyCategories, ...(emptyProject ? [] : projectCategories)],
    },
    updated_at: "2026-08-10T08:00:00Z",
    published_at: null,
  },
  projects: [
    {
      id: alpha,
      name: "Alpha咨询",
      status: "active",
      project_code: "ALPHA-26",
      project_code_active: true,
      default_confidentiality: "L2",
    },
    {
      id: beta,
      name: "Beta转型",
      status: "active",
      project_code: "BETA-26",
      project_code_active: true,
      default_confidentiality: "L3",
    },
  ],
});
const scenarios = [
  { name: "governance-landing", width: 1440, action: "landing" },
  { name: "company-scope", width: 1440, action: "company" },
  { name: "unified-project-scope", width: 1440, action: "project" },
  { name: "mid-unified-project", width: 1024, action: "project" },
  { name: "unified-project-empty", width: 1440, action: "empty" },
  { name: "many-categories-search", width: 1440, action: "many" },
  { name: "category-editor", width: 1440, action: "editor" },
  { name: "initialization-wizard", width: 1440, action: "initialize" },
  { name: "project-code-facts", width: 1440, action: "codes" },
  { name: "save-success", width: 1440, action: "save" },
  { name: "publish-success", width: 1440, action: "publish" },
  { name: "no-permission", width: 1440, action: "denied" },
  { name: "load-failure", width: 1440, action: "failure" },
  { name: "narrow-unified-project", width: 390, action: "project" },
];

let server = null;
if (!externalBase) {
  await build({ logLevel: "silent" });
  server = await preview({ preview: { port, host: "127.0.0.1" }, logLevel: "silent" });
}
const browser = await chromium.launch({ args: ["--disable-gpu"] });
const results = [];
try {
  for (const scenario of scenarios) {
    const context = await browser.newContext({
      viewport: { width: scenario.width, height: scenario.width < 500 ? 844 : 980 },
    });
    const center = makeCenter(scenario.action === "empty");
    await context.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url());
      const method = route.request().method();
      const fulfill = (body, status = 200) =>
        route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "ui-qa" });
      if (url.pathname === "/api/v1/auth/me")
        return fulfill({
          user_id: "90000000-0000-0000-0000-000000000001",
          name: "命名治理验收用户",
          email: "hidden@example.test",
          status: "active",
          company_roles: scenario.action === "denied" ? ["admin"] : ["boss"],
          active_company_role: scenario.action === "denied" ? "admin" : "boss",
          is_business_user: scenario.action !== "denied",
          can_discover_l5: scenario.action !== "denied",
          project_memberships: [],
        });
      if (url.pathname === "/api/v1/admin/naming-rules/draft" && method === "PUT")
        return fulfill(center.draft);
      if (url.pathname === "/api/v1/admin/naming-rules/publish" && method === "POST")
        return fulfill({
          ...center,
          published: { ...center.draft, status: "published", published_at: "2026-08-10T10:00:00Z" },
        });
      if (url.pathname === "/api/v1/admin/naming-rules")
        return scenario.action === "failure"
          ? fulfill({ detail: { message: "命名规则服务暂时不可用" } }, 503)
          : fulfill(center);
      return fulfill({ detail: { message: "not mocked" } }, 404);
    });
    const page = await context.newPage();
    await page.goto(`${base}/admin/naming-rules`, { waitUntil: "networkidle" });
    if (["project", "empty", "editor", "initialize", "codes"].includes(scenario.action))
      await page.getByRole("button", { name: "全项目通用规范" }).click();
    if (scenario.action === "project" || scenario.action === "empty") {
      await page.getByRole("button", { name: "管理目录类别" }).click();
      if (scenario.action === "project") {
        await page.getByText("交付成果", { exact: true }).waitFor();
        if (await page.getByText(/公司类别/).count())
          throw new Error("company category leaked into unified project scope");
      } else await page.getByText("当前范围还没有目录类别").waitFor();
    } else if (scenario.action === "company" || scenario.action === "many") {
      await page.getByRole("button", { name: "管理目录类别" }).click();
      await page.getByText("方法论 / 公司类别1", { exact: true }).waitFor();
      if (scenario.action === "many") {
        await page.getByText("第 1 / 2 页").waitFor();
        await page.getByLabel("搜索目录类别").fill("公司类别12");
        await page.getByText("洞察 / 公司类别12", { exact: true }).waitFor();
      }
    } else if (scenario.action === "editor") {
      await page.getByRole("button", { name: "管理目录类别" }).click();
      await page.getByRole("button", { name: "新增类别" }).click();
      await page.getByText("全项目通用规范", { exact: true }).last().waitFor();
    } else if (scenario.action === "initialize") {
      await page.getByRole("button", { name: "初始化标准目录" }).click();
      await page.getByRole("button", { name: "继续" }).click();
      await page.getByText("这一步不会直接发布").waitFor();
    } else if (scenario.action === "codes") {
      await page.getByRole("button", { name: "管理项目代码" }).click();
      await page.getByText("Alpha咨询", { exact: true }).waitFor();
      await page.getByText("Beta转型", { exact: true }).waitFor();
    } else if (scenario.action === "save") {
      await page.getByRole("button", { name: "保存草稿" }).click();
      await page.getByText("草稿已保存，尚未发布，不影响新入库资料。").waitFor();
    } else if (scenario.action === "publish") {
      await page.getByRole("button", { name: "发布规则" }).click();
      await page.getByText("发布请求已完成；新版本仅影响此后确认入库的资料。").waitFor();
    } else if (scenario.action === "failure")
      await page.getByText("命名规则服务暂时不可用").waitFor();
    else if (scenario.action !== "landing")
      await page
        .getByText(/无权|权限|访问/)
        .first()
        .waitFor();
    const file = path.join(outDir, `${scenario.name}.png`);
    await page.screenshot({ path: file });
    const metrics = await page.evaluate(() => {
      const root = document.documentElement;
      const actions = [
        ...document.querySelectorAll(".product-page button, [role='dialog'] button"),
      ].filter((button) => button.getBoundingClientRect().width > 0);
      return {
        overflowX: root.scrollWidth - root.clientWidth,
        noSummaryMatrix: !document.querySelector(".naming-overview"),
        actionsReachable: actions.every((button) => {
          const rect = button.getBoundingClientRect();
          return rect.left >= -2 && rect.right <= root.clientWidth + 2;
        }),
      };
    });
    results.push({
      scenario: scenario.name,
      viewport: scenario.width,
      screenshot: file,
      ...metrics,
      passed: metrics.overflowX <= 2 && metrics.noSummaryMatrix && metrics.actionsReachable,
    });
    await context.close();
  }
} finally {
  await browser.close();
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
