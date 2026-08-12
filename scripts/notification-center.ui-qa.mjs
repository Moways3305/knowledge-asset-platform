import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5199);
const base = `http://127.0.0.1:${port}`;
const outDir = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "notification-center",
);
fs.mkdirSync(outDir, { recursive: true });
const viewports = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "tablet", width: 1024, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];
const auth = {
  user_id: "00000000-0000-0000-0000-000000000090",
  name: "通知验收用户",
  email: "notification@example.test",
  status: "active",
  company_roles: ["consultant"],
  active_company_role: "consultant",
  is_business_user: true,
  can_discover_l5: false,
  project_memberships: [],
};
const item = (overrides = {}) => ({
  id: "00000000-0000-0000-0000-000000000101",
  event_type: "review.project_pending",
  category: "review",
  title: "项目事项待确认",
  summary: "有一项项目事项等待你确认。",
  created_at: "2026-08-12T01:30:00Z",
  is_read: false,
  read_at: null,
  project_name: "华东交付项目",
  object_name: "项目事项待确认",
  task_status: "needs_action",
  task_group: "my_tasks",
  action_required: true,
  next_action_label: "前往处理",
  delivery_status: "pending",
  target: { route_key: "reviews", resource_id: "00000000-0000-0000-0000-000000000201" },
  ...overrides,
});
const notifications = {
  items: [
    item(),
    item({
      id: "00000000-0000-0000-0000-000000000102",
      category: "knowledge_base",
      event_type: "job.knowledge_base.partial",
      title: "知识库迁移部分完成",
      summary: "迁移仍有待处理项，请查看结果。",
      is_read: true,
      read_at: "2026-08-12T02:00:00Z",
      project_name: null,
      object_name: "知识库迁移",
      task_status: "partial",
      task_group: "attention_items",
      action_required: false,
      next_action_label: "查看结果",
      target: { route_key: "models", resource_id: "00000000-0000-0000-0000-000000000202" },
    }),
  ],
  total: 2,
  page: 1,
  page_size: 20,
  unread_count: 1,
  categories: ["review", "knowledge_base"],
};
const emptyOverview = {
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
  todos: { status: "empty", error_code: null, total: 0, items: [] },
  operations: { status: "empty", error_code: null, data: null },
  projects: { status: "empty", error_code: null, items: [], total: 0 },
  recent_activity: { status: "empty", error_code: null, items: [], total: 0 },
};

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
  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport });
    await context.route("**/api/v1/**", async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      const body =
        pathname === "/api/v1/auth/me"
          ? auth
          : pathname === "/api/v1/workbench/overview"
            ? emptyOverview
            : pathname === "/api/v1/notifications"
              ? notifications
              : pathname === "/api/v1/auth/workbuddy-token"
                ? {
                    enabled: false,
                    bound_user_name: auth.name,
                    last_rotated_at: null,
                    last_connected_at: null,
                  }
                : pathname === "/api/v1/auth/workbuddy-connectors"
                  ? { version: "1", artifacts: [] }
                  : {};
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    });
    const page = await context.newPage();
    await page.goto(base, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: /通知中心，1 条未读/ }).click();
    await page.getByRole("heading", { name: "通知中心" }).waitFor();
    const metrics = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      drawerScroll:
        document.querySelector(".detail-drawer-body")?.scrollHeight >=
        document.querySelector(".detail-drawer-body")?.clientHeight,
      filters: document.querySelectorAll('.notification-center-filters [role="tab"]').length,
      uuidVisible: document.body.innerText.includes("00000000-"),
    }));
    await page.screenshot({ path: path.join(outDir, `${viewport.name}.png`), fullPage: true });
    results.push({
      ...viewport,
      ...metrics,
      passed:
        metrics.overflow <= 2 &&
        metrics.drawerScroll &&
        metrics.filters === 2 &&
        !metrics.uuidVisible,
    });
    await context.close();
  }
  fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
  if (results.some((item) => !item.passed)) process.exitCode = 1;
  console.log(JSON.stringify({ outDir, results }, null, 2));
} finally {
  if (browser) await browser.close();
  if (server) server.httpServer.close();
}
