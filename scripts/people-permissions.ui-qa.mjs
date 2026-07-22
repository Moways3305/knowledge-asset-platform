import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5204);
const base = `http://127.0.0.1:${port}`;
const outDir = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "people-permissions",
);
const viewports = [
  { name: "1440", width: 1440, height: 1050 },
  { name: "1280", width: 1280, height: 960 },
];
const targets = [
  {
    name: "people",
    path: "/admin/people",
    root: ".people89-page",
    table: ".pp-table",
    scenarios: ["normal", "relations-1", "relations-2", "empty", "failure", "forbidden"],
  },
  {
    name: "permissions",
    path: "/admin/permissions",
    root: ".permissions89-page",
    table: ".gp-primary-panel .gp-table",
  },
  {
    name: "company-kb",
    path: "/admin/company-kb",
    root: ".company-kb-page",
    table: ".ckb-empty-card",
    scenarios: ["normal"],
  },
];
const scenarios = ["normal", "empty", "failure", "forbidden"];
const secrets = [
  "SECRET_USER_89",
  "secret-person@example.test",
  "SECRET_PHONE_89",
  "SECRET_MEMBERSHIP_89",
  "SECRET_PROJECT_89",
  "SECRET_RULE_89",
  "SECRET_RULE_KEY_89",
  "SECRET_PROVIDER_89",
  "SECRET_AGENT_89",
  "SECRET_TOKEN_89",
];

const authMe = {
  user_id: "SECRET_USER_89",
  name: "治理管理员",
  email: "secret-person@example.test",
  status: "active",
  company_roles: ["admin"],
  active_company_role: "admin",
  is_business_user: false,
  can_discover_l5: false,
  project_memberships: [],
};
const person = {
  user_id: "SECRET_USER_89",
  name: "林顾问",
  email: "secret-person@example.test",
  phone: "SECRET_PHONE_89",
  wecom_bound: true,
  status: "active",
  created_at: "2026-07-20T01:00:00Z",
  updated_at: "2026-07-20T01:00:00Z",
  recent_session_at: "2026-07-20T01:00:00Z",
  active_session_count: 2,
  password_set: true,
  password_set_at: "2026-07-20T01:00:00Z",
  company_roles: [
    { role_id: "SECRET_RULE_89", company_role: "consultant", status: "active" },
    { role_id: "role-boss-qa", company_role: "boss", status: "active" },
    { role_id: "role-director-qa", company_role: "consulting_director", status: "active" },
  ],
  project_memberships: ["交付提升项目", "客户运营项目", "组织能力项目", "知识治理项目"].map(
    (project_name, index) => ({
      membership_id: index === 0 ? "SECRET_MEMBERSHIP_89" : `membership-qa-${index}`,
      project_id: index === 0 ? "SECRET_PROJECT_89" : `project-qa-${index}`,
      project_name,
      project_role: index === 1 ? "coach" : "consultant",
      status: "active",
      joined_at: "2026-07-20T01:00:00Z",
    }),
  ),
};
const rule = {
  rule_id: "SECRET_RULE_89",
  rule_key: "SECRET_RULE_KEY_89",
  rule_group: "access_request",
  rule_type: "numeric",
  display_name: "原文访问有效期",
  value_bool: null,
  value_number: 7,
  value_text: null,
  default_bool: null,
  default_number: 5,
  default_text: null,
  unit: "天",
  description: "控制审批后的访问时限。",
  editable: true,
  enabled: true,
  updated_by_user_id: "SECRET_USER_89",
  updated_by_name: "治理负责人",
  updated_at: "2026-07-20T01:00:00Z",
};
const agent = {
  id: "SECRET_AGENT_89",
  provider: "SECRET_PROVIDER_89",
  agent_name: "项目知识助手",
  capability: "semantic_search",
  allowed_scope: "project",
  allowed_project_id: "SECRET_PROJECT_89",
  max_confidentiality_level: "L5",
  max_ai_access_level: "A4",
  enabled: true,
  risk_level: "high",
  risk_note: "SECRET_TOKEN_89",
  created_at: "2026-07-20T01:00:00Z",
  updated_at: "2026-07-20T01:00:00Z",
};

fs.mkdirSync(outDir, { recursive: true });
let server;
let browser;
const results = [];

try {
  await build({ logLevel: "warn" });
  server = await preview({
    preview: { host: "127.0.0.1", port, strictPort: true },
    logLevel: "warn",
  });
  browser = await chromium.launch({ args: ["--disable-gpu"] });

  for (const target of targets) {
    for (const scenario of target.scenarios ?? scenarios) {
      for (const viewport of viewports) {
        const context = await browser.newContext({ viewport });
        const consoleMessages = [];
        await context.route("**/*", async (route) => {
          const url = new URL(route.request().url());
          const fulfill = (body, status = 200) =>
            route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
          if (url.pathname === "/api/v1/auth/me")
            return fulfill(
              ["people", "company-kb"].includes(target.name)
                ? {
                    ...authMe,
                    company_roles: ["boss"],
                    active_company_role: "boss",
                    is_business_user: true,
                    can_discover_l5: true,
                  }
                : authMe,
            );
          if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "qa-csrf" });

          if (url.pathname === "/api/v1/company/knowledge-base")
            return fulfill({
              exists: false,
              display_name: null,
              status: null,
              created_at: null,
              available: false,
              availability_summary: "尚未创建公司知识库",
            });

          const isPeople = url.pathname === "/api/v1/admin/people";
          const isRules = url.pathname === "/api/v1/admin/permissions/rules";
          const isAgents = url.pathname === "/api/v1/admin/permissions/agent-whitelist";
          if (isPeople || isRules || isAgents) {
            if (scenario === "forbidden")
              return fulfill({ detail: { message: "SECRET_TOKEN_89" } }, 403);
            if (scenario === "failure")
              return fulfill({ detail: { message: "SECRET_TOKEN_89" } }, 503);
          }
          if (isPeople)
            return fulfill({
              items:
                scenario === "empty"
                  ? []
                  : [
                      {
                        ...person,
                        project_memberships:
                          scenario === "relations-1"
                            ? person.project_memberships.slice(0, 1)
                            : scenario === "relations-2"
                              ? person.project_memberships.slice(0, 2)
                              : person.project_memberships,
                      },
                    ],
              total: scenario === "empty" ? 0 : 1,
            });
          if (url.pathname === `/api/v1/admin/people/${person.user_id}`) return fulfill(person);
          if (isRules)
            return fulfill({
              items: scenario === "empty" ? [] : [rule],
              total: scenario === "empty" ? 0 : 1,
            });
          if (isAgents) return fulfill({ items: scenario === "empty" ? [] : [agent] });
          if (url.pathname.startsWith("/api/"))
            return fulfill({ detail: { message: "route missing" } }, 404);
          return route.continue();
        });

        const page = await context.newPage();
        page.on("console", (message) => consoleMessages.push(message.text()));
        page.on("pageerror", (error) => consoleMessages.push(error.message));
        await page.goto(`${base}${target.path}`, { waitUntil: "networkidle" });
        await page.locator(target.root).waitFor();
        if (target.name === "people" && scenario === "normal") {
          await page.getByRole("button", { name: "查看 / 治理" }).click();
          await page.getByRole("dialog", { name: "人员治理详情" }).waitFor();
        }
        const screenshot = path.join(outDir, `${target.name}-${scenario}-${viewport.name}.png`);
        await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });

        const metrics = await page.evaluate(
          ({ scenario, secrets, target }) => {
            const root = document.documentElement;
            const html = root.innerHTML;
            const pageRoot = document.querySelector(target.root);
            const console = pageRoot?.querySelector(".gp-governance-console");
            const summary = pageRoot?.querySelector(".gp-summary-panel");
            const main = pageRoot?.querySelector(".gp-main-workspace");
            const primary = pageRoot?.querySelector(
              target.name === "people" ? ".pp-list-section" : ".gp-primary-panel",
            );
            const secondary = pageRoot?.querySelector(".gp-secondary-panel");
            const tableWraps = [
              ...(pageRoot?.querySelectorAll(".pp-table-wrap, .gp-table-wrap") ?? []),
            ];
            const rows = pageRoot?.querySelectorAll(`${target.table} tbody tr`) ?? [];
            const isPeopleDataScenario = ["normal", "relations-1", "relations-2"].includes(
              scenario,
            );
            const stateOkay =
              target.name === "company-kb"
                ? Boolean(pageRoot?.querySelector(".ckb-empty-card"))
                : isPeopleDataScenario
                  ? rows.length > 0
                  : scenario === "empty"
                    ? rows.length === 0 || [...rows].every((row) => row.querySelector(".gp-empty"))
                    : Boolean(
                        pageRoot?.querySelector("[role='alert'], .ig-empty-state, .gp-banner"),
                      );
            const summaryRect = summary?.getBoundingClientRect();
            const mainRect = main?.getBoundingClientRect();
            const primaryRect = primary?.getBoundingClientRect();
            const secondaryRect = secondary?.getBoundingClientRect();
            const summaryValues = [...(summary?.querySelectorAll(".gp-summary-value") ?? [])];
            const summaryIcons = [...(summary?.querySelectorAll(".gp-summary-icon svg") ?? [])];
            const fieldMarks = [
              ...(primary?.querySelectorAll(
                ".gp-row-icon svg, .gp-field-mark svg, .pp-field-mark svg, .pp-role-tag svg, .pp-project-role-item > svg, .gp-status svg, .pp-status-pill svg",
              ) ?? []),
            ];
            const emptyState = pageRoot?.querySelector(".gp-empty-content, .ig-empty-state");
            const emptyRect = emptyState?.getBoundingClientRect();
            const actionButtons = [...(main?.querySelectorAll("button") ?? [])];
            const drawer = pageRoot?.querySelector(".pp-detail-panel")?.getBoundingClientRect();
            const governanceRows = [
              ...(pageRoot?.querySelectorAll(
                ".pp-detail-panel .pp-project-role-list > .pp-project-role-item",
              ) ?? []),
            ];
            const relationCell = pageRoot?.querySelector(".pp-cell-projects");
            const relationSummaries =
              relationCell?.querySelectorAll(".pp-project-role-item").length;
            const relationTrigger = relationCell?.querySelector(".pp-detail-link");
            const roleCell = pageRoot?.querySelector(".pp-table tbody td:nth-child(3)");
            const roleSummaries = roleCell?.querySelectorAll(".pp-role-tag").length;
            const roleTrigger = roleCell?.querySelector(".pp-detail-link");
            return {
              overflowX: root.scrollWidth - root.clientWidth,
              safe: secrets.every((secret) => !html.includes(secret)),
              twoColumn:
                target.name === "company-kb" ||
                (Boolean(console && summaryRect && mainRect && primaryRect) &&
                  console.children.length === 2 &&
                  summaryRect.width >= 220 &&
                  summaryRect.width <= 250 &&
                  mainRect.width >= summaryRect.width * 2.25 &&
                  Math.abs(summaryRect.top - mainRect.top) <= 2),
              noWideStatusStrip: !pageRoot?.querySelector(".gp-summary"),
              iconLanguage:
                target.name === "company-kb"
                  ? Boolean(pageRoot?.querySelector(".ckb-empty-icon svg"))
                  : summaryValues.length === 4 &&
                    summaryIcons.length === summaryValues.length &&
                    (scenario !== "normal" || fieldMarks.length >= 3),
              listFirst: target.name !== "people" || Boolean(primary),
              drawerStructured:
                target.name !== "people" ||
                scenario !== "normal" ||
                Boolean(
                  drawer &&
                  drawer.width <= root.clientWidth * 0.84 &&
                  drawer.right <= root.clientWidth + 1 &&
                  governanceRows.length > 0 &&
                  governanceRows.every((row) => row.scrollWidth <= row.clientWidth + 2),
                ),
              progressiveRelations:
                target.name !== "people" ||
                (scenario === "normal"
                  ? Boolean(
                      relationSummaries === 2 &&
                      relationTrigger?.textContent?.includes("+2") &&
                      roleSummaries === 2 &&
                      roleTrigger?.textContent?.includes("+1") &&
                      pageRoot
                        ?.querySelector(".pp-detail-panel")
                        ?.textContent?.includes("知识治理项目"),
                    )
                  : scenario === "relations-1"
                    ? relationSummaries === 1 && !relationTrigger
                    : scenario === "relations-2"
                      ? relationSummaries === 2 && !relationTrigger
                      : true),
              secondaryBelow:
                target.name !== "permissions" ||
                Boolean(
                  primaryRect &&
                  secondaryRect &&
                  secondaryRect.top >= primaryRect.bottom &&
                  Math.abs(secondaryRect.width - primaryRect.width) <= 2,
                ),
              noInnerScroll: tableWraps.every((node) => node.scrollWidth - node.clientWidth <= 2),
              actionsVisible: actionButtons.every((button) => {
                const rect = button.getBoundingClientRect();
                const drawerBounds = button.closest(".pp-detail-panel")?.getBoundingClientRect();
                const bounds = drawerBounds || mainRect;
                return !bounds || (rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1);
              }),
              honestEmptyPattern:
                scenario !== "empty" ||
                Boolean(
                  emptyState?.querySelector(".gp-empty-visual svg") &&
                  emptyState.querySelector("button") &&
                  emptyRect &&
                  emptyRect.height <= 260,
                ),
              noCharts: !pageRoot?.querySelector(
                "canvas, svg[data-chart], .chart, [class*='trend']",
              ),
              compactCompanyKb:
                target.name !== "company-kb" ||
                Boolean(
                  pageRoot?.querySelector(".pp-support-section.is-empty") &&
                  pageRoot.querySelector(".ckb-empty-card")?.getBoundingClientRect().width <= 680 &&
                  pageRoot.querySelector(".ckb-empty-card button")?.getBoundingClientRect().width <
                    220,
                ),
              stateOkay,
            };
          },
          { scenario, secrets, target },
        );
        const consoleLeak = consoleMessages.some((message) =>
          secrets.some((secret) => message.includes(secret)),
        );
        results.push({
          page: target.name,
          scenario,
          viewport: viewport.name,
          screenshot,
          ...metrics,
          consoleLeak,
          pass:
            metrics.overflowX <= 2 &&
            metrics.safe &&
            metrics.twoColumn &&
            metrics.noWideStatusStrip &&
            metrics.iconLanguage &&
            metrics.listFirst &&
            metrics.drawerStructured &&
            metrics.progressiveRelations &&
            metrics.secondaryBelow &&
            metrics.noInnerScroll &&
            metrics.actionsVisible &&
            metrics.honestEmptyPattern &&
            metrics.noCharts &&
            metrics.compactCompanyKb &&
            metrics.stateOkay &&
            !consoleLeak,
        });
        await context.close();
      }
    }
  }
} finally {
  await browser?.close();
  await server?.close();
}

const reportPath = path.join(outDir, "report.json");
fs.writeFileSync(reportPath, JSON.stringify(results, null, 2));
console.log(
  JSON.stringify(
    {
      outDir,
      reportPath,
      passed: results.filter((item) => item.pass).length,
      total: results.length,
    },
    null,
    2,
  ),
);
if (results.some((item) => !item.pass)) process.exitCode = 1;
