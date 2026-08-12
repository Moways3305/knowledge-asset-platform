import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5198);
const base = `http://127.0.0.1:${port}`;
const outDir = path.join(process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"), "task-center");
fs.mkdirSync(outDir, { recursive: true });
const viewports = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "tablet", width: 1024, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];
const auth = {
  user_id: "00000000-0000-0000-0000-000000000090", name: "任务中心验收用户",
  email: "task-center@example.test", status: "active", company_roles: ["consultant"],
  active_company_role: "consultant", is_business_user: true, can_discover_l5: false,
  project_memberships: [],
};
const task = (overrides = {}) => ({
  task_ref: "safe-task-reference", task_type: "review", object_name: "客户交付复盘审核",
  project_name: "华东交付项目", status: "needs_action", priority: "high", assignee: "任务中心验收用户",
  responsibility: "由你处理", created_at: "2026-08-12T00:30:00Z", updated_at: "2026-08-12T01:30:00Z",
  waiting_minutes: 90, next_action_key: "decide_review", next_action_label: "进入审核", route_key: "reviews",
  result_summary: null, progress_total: null, progress_success: null, progress_failed: null, ...overrides,
});
const overview = {
  task_center: {
    status: "available", error_code: null,
    summary: { needs_action: 2, running: 2, attention: 1, completed_today: 1 },
    priority_items: [task(), task({ task_ref: "safe-failed", task_type: "ingest", object_name: "调研纪要入库", status: "failed", priority: "urgent", next_action_label: "修正或重试", route_key: "upload" })],
    my_tasks: [task(), task({ task_ref: "safe-submitted", status: "submitted", object_name: "方法论升级申请", responsibility: "由你提交", next_action_label: "等待审核结果" })],
    running_jobs: [task({ task_ref: "safe-running", task_type: "ingest", object_name: "市场资料解析", status: "processing", priority: "normal", assignee: "系统作业", next_action_label: "等待处理完成", route_key: "upload" }), task({ task_ref: "safe-migration", task_type: "kb_migration", object_name: "知识库迁移", status: "submitted", priority: "normal", assignee: "平台运维", responsibility: "运维作业", next_action_label: "查看作业进度", route_key: "models", progress_total: 12, progress_success: 4, progress_failed: 0 })],
    attention_items: [task({ task_ref: "safe-attention", task_type: "index_failed", object_name: "索引异常资产", status: "failed", priority: "urgent", assignee: "有权限的治理负责人", responsibility: "运营关注", next_action_label: "查看受影响范围", route_key: "admin_ingest", result_summary: "当前有 4 项需要关注" })],
    recent_completed: [task({ task_ref: "safe-complete", object_name: "项目方案审核", status: "completed", priority: "low", responsibility: "已处理", next_action_label: "查看审核结果", result_summary: "审核已通过" })],
  },
  todos: { status: "available", error_code: null, total: 2, items: [{ key: "review_pending", count: 2, severity: "warning", route_key: "reviews", action_key: "decide_review" }] },
  operations: { status: "empty", error_code: null, data: null },
  projects: { status: "empty", error_code: null, items: [], total: 0 },
  recent_activity: { status: "empty", error_code: null, items: [], total: 0 },
};

let server;
let browser;
const results = [];
try {
  await build({ logLevel: "warn" });
  server = await preview({ preview: { host: "127.0.0.1", port, strictPort: true }, logLevel: "warn" });
  browser = await chromium.launch({ args: ["--disable-gpu"] });
  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport });
    await context.route("**/api/v1/**", async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      const body = pathname === "/api/v1/auth/me" ? auth : pathname === "/api/v1/workbench/overview" ? overview : pathname === "/api/v1/notifications/unread-count" ? { unread_count: 0 } : pathname === "/api/v1/notifications" ? { items: [], total: 0, page: 1, page_size: 20 } : pathname === "/api/v1/auth/workbuddy-token" ? { enabled: false, bound_user_name: auth.name, last_rotated_at: null, last_connected_at: null } : pathname === "/api/v1/auth/workbuddy-connectors" ? { version: "1", artifacts: [] } : {};
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });
    const page = await context.newPage();
    await page.goto(base, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: /有 2 项需要你处理/ }).waitFor();
    await page.getByRole("button", { name: "打开任务中心", exact: true }).click();
    await page.getByRole("heading", { name: "任务中心", exact: true }).waitFor();
    const metrics = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      drawerOverflow: document.querySelector(".detail-drawer-body")?.scrollHeight > document.querySelector(".detail-drawer-body")?.clientHeight,
      actionVisible: Boolean(document.querySelector(".detail-drawer-footer a")),
      groups: document.querySelectorAll('[role="tab"]').length,
      internalRefVisible: document.body.innerText.includes("safe-task-reference"),
    }));
    await page.screenshot({ path: path.join(outDir, `${viewport.name}.png`), fullPage: true });
    results.push({ ...viewport, ...metrics, passed: metrics.overflow <= 2 && metrics.actionVisible && metrics.groups === 4 && !metrics.internalRefVisible });
    await context.close();
  }
  fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
  if (results.some((item) => !item.passed)) process.exitCode = 1;
  console.log(JSON.stringify({ outDir, results }, null, 2));
} finally {
  if (browser) await browser.close();
  if (server) server.httpServer.close();
}
