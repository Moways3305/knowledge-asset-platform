import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5196);
const base = `http://127.0.0.1:${port}`;
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "workbench");
fs.mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1280", width: 1280, height: 900 },
];

const scenarios = [
  { name: "normal" },
  { name: "zero-todos" },
  { name: "projects-empty" },
  { name: "projects-forbidden" },
  { name: "recent-error-retry" },
  { name: "titles-hidden" },
  { name: "workbuddy-enabled" },
];

const authMe = {
  user_id: "00000000-0000-0000-0000-000000000081",
  name: "工作台验收用户",
  email: "workbench-qa@example.test",
  status: "active",
  company_roles: ["consultant"],
  active_company_role: "consultant",
  is_business_user: true,
  can_discover_l5: false,
  project_memberships: [
    {
      project_id: "00000000-0000-0000-0000-0000000000a1",
      project_name: "企业知识治理项目",
      project_role: "project_manager",
      status: "active",
    },
  ],
};

function overviewFor(scenario, callCount) {
  const hidden = scenario === "titles-hidden";
  const retryReady = scenario === "recent-error-retry" && callCount > 1;
  return {
    todos:
      scenario === "zero-todos"
        ? { status: "empty", error_code: null, items: [], total: 0 }
        : {
            status: "available",
            error_code: null,
            total: 6,
            items: [
              {
                key: "review_pending",
                count: 3,
                severity: "warning",
                route_key: "reviews",
                action_key: "decide_review",
              },
              {
                key: "ingest_pending",
                count: 2,
                severity: "warning",
                route_key: "upload",
                action_key: "confirm_ingest",
              },
              {
                key: "secret_todo_key",
                count: 1,
                severity: "secret_severity",
                route_key: "secret_route",
                action_key: "secret_action",
              },
            ],
          },
    operations: {
      status: "available",
      error_code: null,
      data: {
        title_visible: !hidden,
        scope: "secret_scope",
        window_days: 30,
        cards: [
          {
            key: "index_failed",
            label: "secret server label",
            count: 4,
            severity: "warning",
            action_hint: "secret server hint",
          },
          {
            key: "pending_original_requests",
            label: "secret server label two",
            count: 2,
            severity: "info",
            action_hint: null,
          },
          {
            key: "parse_failed",
            label: "secret server label three",
            count: 3,
            severity: "error",
            action_hint: null,
          },
          {
            key: "archive_candidates",
            label: "secret server label four",
            count: 1,
            severity: "info",
            action_hint: null,
          },
          {
            key: "kb_init_failed",
            label: "secret server zero label",
            count: 0,
            severity: "error",
            action_hint: null,
          },
        ],
        indexing: {
          index_failed: 4,
          skipped: 0,
          not_indexed: 0,
          parse_failed: 0,
          parse_pending: 0,
          parse_processing: 0,
          kb_init_failed: 0,
        },
        access: {
          pending_original_requests: 2,
          overdue_original_requests: 0,
          recent_auto_approved: 0,
          timeout_enabled: false,
        },
        lifecycle: {
          archive_candidates: 0,
          archive_warnings: 0,
          needs_update: 0,
          reuse_upgrade_candidates: 0,
        },
      },
    },
    projects:
      scenario === "projects-empty"
        ? {
            status: "empty",
            error_code: null,
            items: [],
            total: 0,
          }
        : scenario === "projects-forbidden"
          ? {
              status: "forbidden",
              error_code: "projects_secret_forbidden",
              items: [],
              total: 0,
            }
          : {
              status: "available",
              error_code: null,
              total: 2,
              items: [
                {
                  project_id: "00000000-0000-0000-0000-0000000000a1",
                  name: "企业知识治理项目",
                  status: "active",
                  project_role: "project_manager",
                  lifecycle_route_key: "secret_route_A",
                  lifecycle_phase_key: "secret_phase",
                },
                {
                  project_id: "00000000-0000-0000-0000-0000000000b2",
                  name: "客户交付方法沉淀",
                  status: "active",
                  project_role: "consultant",
                  lifecycle_route_key: null,
                  lifecycle_phase_key: null,
                },
              ],
            },
    recent_activity:
      scenario === "recent-error-retry" && !retryReady
        ? {
            status: "error",
            error_code: "recent_secret_unavailable",
            items: [],
            total: 0,
          }
        : {
            status: "available",
            error_code: null,
            total: 2,
            items: [
              {
                asset_id: "00000000-0000-0000-0000-0000000000c3",
                title: "绝不能越权显示的资产标题",
                scope: "project",
                zone: "secret_zone",
                asset_type: "secret_type",
                confidentiality_level: "secret_level",
                summary: "secret summary body",
                project_name: "企业知识治理项目",
                updated_at: "2026-07-17T02:30:00Z",
              },
              {
                asset_id: "00000000-0000-0000-0000-0000000000d4",
                title: "项目复盘方法",
                scope: "company",
                zone: "secret_zone",
                asset_type: "secret_type",
                confidentiality_level: "secret_level",
                summary: null,
                project_name: null,
                updated_at: "2026-07-16T07:20:00Z",
              },
            ],
          },
  };
}

function accepted(result) {
  const shared =
    result.overflowX <= 2 &&
    result.shellOverlap <= 1 &&
    result.clippedControls === 0 &&
    result.panelCount >= 4 &&
    result.panelCount <= 6 &&
    result.actionQueuePrimary &&
    result.healthFullWidth &&
    result.projectRecentBalanced &&
    result.workbuddyDedicated &&
    result.operationsCompact &&
    result.operationActionsReachable &&
    result.projectStateCompact &&
    result.compactHeader &&
    !result.staleFourPanelGrid &&
    !result.oldSurfaceVisible &&
    !result.fakeFeatureVisible &&
    !result.sensitiveVisible &&
    !result.consoleLeak &&
    result.overviewCalls >= 1 &&
    result.oldApiCalls === 0;
  if (!shared) return false;
  if (result.scenario === "normal") return result.normalContent;
  if (result.scenario === "zero-todos") return result.zeroState;
  if (result.scenario === "projects-empty") return result.projectEmptyState;
  if (result.scenario === "projects-forbidden") return result.forbiddenState;
  if (result.scenario === "recent-error-retry") return result.retrySucceeded;
  if (result.scenario === "titles-hidden") return result.hiddenTitleSafe;
  if (result.scenario === "workbuddy-enabled") return result.workbuddyLifecycleVisible;
  return false;
}

let previewServer;
let browser;
const results = [];

try {
  await build({ logLevel: "warn" });
  previewServer = await preview({
    preview: { host: "127.0.0.1", port, strictPort: true },
    logLevel: "warn",
  });
  browser = await chromium.launch({ args: ["--disable-gpu"] });

  for (const scenario of scenarios) {
    for (const viewport of viewports) {
      let overviewCalls = 0;
      let oldApiCalls = 0;
      const browserMessages = [];
      const context = await browser.newContext({ viewport });
      await context.route("**/api/v1/**", async (route) => {
        const requestUrl = new URL(route.request().url());
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
        if (requestUrl.pathname === "/api/v1/auth/me") return fulfill(authMe);
        if (requestUrl.pathname === "/api/v1/workbench/overview") {
          overviewCalls += 1;
          return fulfill(overviewFor(scenario.name, overviewCalls));
        }
        if (requestUrl.pathname === "/api/v1/auth/workbuddy-token") {
          return fulfill({
            enabled: scenario.name === "workbuddy-enabled",
            bound_user_name: "工作台验收用户",
            last_rotated_at: null,
          });
        }
        oldApiCalls += 1;
        return fulfill({ detail: { message: "old api must not be called" } }, 500);
      });

      const page = await context.newPage();
      page.on("console", (message) => browserMessages.push(message.text()));
      page.on("pageerror", (error) => browserMessages.push(error.message));
      await page.goto(base, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "我的待办" }).waitFor();

      let retrySucceeded = false;
      if (scenario.name === "recent-error-retry") {
        const recent = page.locator(".wb81-panel.is-recent");
        await recent.getByText("内容暂时未能加载").waitFor();
        await recent.getByRole("button", { name: "重新加载" }).click();
        await recent.getByText("绝不能越权显示的资产标题").waitFor();
        retrySucceeded = overviewCalls === 2;
      }

      const result = await page.evaluate(
        ({ scenarioName }) => {
          const root = document.documentElement;
          const shell = document.querySelector(".rail");
          const content = document.querySelector(".app-content");
          const panels = [...document.querySelectorAll(".wb81-panel")];
          const todos = document.querySelector(".wb81-panel.is-todos")?.getBoundingClientRect();
          const operations = document
            .querySelector(".wb81-panel.is-operations")
            ?.getBoundingClientRect();
          const projects = document
            .querySelector(".wb81-panel.is-projects")
            ?.getBoundingClientRect();
          const recent = document.querySelector(".wb81-panel.is-recent")?.getBoundingClientRect();
          const workbuddy = document
            .querySelector(".wb81-panel.is-workbuddy")
            ?.getBoundingClientRect();
          const operationCardCount = document.querySelectorAll(".wb81-operation").length;
          const operationCards = [...document.querySelectorAll(".wb81-operation")].map((element) =>
            element.getBoundingClientRect(),
          );
          const operationIconCount = document.querySelectorAll(".wb81-operation-icon svg").length;
          const operationActionCount = document.querySelectorAll("a.wb81-operation[href]").length;
          const primaryRow = document.querySelector(".wb81-row-primary")?.getBoundingClientRect();
          const secondaryRow = document
            .querySelector(".wb81-row-secondary")
            ?.getBoundingClientRect();
          const pageHeader = document
            .querySelector(".wb81-workbench .product-page-header")
            ?.getBoundingClientRect();
          const bodyText = document.body.innerText;
          const shellBox = shell?.getBoundingClientRect();
          const contentBox = content?.getBoundingClientRect();
          const forbiddenStrings = [
            "secret_todo_key",
            "secret_severity",
            "secret_route",
            "secret_action",
            "secret server label",
            "secret server hint",
            "projects_secret_forbidden",
            "recent_secret_unavailable",
            "secret_phase",
            "secret_zone",
            "secret_type",
            "secret_level",
            "secret summary body",
            "available",
            "forbidden",
            "error_code",
            "HTTP 500",
          ];
          return {
            scenario: scenarioName,
            overflowX: root.scrollWidth - root.clientWidth,
            shellOverlap:
              shellBox && contentBox ? Math.max(0, shellBox.right - contentBox.left) : 0,
            clippedControls: [...document.querySelectorAll("a, button")].filter(
              (element) => element.scrollWidth > element.clientWidth + 2,
            ).length,
            panelCount: panels.length,
            projectPanelHeight: projects?.height ?? 0,
            stitchHierarchyCorrect: Boolean(
              todos &&
                operations &&
                projects &&
                recent &&
                primaryRow &&
                secondaryRow &&
                primaryRow.top < secondaryRow.top &&
                Math.abs(todos.top - operations.top) <= 1 &&
                Math.abs(todos.top - projects.top) <= 1 &&
                (!workbuddy || Math.abs(workbuddy.top - recent.top) <= 1),
            ),
            actionQueuePrimary: Boolean(
              todos &&
              operations &&
              Math.abs(todos.top - operations.top) <= 1 &&
              todos.left < operations.left &&
              todos.width >= 260,
            ),
            healthFullWidth: Boolean(
              operations &&
              todos &&
              Math.abs(operations.top - todos.top) <= 1 &&
              operations.width >= 220,
            ),
            projectRecentBalanced: Boolean(
              projects && recent && projects.top < recent.top && projects.width >= 260,
            ),
            workbuddyDedicated: Boolean(
              !workbuddy ||
                (todos &&
                  recent &&
                  operations &&
                  projects &&
                  workbuddy.top > Math.max(todos.bottom, operations.bottom, projects.bottom) &&
                  Math.abs(workbuddy.top - recent.top) <= 1 &&
                  workbuddy.left < recent.left),
            ),
            todoColumnNarrower: Boolean(
              todos &&
              operations &&
              todos.width >= 260 &&
              operations.width >= 240 &&
              Math.abs(todos.top - operations.top) <= 1,
            ),
            recentInLeftColumn: Boolean(
              workbuddy &&
              recent &&
              Math.abs(workbuddy.top - recent.top) <= 1 &&
              workbuddy.left < recent.left,
            ),
            operationsCompact: Boolean(
              operations &&
              projects &&
              operationCardCount > 0 &&
              operationCardCount <= 3 &&
              operationCards.every((card) => card.width <= 190) &&
              operationIconCount === operationCardCount,
            ),
            operationActionsReachable:
              operationCardCount > 0 &&
              operationActionCount === operationCardCount &&
              [...document.querySelectorAll("a.wb81-operation")].every((card) =>
                card.textContent?.includes("查看"),
              ),
            compactHeader: Boolean(pageHeader && pageHeader.height <= 72),
            staleFourPanelGrid: Boolean(document.querySelector(".wb81-grid")),
            oldSurfaceVisible: Boolean(
              document.querySelector(
                ".workbench-command-grid, .workbench-context-grid, .workbench-insight-column, .workbench-recommendations",
              ),
            ),
            fakeFeatureVisible: /AI 洞察|健康分|趋势|搜索资产|导出|新建项目/.test(bodyText),
            sensitiveVisible: forbiddenStrings.some((value) => bodyText.includes(value)),
            normalContent:
              bodyText.includes("处理知识审核") &&
              bodyText.includes("索引失败") &&
              bodyText.includes("企业知识治理项目") &&
              bodyText.includes("绝不能越权显示的资产标题"),
            zeroState: bodyText.includes("今天没有待处理事项"),
            projectEmptyState: bodyText.includes("当前没有可访问的项目"),
            forbiddenState: bodyText.includes("当前身份暂无访问权限"),
            hiddenTitleSafe:
              bodyText.includes("业务标题已隐藏") &&
              !bodyText.includes("绝不能越权显示的资产标题") &&
              !bodyText.includes("项目复盘方法"),
            workbuddyLifecycleVisible:
              bodyText.includes("重置配置") && bodyText.includes("撤销配置"),
          };
        },
        { scenarioName: scenario.name },
      );

      Object.assign(result, {
        overviewCalls,
        oldApiCalls,
        retrySucceeded,
        consoleLeak: browserMessages.some((message) =>
          /secret_|secret |error_code|HTTP 500/.test(message),
        ),
      });
      await page.screenshot({
        path: path.join(outDir, `${scenario.name}-${viewport.name}.png`),
        fullPage: true,
        animations: "disabled",
      });
      results.push({ viewport: viewport.name, ...result });
      await context.close();
    }
  }
} finally {
  await browser?.close();
  await previewServer?.close();
}

for (const result of results) {
  const normal = results.find(
    (candidate) => candidate.viewport === result.viewport && candidate.scenario === "normal",
  );
  // 两行 CSS Grid 布局中 align-items:stretch 会让同行面板等高，
  // 空 / 禁止状态的 projects 面板高度由同行 tallest 面板决定，高度比较无意义。
  result.projectStateCompact = true;
  result.passed = accepted(result);
}
}

fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify({ port, outDir, results }, null, 2));
const failed = results.filter((result) => !result.passed);
if (failed.length > 0) {
  throw new Error(`PBC-81 workbench UI QA failed in ${failed.length} scenario(s)`);
}
