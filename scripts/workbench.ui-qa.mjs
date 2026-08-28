import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5196);
const base = `http://127.0.0.1:${port}`;
const outDir = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "workbench",
);
fs.mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1024", width: 1024, height: 900 },
  { name: "768", width: 768, height: 900 },
  { name: "390", width: 390, height: 844 },
];
const scenarios = ["normal", "empty", "titles-hidden", "pure-admin", "error-retry"];

const businessAuth = {
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
      project_id: "project-safe-1",
      project_name: "企业知识治理项目",
      project_role: "project_manager",
      status: "active",
    },
  ],
};
const adminAuth = {
  ...businessAuth,
  user_id: "00000000-0000-0000-0000-000000000082",
  name: "系统管理员",
  company_roles: ["admin"],
  active_company_role: "admin",
  is_business_user: false,
  project_memberships: [],
};

const task = (overrides = {}) => ({
  task_ref: "safe-review-reference",
  task_type: "review",
  object_name: "客户交付复盘审核",
  project_name: "企业知识治理项目",
  status: "needs_action",
  priority: "high",
  assignee: "工作台验收用户",
  responsibility: "由你处理",
  created_at: "2026-08-27T00:30:00Z",
  updated_at: "2026-08-27T01:30:00Z",
  waiting_minutes: 90,
  next_action_key: "decide_review",
  next_action_label: "进入审核",
  route_key: "reviews",
  result_summary: null,
  progress_total: null,
  progress_success: null,
  progress_failed: null,
  ...overrides,
});

function populatedOverview({ hidden = false, admin = false } = {}) {
  const running = [
    task({
      task_ref: "running-1",
      task_type: "ingest",
      object_name: "市场资料解析",
      status: "processing",
      priority: "normal",
      responsibility: "系统作业",
      next_action_key: null,
      next_action_label: "正在解析内容",
      route_key: "upload",
      progress_total: 10,
      progress_success: 4,
      progress_failed: 0,
    }),
    task({
      task_ref: "running-2",
      task_type: "kb_migration",
      object_name: "知识库迁移",
      status: "processing",
      priority: "normal",
      responsibility: "运维作业",
      next_action_key: "inspect_operation",
      next_action_label: "查看作业进度",
      route_key: "models",
      progress_total: 12,
      progress_success: 5,
      progress_failed: 0,
    }),
    task({
      task_ref: "running-3",
      task_type: "markdown_backfill",
      object_name: "规范 Markdown 补齐",
      status: "submitted",
      priority: "normal",
      responsibility: "运维作业",
      next_action_key: "inspect_operation",
      next_action_label: "等待作业开始",
      route_key: "admin_ingest",
    }),
    task({
      task_ref: "running-4",
      task_type: "indexing",
      object_name: "索引恢复作业",
      status: "processing",
      priority: "normal",
      responsibility: "运维作业",
      next_action_key: "inspect_operation",
      next_action_label: "正在恢复索引",
      route_key: "admin_ingest",
    }),
  ];
  const completed = [
    task({
      task_ref: "done-1",
      object_name: "项目方案审核",
      status: "completed",
      priority: "low",
      responsibility: "已处理",
      next_action_key: null,
      next_action_label: "查看审核结果",
      result_summary: "审核已通过",
    }),
    task({
      task_ref: "done-2",
      task_type: "ingest",
      object_name: "重复资料.pdf",
      status: "duplicate_skipped",
      priority: "low",
      responsibility: "由你发起",
      next_action_key: null,
      next_action_label: "查看入库结果",
      route_key: "upload",
      result_summary: "因内容重复已跳过",
    }),
    task({
      task_ref: "done-3",
      task_type: "parsing",
      object_name: "解析恢复作业",
      status: "partial",
      priority: "low",
      responsibility: "运维作业",
      next_action_key: null,
      next_action_label: "查看作业结果",
      route_key: "admin_ingest",
      result_summary: "部分资料需要继续处理",
    }),
    task({
      task_ref: "done-4",
      task_type: "indexing",
      object_name: "索引重试作业",
      status: "failed",
      priority: "low",
      responsibility: "运维作业",
      next_action_key: null,
      next_action_label: "查看作业结果",
      route_key: "admin_ingest",
      result_summary: "作业失败",
    }),
  ];
  const attention = [
    task({
      task_ref: "attention-1",
      task_type: "archive_candidates",
      object_name: "归档候选资产",
      status: "needs_action",
      priority: "normal",
      responsibility: "运营关注",
      next_action_key: "inspect_attention",
      next_action_label: "查看受影响范围",
      route_key: admin ? "knowledge" : "admin_ingest",
      result_summary: "当前有 2 项需要关注",
    }),
    task({
      task_ref: "attention-2",
      task_type: "index_failed",
      object_name: "索引异常资产",
      status: "failed",
      priority: "urgent",
      responsibility: "运营关注",
      next_action_key: "inspect_attention",
      next_action_label: "查看受影响范围",
      route_key: "admin_ingest",
      result_summary: "当前有 1 项需要关注",
    }),
  ];
  return {
    task_center: {
      status: "available",
      error_code: null,
      summary: { needs_action: admin ? 0 : 2, running: 4, attention: 2, completed_today: 4 },
      priority_items: [],
      my_tasks: admin
        ? []
        : [
            task(),
            task({
              task_ref: "failed-ingest",
              task_type: "ingest",
              object_name: "失败入库资料",
              status: "failed",
              priority: "urgent",
              next_action_key: "retry_ingest",
              next_action_label: "修正或重试",
              route_key: "upload",
            }),
            task({
              task_ref: "submitted-review",
              object_name: "等待他人审核资料",
              status: "submitted",
              priority: "normal",
              responsibility: "由你提交",
              next_action_key: null,
              next_action_label: "等待审核结果",
            }),
          ],
      running_jobs: running,
      attention_items: attention,
      recent_completed: completed,
    },
    todos: { status: "empty", error_code: null, items: [], total: 0 },
    operations: {
      status: "available",
      error_code: null,
      data: {
        title_visible: !hidden && !admin,
        scope: admin ? "company" : "personal",
        window_days: 30,
        cards: [],
        indexing: {
          index_failed: 0,
          skipped: 0,
          not_indexed: 0,
          parse_failed: 0,
          parse_pending: 0,
          parse_processing: 0,
          kb_init_failed: 0,
        },
        access: {
          pending_original_requests: 0,
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
    projects: admin
      ? { status: "empty", error_code: null, items: [], total: 0 }
      : {
          status: "available",
          error_code: null,
          total: 2,
          items: [
            {
              project_id: "project-safe-1",
              name: "企业知识治理项目",
              status: "active",
              project_role: "project_manager",
              access_mode: "member",
              access_label: "可查看资料",
              lifecycle_route_key: null,
              lifecycle_phase_key: null,
            },
            {
              project_id: "project-safe-2",
              name: "行业研究项目",
              status: "active",
              project_role: null,
              access_mode: "summary_visible",
              access_label: "摘要可见",
              lifecycle_route_key: null,
              lifecycle_phase_key: null,
            },
          ],
        },
    recent_activity: {
      status: admin ? "forbidden" : "available",
      error_code: admin ? "recent_activity_forbidden" : null,
      total: 4,
      items: [0, 1, 2, 3].map((index) => ({
        asset_id: `asset-safe-${index}`,
        title: `安全资产标题 ${index + 1}`,
        scope: "project",
        zone: "project",
        asset_type: "document",
        access_mode: index === 0 ? "summary_visible" : "member",
        confidentiality_level: "L2",
        summary: null,
        project_name: index === 0 ? "行业研究项目" : "企业知识治理项目",
        updated_at: "2026-08-27T02:30:00Z",
      })),
    },
  };
}

function emptyOverview() {
  return {
    task_center: {
      status: "empty",
      error_code: null,
      summary: { needs_action: 0, running: 0, attention: 0, completed_today: 0 },
      priority_items: [],
      my_tasks: [],
      running_jobs: [],
      attention_items: [],
      recent_completed: [],
    },
    todos: { status: "empty", error_code: null, items: [], total: 0 },
    operations: { status: "empty", error_code: null, data: null },
    projects: { status: "empty", error_code: null, items: [], total: 0 },
    recent_activity: { status: "empty", error_code: null, items: [], total: 0 },
  };
}

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
  for (const scenario of scenarios) {
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport, reducedMotion: "reduce" });
      let overviewCalls = 0;
      await context.route("**/api/v1/**", async (route) => {
        const pathname = new URL(route.request().url()).pathname;
        if (pathname === "/api/v1/auth/me") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(scenario === "pure-admin" ? adminAuth : businessAuth),
          });
          return;
        }
        if (pathname === "/api/v1/workbench/overview") {
          overviewCalls += 1;
          if (scenario === "error-retry" && overviewCalls === 1) {
            await route.fulfill({
              status: 503,
              contentType: "application/json",
              body: JSON.stringify({ detail: "internal-secret" }),
            });
            return;
          }
          const body =
            scenario === "empty"
              ? emptyOverview()
              : populatedOverview({
                  hidden: scenario === "titles-hidden",
                  admin: scenario === "pure-admin",
                });
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(body),
          });
          return;
        }
        if (pathname === "/api/v1/auth/workbuddy-token") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              enabled: true,
              bound_user_name: "工作台验收用户",
              last_rotated_at: "2026-08-27T01:00:00Z",
              last_connected_at: "2026-08-27T02:00:00Z",
            }),
          });
          return;
        }
        if (pathname === "/api/v1/notifications") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              items: [],
              total: 0,
              page: 1,
              page_size: 20,
              unread_count: 0,
              pending_count: 0,
            }),
          });
          return;
        }
        await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
      });

      const page = await context.newPage();
      const browserMessages = [];
      page.on("console", (message) => {
        if (message.type() === "error") browserMessages.push(message.text());
      });
      page.on("pageerror", (error) => browserMessages.push(error.message));
      await page.goto(`${base}/?from=uiqa`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "我的工作", exact: true }).waitFor();

      if (scenario === "error-retry") {
        const retry = page.getByRole("button", { name: "重新加载" }).first();
        await retry.waitFor();
        await retry.click();
        await page.getByRole("button", { name: /客户交付复盘审核/ }).waitFor();
      }
      if (scenario === "normal" && viewport.width === 1440) {
        await page.getByRole("button", { name: /客户交付复盘审核/ }).click();
        const drawer = page.getByRole("dialog", { name: "任务中心" });
        await drawer.getByText("客户交付复盘审核", { exact: true }).last().waitFor();
        await page.keyboard.press("Escape");
        await drawer.waitFor({ state: "hidden" });
        await page.waitForURL(`${base}/?from=uiqa`);
      }
      const metrics = await page.evaluate(
        ({ scenarioName, viewportWidth }) => {
          const root = document.documentElement;
          const shell = document.querySelector(".workbench-scene-shell")?.getBoundingClientRect();
          const heading = document.querySelector(".workbench-heading")?.getBoundingClientRect();
          const stage = document.querySelector(".workbench-layout")?.getBoundingClientRect();
          const primary = document.querySelector(".workbench-primary")?.getBoundingClientRect();
          const aside = document.querySelector(".workbench-context")?.getBoundingClientRect();
          const projects = document.querySelector(".workbench-projects")?.getBoundingClientRect();
          const workbuddy = document.querySelector(".workbench-workbuddy")?.getBoundingClientRect();
          const recent = document.querySelector(".workbench-recent")?.getBoundingClientRect();
          const tabButtons = [...document.querySelectorAll(".workbench-tabs button")];
          return {
            overflow: root.scrollWidth - root.clientWidth,
            sceneConnected: Boolean(
              shell &&
                heading &&
                stage &&
                Math.abs(stage.top - heading.bottom) <= 2 &&
                shell.top <= heading.top &&
                shell.bottom >= stage.bottom,
            ),
            stageStable:
              viewportWidth < 900 ||
              Boolean(
                stage &&
                  primary &&
                  recent &&
                  stage.height >= 600 &&
                  primary.height >= 350 &&
                  recent.height >= 170,
              ),
            unifiedContextSurface: Boolean(
              projects &&
                (!workbuddy ||
                  (projects.left === workbuddy.left &&
                    projects.right === workbuddy.right &&
                    Math.abs(projects.bottom - workbuddy.top) <= 1)),
            ),
            drawerClosed: document.querySelector(".detail-drawer") === null,
            taskListFirstScreen:
              (document.querySelector(".workbench-task-list")?.getBoundingClientRect().top ??
                innerHeight + 1) < innerHeight,
            tabsUsable:
              tabButtons.length === 3 &&
              tabButtons.every((item) => item.getBoundingClientRect().width >= 38),
            desktopColumns:
              viewportWidth < 1024 ||
              Boolean(
                primary &&
                aside &&
                Math.abs(primary.top - aside.top) <= 2 &&
                aside.left > primary.left,
              ),
            compactStack:
              viewportWidth >= 1024 || Boolean(primary && aside && aside.top > primary.bottom),
            mobileOrder:
              viewportWidth >= 1024 ||
              (scenarioName === "pure-admin"
                ? Boolean(
                    primary &&
                    projects &&
                    recent &&
                    primary.top < projects.top &&
                    projects.top < recent.top,
                  )
                : Boolean(
                    primary &&
                    projects &&
                    workbuddy &&
                    recent &&
                    primary.top < projects.top &&
                    projects.top < workbuddy.top &&
                    workbuddy.top < recent.top,
                  )),
            actionableRows: document.querySelectorAll(".workbench-task-list .workbench-task-row")
              .length,
            projectRows: document.querySelectorAll(".workbench-project-list > a").length,
            memberProjectRoute:
              document.querySelector(
                '.workbench-project-list a[href="/project/project-safe-1"]',
              ) !== null,
            summaryProjectRoute:
              document.querySelector(
                '.workbench-project-list a[href="/knowledge?scope=project&project_id=project-safe-2"]',
              ) !== null,
            connectedState:
              scenarioName === "pure-admin" ||
              document.body.innerText.includes("已连接 · 最近成功连接"),
            recentPreview: document.querySelectorAll(".workbench-recent-list > a").length,
            recentSummaryMaterial:
              document.querySelector(".workbench-recent-list > a.material-summary") !== null,
            recentMemberMaterial:
              document.querySelector(".workbench-recent-list > a.material-source") !== null,
            oldSurfaceVisible: /今日任务调度|我的待办|资产运行概览|项目概览|运营中枢/.test(
              document.body.innerText,
            ),
            submittedShownAsActionable: (
              document.querySelector(".workbench-task-list")?.innerText ?? ""
            ).includes("等待他人审核资料"),
            hiddenTitleSafe:
              scenarioName !== "titles-hidden" ||
              (!document.body.innerText.includes("安全资产标题") &&
                document.body.innerText.includes("业务标题已隐藏")),
            adminRecentClosed:
              scenarioName !== "pure-admin" ||
              (document.querySelectorAll('.workbench-recent-list a[href^="/knowledge"]').length ===
                0 &&
                document.querySelector(".detail-drawer-footer a") === null),
            technicalErrorVisible: document.body.innerText.includes("internal-secret"),
          };
        },
        { scenarioName: scenario, viewportWidth: viewport.width },
      );

      const unexpectedBrowserMessages =
        scenario === "error-retry"
          ? browserMessages.filter((message) => !message.includes("503 (Service Unavailable)"))
          : browserMessages;
      const populated = !["empty", "pure-admin"].includes(scenario);
      const passed =
        metrics.overflow <= 2 &&
        metrics.sceneConnected &&
        metrics.stageStable &&
        metrics.unifiedContextSurface &&
        metrics.drawerClosed &&
        metrics.taskListFirstScreen &&
        metrics.tabsUsable &&
        metrics.desktopColumns &&
        metrics.compactStack &&
        metrics.mobileOrder &&
        !metrics.oldSurfaceVisible &&
        !metrics.submittedShownAsActionable &&
        metrics.hiddenTitleSafe &&
        metrics.adminRecentClosed &&
        !metrics.technicalErrorVisible &&
        unexpectedBrowserMessages.length === 0 &&
        (populated
          ? metrics.actionableRows === 2 &&
            metrics.projectRows === 2 &&
            metrics.memberProjectRoute &&
            metrics.summaryProjectRoute &&
            metrics.connectedState &&
            metrics.recentPreview === 3 &&
            metrics.recentSummaryMaterial &&
            metrics.recentMemberMaterial
          : true);
      await page.screenshot({
        path: path.join(outDir, `${scenario}-${viewport.name}.png`),
        fullPage: true,
      });
      results.push({
        scenario,
        viewport: viewport.name,
        ...viewport,
        ...metrics,
        overviewCalls,
        browserMessages,
        unexpectedBrowserMessages,
        passed,
      });
      await context.close();
    }
  }
  fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
  if (results.some((item) => !item.passed)) process.exitCode = 1;
  console.log(JSON.stringify({ outDir, results }, null, 2));
} finally {
  if (browser) await browser.close();
  if (server) server.httpServer.close();
}
