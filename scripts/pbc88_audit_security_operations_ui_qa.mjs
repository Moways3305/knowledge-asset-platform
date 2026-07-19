import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5203);
const base = `http://127.0.0.1:${port}`;
const outDir = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "pbc88-security-operations",
);
const viewports = [
  { name: "1440", width: 1440, height: 1050 },
  { name: "1280", width: 1280, height: 960 },
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
          ({ scenario, secrets }) => {
            const text = document.body.innerText;
            const html = document.documentElement.innerHTML;
            const root = document.documentElement;
            const summaryValues = [...document.querySelectorAll(".product-status-value")].map(
              (node) => node.textContent?.trim(),
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
              hasWorkspace: Boolean(document.querySelector(".secops-workspace")),
              noCharts: !document.querySelector(
                "canvas, svg[data-chart], .chart, [class*='trend']",
              ),
              honestEmpty: scenario !== "empty" || summaryValues.every((value) => value === "0"),
              expectedState,
            };
          },
          { scenario, secrets },
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
            metrics.hasWorkspace &&
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
