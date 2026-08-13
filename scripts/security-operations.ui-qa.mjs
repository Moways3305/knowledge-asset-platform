import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5203);
const base = `http://127.0.0.1:${port}`;
const outDir = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "security-operations",
);
const viewports = [
  { name: "1440", width: 1440, height: 1050 },
  { name: "1024", width: 1024, height: 900 },
  { name: "390", width: 390, height: 844 },
];
const pages = [
  { name: "audit", path: "/admin/audit", heading: "审计日志" },
  { name: "auth", path: "/admin/auth-security", heading: "登录安全" },
  { name: "alerts", path: "/admin/alert-settings", heading: "告警设置" },
];
const scenarios = ["normal", "empty", "failure", "forbidden"];
const secrets = [
  "SECRET_EVENT_88",
  "SECRET_TRACE_88",
  "SECRET_USER_88",
  "SECRET_TARGET_88",
  "SECRET_HASH_88",
  "SECRET_IP_88",
  "SECRET_RULE_88",
  "SECRET_NOTICE_88",
  "SECRET_TOKEN_88",
];
const authMe = {
  user_id: "qa-admin",
  name: "安全管理员",
  email: "qa@example.test",
  status: "active",
  company_roles: ["admin"],
  active_company_role: "admin",
  is_business_user: false,
  can_discover_l5: false,
  project_memberships: [],
};
const auditEvent = {
  id: "SECRET_EVENT_88",
  log_type: "operation",
  action: "project.created",
  actor_user_id: "SECRET_USER_88",
  actor_name: "张经理",
  actor_company_role: "project_manager",
  actor_project_role: null,
  target_type: "project",
  target_id: "SECRET_TARGET_88",
  severity: null,
  is_processed: false,
  processed_by: null,
  processed_at: null,
  trace_id: "SECRET_TRACE_88",
  denied_reason: null,
  risk_level: null,
  created_at: "2026-07-20T01:00:00Z",
  before_snapshot: { token: "SECRET_TOKEN_88" },
  after_snapshot: null,
  extra: null,
};
const authOverview = {
  window_minutes: 60,
  counts: {
    failed: 2,
    locked: 1,
    rate_limited: 1,
    success: 8,
    unlocked: 1,
    unique_identifier_count: 4,
    unique_ip_count: 5,
  },
  recent_events: [
    {
      attempt_id: "SECRET_EVENT_88",
      identifier_hash_prefix: "SECRET_HASH_88",
      ip_hash_prefix: "SECRET_IP_88",
      user_id: "SECRET_USER_88",
      user_name: "李顾问",
      user_status: "active",
      login_method: "SECRET_TOKEN_88",
      result: "locked",
      reason_code: "identifier_locked",
      created_at: "2026-07-20T01:00:00Z",
    },
  ],
};
const rule = {
  id: "SECRET_RULE_88",
  rule_name: "连续登录失败",
  severity: "critical",
  threshold: 5,
  threshold_unit: "次",
  enabled: true,
  notification_channels: ["in_app"],
  dedup_strategy: "cooldown",
  updated_at: "2026-07-20T01:00:00Z",
};
const notice = {
  id: "SECRET_NOTICE_88",
  alert_rule_id: "SECRET_RULE_88",
  audit_event_id: "SECRET_EVENT_88",
  recipient_user_id: "SECRET_USER_88",
  recipient_name: "安全管理员",
  channel: "in_app",
  title: "登录失败告警",
  content: "SECRET_TOKEN_88",
  send_status: "pending",
  sent_at: null,
  created_at: "2026-07-20T01:00:00Z",
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
  for (const target of pages)
    for (const scenario of scenarios)
      for (const viewport of viewports) {
        const context = await browser.newContext({ viewport });
        const consoleMessages = [];
        await context.route("**/*", async (route) => {
          const request = route.request();
          const url = new URL(request.url());
          const fulfill = (body, status = 200) =>
            route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
          if (url.pathname === "/api/v1/auth/me") return fulfill(authMe);
          if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "qa-csrf" });
          const isAudit = url.pathname.startsWith("/api/v1/admin/audit");
          const isAuth = url.pathname.startsWith("/admin/ops/auth-security");
          const isRules = url.pathname === "/api/v1/admin/alerts/rules";
          const isNotices = url.pathname === "/api/v1/admin/alerts/notifications";
          if ((isAudit || isAuth || isRules || isNotices) && scenario === "forbidden")
            return fulfill({ detail: { message: "SECRET_TOKEN_88" } }, 403);
          if ((isAudit || isAuth || isRules || isNotices) && scenario === "failure")
            return fulfill({ detail: { message: "SECRET_TOKEN_88" } }, 503);
          if (isAudit)
            return fulfill({
              items:
                scenario === "empty"
                  ? []
                  : [
                      auditEvent,
                      {
                        ...auditEvent,
                        id: "exception-safe",
                        log_type: "exception",
                        action: "preview.denied",
                        severity: "critical",
                      },
                      {
                        ...auditEvent,
                        id: "login-safe",
                        log_type: "login",
                        action: "login.failed",
                      },
                    ],
              total: scenario === "empty" ? 0 : 3,
              page: 1,
              page_size: 200,
              view: "admin_metadata",
            });
          if (isAuth)
            return fulfill(
              scenario === "empty"
                ? {
                    ...authOverview,
                    counts: {
                      failed: 0,
                      locked: 0,
                      rate_limited: 0,
                      success: 0,
                      unlocked: 0,
                      unique_identifier_count: 0,
                      unique_ip_count: 0,
                    },
                    recent_events: [],
                  }
                : authOverview,
            );
          if (isRules) return fulfill({ items: scenario === "empty" ? [] : [rule] });
          if (isNotices) return fulfill({ items: scenario === "empty" ? [] : [notice] });
          if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/admin/ops/"))
            return fulfill({ detail: { message: "route missing" } }, 404);
          return route.continue();
        });
        const page = await context.newPage();
        page.on("console", (message) => consoleMessages.push(message.text()));
        page.on("pageerror", (error) => consoleMessages.push(error.message));
        await page.goto(`${base}${target.path}`, { waitUntil: "networkidle" });
        await page.getByRole("heading", { name: target.heading }).waitFor();
        const screenshot = path.join(outDir, `${target.name}-${scenario}-${viewport.name}.png`);
        await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
        const metrics = await page.evaluate(
          ({ scenario, secrets, targetName }) => {
            const text = document.body.innerText;
            const html = document.documentElement.innerHTML;
            const root = document.documentElement;
            const summaryValues = [...document.querySelectorAll(".secops-summary-value")].map(
              (node) => node.textContent?.trim(),
            );
            const console = document.querySelector(".secops-console");
            const summary = document
              .querySelector(".secops-summary-panel")
              ?.getBoundingClientRect();
            const main = document.querySelector(".secops-main-workspace")?.getBoundingClientRect();
            const workspaces = [...document.querySelectorAll(".secops-workspace")];
            const tableWraps = [...document.querySelectorAll(".secops-table-wrap")];
            const actionButtons = [...document.querySelectorAll(".secops-main-workspace button")];
            const refreshButton = actionButtons.find((button) =>
              button.textContent?.includes("刷新"),
            );
            const expectedState =
              scenario === "normal"
                ? document.querySelectorAll(".secops-table tbody tr").length > 0
                : scenario === "empty"
                  ? text.includes("暂无")
                  : scenario === "forbidden"
                    ? text.includes("没有") && text.includes("权限")
                    : text.includes("暂时无法加载");
            return {
              overflowX: root.scrollWidth - root.clientWidth,
              safe: secrets.every((secret) => !html.includes(secret)),
              twoColumn:
                Boolean(console && summary && main) &&
                console.children.length === 2 &&
                summary.width >= 220 &&
                summary.width <= 250 &&
                main.width >= summary.width * 2.4 &&
                Math.abs(summary.y - main.y) <= 2,
              noStatusStrip: !document.querySelector(".product-status-strip"),
              hasReferenceIconography:
                document.querySelectorAll(".secops-summary-icon svg").length ===
                  summaryValues.length &&
                Boolean(
                  document.querySelector(
                    ".secops-main-workspace .secops-workspace-heading-icon svg",
                  ),
                ) &&
                Boolean(refreshButton?.querySelector("svg")),
              noInnerScroll: tableWraps.every((node) => node.scrollWidth - node.clientWidth <= 2),
              actionsVisible: actionButtons.every((button) => {
                const rect = button.getBoundingClientRect();
                return !main || (rect.left >= main.left - 1 && rect.right <= main.right + 1);
              }),
              alertsStacked:
                targetName !== "alerts" ||
                (workspaces.length === 2 &&
                  workspaces[1].getBoundingClientRect().top >=
                    workspaces[0].getBoundingClientRect().bottom + 8 &&
                  Math.abs(
                    workspaces[0].getBoundingClientRect().width -
                      workspaces[1].getBoundingClientRect().width,
                  ) <= 2),
              noCharts: !document.querySelector(
                "canvas, svg[data-chart], .chart, [class*='trend']",
              ),
              honestEmpty: scenario !== "empty" || summaryValues.every((value) => value === "0"),
              expectedState,
            };
          },
          { scenario, secrets, targetName: target.name },
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
            (viewport.width > 1200 ? metrics.twoColumn : metrics.alertsStacked) &&
            metrics.noStatusStrip &&
            metrics.hasReferenceIconography &&
            (viewport.width > 1200 ? metrics.noInnerScroll : true) &&
            (viewport.width > 1200 ? metrics.actionsVisible : true) &&
            metrics.alertsStacked &&
            metrics.noCharts &&
            metrics.honestEmpty &&
            metrics.expectedState &&
            !consoleLeak,
        });
        await context.close();
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
