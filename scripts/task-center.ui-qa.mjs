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
  { name: "desktop-compact", width: 1024, height: 900 },
  { name: "tablet", width: 768, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];

const auth = {
  user_id: "00000000-0000-0000-0000-000000000090",
  name: "任务中心验收用户",
  email: "task-center@example.test",
  status: "active",
  company_roles: ["consultant"],
  active_company_role: "consultant",
  is_business_user: true,
  can_discover_l5: false,
  project_memberships: [],
};

const task = (overrides = {}) => ({
  task_ref: "safe-task-reference",
  task_type: "review",
  object_name: "客户交付复盘审核",
  project_name: "华东交付项目",
  status: "needs_action",
  priority: "high",
  assignee: "任务中心验收用户",
  responsibility: "由你处理",
  created_at: "2026-08-12T00:30:00Z",
  updated_at: "2026-08-12T01:30:00Z",
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

const overview = {
  task_center: {
    status: "available",
    error_code: null,
    summary: { needs_action: 2, running: 1, attention: 1, completed_today: 1 },
    priority_items: [],
    my_tasks: [
      task(),
      task({ task_ref: "safe-failed-reference", task_type: "ingest", object_name: "调研纪要入库", status: "failed", priority: "urgent", next_action_key: "retry_ingest", next_action_label: "修正或重试", route_key: "upload" }),
    ],
    running_jobs: [
      task({ task_ref: "safe-migration-reference", task_type: "kb_migration", object_name: "知识库迁移", status: "processing", priority: "normal", assignee: "平台运维", responsibility: "运维作业", next_action_key: "inspect_operation", next_action_label: "查看作业进度", route_key: "models", progress_total: 12, progress_success: 4, progress_failed: 0 }),
    ],
    attention_items: [
      task({ task_ref: "safe-attention-reference", task_type: "index_failed", object_name: "索引异常资产", status: "failed", priority: "urgent", responsibility: "运营关注", next_action_key: "inspect_attention", next_action_label: "查看受影响范围", route_key: "admin_ingest", result_summary: "当前有 4 项需要关注" }),
    ],
    recent_completed: [
      task({ task_ref: "safe-duplicate-reference", task_type: "ingest", object_name: "重复资料.pdf", status: "duplicate_skipped", priority: "low", responsibility: "由你发起", next_action_key: null, next_action_label: "查看入库结果", route_key: "upload", result_summary: "因内容重复已跳过" }),
    ],
  },
  todos: { status: "empty", error_code: null, items: [], total: 0 },
  operations: { status: "empty", error_code: null, data: null },
  projects: { status: "empty", error_code: null, items: [], total: 0 },
  recent_activity: { status: "empty", error_code: null, items: [], total: 0 },
};

function responseFor(pathname) {
  if (pathname === "/api/v1/auth/me") return auth;
  if (pathname === "/api/v1/workbench/overview") return overview;
  if (pathname === "/api/v1/notifications") return { items: [], total: 0, page: 1, page_size: 20, unread_count: 0, pending_count: 0 };
  return {};
}

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
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(responseFor(pathname)) });
    });
    const page = await context.newPage();
    const browserMessages = [];
    page.on("console", (message) => { if (message.type() === "error") browserMessages.push(message.text()); });
    page.on("pageerror", (error) => browserMessages.push(error.message));
    await page.goto(base, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "我的工作", exact: true }).waitFor();
    await page.getByRole("button", { name: "打开任务中心，2 项待处理" }).click();
    const drawer = page.getByRole("dialog", { name: "任务中心" });
    await drawer.waitFor();
    const defaultTab = drawer.getByRole("tab", { name: /我的任务\s*2/ });
    const defaultSelected = (await defaultTab.getAttribute("aria-selected")) === "true";
    await drawer.getByRole("link", { name: "进入审核" }).waitFor();
    await drawer.getByRole("tab", { name: /进行中的作业\s*1/ }).click();
    await drawer.getByText("迁移作业", { exact: true }).waitFor();
    await drawer.getByRole("tab", { name: /最近完成\s*1/ }).click();
    await drawer.getByText("重复跳过", { exact: true }).first().waitFor();
    const metrics = await page.evaluate(() => {
      const drawerElement = document.querySelector(".detail-drawer");
      const drawerRect = drawerElement?.getBoundingClientRect();
      const drawerTabs = [...document.querySelectorAll('.detail-drawer [role="tab"]')];
      return {
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        drawerWithinViewport: Boolean(drawerRect) && drawerRect.left >= -1 && drawerRect.right <= innerWidth + 1,
        tabCount: drawerTabs.length,
        tabsUsable: drawerTabs.every((tab) => tab.getBoundingClientRect().width >= 44),
        internalRefVisible: document.body.innerText.includes("safe-task-reference"),
        technicalTypeVisible: document.body.innerText.includes("kb_migration"),
      };
    });
    const passed = metrics.overflow <= 2 && metrics.drawerWithinViewport && metrics.tabCount === 4 && metrics.tabsUsable && !metrics.internalRefVisible && !metrics.technicalTypeVisible && defaultSelected && browserMessages.length === 0;
    await page.screenshot({ path: path.join(outDir, `${viewport.name}.png`), fullPage: true });
    results.push({ ...viewport, ...metrics, defaultSelected, browserMessages, passed });
    await context.close();
  }
  fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
  if (results.some((item) => !item.passed)) process.exitCode = 1;
  console.log(JSON.stringify({ outDir, results }, null, 2));
} finally {
  if (browser) await browser.close();
  if (server) server.httpServer.close();
}
