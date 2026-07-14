import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.UI_QA_BASE || "http://localhost:5179";
const outDir = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "pbc65-home-ui-qa");
fs.mkdirSync(outDir, { recursive: true });

const auth = {
  user_id: "00000000-0000-0000-0000-000000000065",
  name: "工作台验收用户",
  email: "workbench-qa@example.test",
  status: "active",
  company_roles: ["boss"],
  is_business_user: true,
  can_discover_l5: true,
  project_memberships: [
    {
      project_id: "00000000-0000-0000-0000-0000000000a1",
      project_name: "企业知识治理项目",
      project_role: "project_manager",
      status: "active",
    },
    {
      project_id: "00000000-0000-0000-0000-0000000000b2",
      project_name: "客户交付方法沉淀",
      project_role: "consultant",
      status: "active",
    },
  ],
};

const projects = {
  items: auth.project_memberships.map((project, index) => ({
    id: project.project_id,
    name: project.project_name,
    client_name: null,
    status: "active",
    lifecycle_route_key: null,
    lifecycle_phase_key: null,
    created_at: "2026-07-14T08:00:00Z",
    can_manage: index === 0,
  })),
};

function insights(withWork) {
  return {
    title_visible: true,
    scope: "company",
    window_days: 30,
    cards: [],
    indexing: {
      index_failed: withWork ? 2 : 0,
      skipped: withWork ? 1 : 0,
      not_indexed: 0,
      parse_failed: 0,
      parse_pending: 0,
      parse_processing: 0,
      kb_init_failed: 0,
      recent_jobs: [],
    },
    access: {
      pending_original_requests: withWork ? 1 : 0,
      overdue_original_requests: 0,
      recent_auto_approved: 0,
      timeout_enabled: true,
    },
    lifecycle: {
      archive_candidates: withWork ? 2 : 0,
      archive_warnings: 0,
      needs_update: withWork ? 4 : 0,
      reuse_upgrade_candidates: withWork ? 1 : 0,
    },
    recommendations: withWork
      ? [
          {
            key: "index-recovery",
            severity: "warning",
            message: "存在需要处理的索引失败资产",
            target: "/admin/ingest",
          },
        ]
      : [],
    recent_items: withWork
      ? [
          {
            asset_id: "00000000-0000-0000-0000-0000000000c3",
            scope: "company",
            status: "active",
            title: "项目复盘方法",
            message: "知识资产已更新",
            updated_at: "2026-07-14T08:30:00Z",
          },
        ]
      : [],
  };
}

const scenarios = [
  { name: "with-todos", withWork: true, failInsights: false },
  { name: "zero-todos-with-projects", withWork: false, failInsights: false },
  { name: "insights-error", withWork: false, failInsights: true },
];
const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1920", width: 1920, height: 1080 },
];

const browser = await chromium.launch();
const results = [];

for (const scenario of scenarios) {
  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport });
    await context.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url());
      const fulfill = (body, status = 200) =>
        route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

      if (url.pathname === "/api/v1/auth/me") return fulfill(auth);
      if (url.pathname === "/api/v1/projects") return fulfill(projects);
      if (url.pathname === "/api/v1/knowledge/ops-insights") {
        return scenario.failInsights
          ? fulfill({ detail: { message: "运营状态暂时不可用" } }, 503)
          : fulfill(insights(scenario.withWork));
      }
      if (url.pathname === "/api/v1/ingest/pending") {
        return fulfill({
          items: scenario.withWork ? [{}, {}, {}] : [],
          total: scenario.withWork ? 3 : 0,
        });
      }
      if (url.pathname === "/api/v1/reviews") {
        return fulfill({
          items: scenario.withWork ? [{ status: "pending" }] : [],
          total: scenario.withWork ? 1 : 0,
        });
      }
      if (url.pathname === "/api/v1/original-access/requests") {
        const hasInboxWork = scenario.withWork && url.searchParams.get("box") === "inbox";
        return fulfill({
          items: hasInboxWork ? [{ status: "pending" }] : [],
          total: hasInboxWork ? 1 : 0,
        });
      }
      return fulfill({ detail: { message: "not configured for UI QA" } }, 404);
    });

    const page = await context.newPage();
    await page.goto(base, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "我的待办" }).waitFor();
    if (scenario.name === "with-todos") {
      await page.getByRole("link", { name: /处理索引失败/ }).waitFor();
    } else if (scenario.name === "zero-todos-with-projects") {
      await page.getByText("今天没有待处理事项").waitFor();
    } else {
      await page.getByText("部分待办数据未加载成功").waitFor();
    }

    const metrics = await page.evaluate(() => {
      const root = document.documentElement;
      const unnamedActions = [...document.querySelectorAll("a, button")].filter(
        (element) => !(element.textContent || element.getAttribute("aria-label") || "").trim(),
      ).length;
      const clippedLabels = [...document.querySelectorAll("a, button")].filter(
        (element) => element.scrollWidth > element.clientWidth + 2,
      ).length;
      return {
        overflowX: root.scrollWidth - root.clientWidth,
        unnamedActions,
        clippedLabels,
      };
    });
    await page.screenshot({
      path: path.join(outDir, `${scenario.name}-${viewport.name}.png`),
      fullPage: true,
    });
    results.push({ scenario: scenario.name, viewport: viewport.name, ...metrics });
    await context.close();
  }
}

await browser.close();
fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify({ outDir, results }, null, 2));

if (
  results.some((result) => result.overflowX > 2 || result.unnamedActions || result.clippedLabels)
) {
  process.exit(1);
}
