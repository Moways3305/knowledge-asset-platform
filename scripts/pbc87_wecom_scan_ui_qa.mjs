import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5202);
const base = `http://127.0.0.1:${port}`;
const outDir = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "pbc87-wecom-scan",
);
fs.mkdirSync(outDir, { recursive: true });
const viewports = [
  { name: "1440", width: 1440, height: 1050 },
  { name: "1280", width: 1280, height: 960 },
];
const scenarios = [
  "normal",
  "empty",
  "disabled",
  "scan-success",
  "scan-failure",
  "records-empty",
  "forbidden",
  "unconfigured",
];
const secrets = [
  "SECRET_CONFIG_87",
  "SECRET_RECORD_87",
  "SECRET_TRACE_87",
  "SECRET_SPACE_87",
  "SECRET_FOLDER_87",
  "SECRET_UPSTREAM_87",
  "SECRET_TOKEN_87",
];
const authMe = {
  user_id: "qa-admin",
  name: "扫描管理员",
  email: "qa@example.test",
  status: "active",
  company_roles: ["admin"],
  is_business_user: false,
  can_discover_l5: false,
  project_memberships: [],
};
const config = {
  id: "SECRET_CONFIG_87",
  name: "Alpha 交付资料",
  directory_path: "spaceid:SECRET_SPACE_87;fatherid:SECRET_FOLDER_87",
  scope_type: "project",
  related_project_id: "project-safe",
  related_project_name: "Alpha 项目",
  enabled: true,
  created_by: "owner-safe",
  task_owner_name: "张经理",
  task_owner_role_label: "项目经理",
  scan_frequency: null,
  last_scan_at: "2026-07-20T01:00:00Z",
  created_at: "2026-07-19T01:00:00Z",
  updated_at: "2026-07-20T01:00:00Z",
};
const record = {
  id: "SECRET_RECORD_87",
  config_id: "SECRET_CONFIG_87",
  trace_id: "SECRET_TRACE_87",
  scan_started_at: "2026-07-20T01:00:00Z",
  scan_completed_at: "2026-07-20T01:01:00Z",
  discovered_count: 12,
  new_count: 4,
  duplicate_count: 7,
  failed_count: 1,
  scan_status: "partial",
  error_type: "upstream_auth_token",
  error_message: "SECRET_UPSTREAM_87 SECRET_TOKEN_87",
  created_at: "2026-07-20T01:00:00Z",
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
  for (const scenario of scenarios)
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport });
      const consoleMessages = [];
      let scanHeader = null;
      await context.route("**/*", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
        if (!url.pathname.startsWith("/api/")) return route.continue();
        if (url.pathname === "/api/v1/auth/me") return fulfill(authMe);
        if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "qa-csrf" });
        if (scenario === "forbidden" && url.pathname === "/api/v1/admin/wecom-scan/configs")
          return fulfill({ detail: { message: "SECRET_UPSTREAM_87" } }, 403);
        if (url.pathname === "/api/v1/admin/wecom-scan/configs")
          return fulfill({
            items: scenario === "empty" ? [] : [{ ...config, enabled: scenario !== "disabled" }],
          });
        if (url.pathname.endsWith("/records"))
          return fulfill({ items: scenario === "records-empty" ? [] : [record] });
        if (url.pathname.endsWith("/scan")) {
          scanHeader = request.headers()["idempotency-key"] || null;
          if (scenario === "scan-failure")
            return fulfill({ detail: { message: "SECRET_UPSTREAM_87" } }, 502);
          return fulfill(record);
        }
        if (url.pathname.endsWith("/project-options"))
          return fulfill({ items: [{ id: "project-safe", name: "Alpha 项目" }] });
        if (url.pathname.endsWith("/owner-options"))
          return fulfill({
            items: [
              {
                user_id: "owner-safe",
                name: "张经理",
                role_label: "项目经理",
                project_ids: ["project-safe"],
                is_governance: false,
              },
            ],
          });
        if (url.pathname.endsWith("/drive/spaces")) {
          if (scenario === "unconfigured")
            return fulfill({ detail: { message: "SECRET_TOKEN_87" } }, 503);
          return fulfill({ items: [{ space_ref: "SECRET_SPACE_87", name: "项目空间" }] });
        }
        if (url.pathname.includes("/drive/directories"))
          return fulfill({ space_ref: "SECRET_SPACE_87", items: [] });
        return fulfill({ detail: { message: "route missing" } }, 404);
      });
      const page = await context.newPage();
      page.on("console", (message) => consoleMessages.push(message.text()));
      page.on("pageerror", (error) => consoleMessages.push(error.message));
      await page.goto(`${base}/admin/wecom-scan`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "微盘扫描" }).waitFor();
      if (scenario === "scan-success" || scenario === "scan-failure") {
        await page.getByRole("button", { name: "扫描", exact: true }).click();
        await page.getByText(scenario === "scan-success" ? /扫描已结束/ : /扫描未能完成/).waitFor();
      }
      if (scenario === "unconfigured") {
        await page.getByRole("button", { name: "新增扫描配置" }).click();
        await page.getByRole("button", { name: "选择微盘目录" }).click();
        await page.getByText("微盘空间暂时无法加载，请检查企业微信配置后重试。").waitFor();
      }
      const screenshot = path.join(outDir, `${scenario}-${viewport.name}.png`);
      await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
      const metrics = await page.evaluate(
        ({ scenario, secrets }) => {
          const root = document.documentElement;
          const text = document.body.innerText;
          return {
            scenario,
            overflowX: root.scrollWidth - root.clientWidth,
            safe: secrets.every((secret) => !document.documentElement.innerHTML.includes(secret)),
            consoleLayout: Boolean(
              document.querySelector(".ws87-summary") &&
              document.querySelector(".ws87-config-panel") &&
              document.querySelector(".ws87-record-panel"),
            ),
            readOnly:
              scenario !== "forbidden" ||
              (text.includes("保持只读") && !text.includes("新增扫描配置")),
            stateVisible: {
              empty: text.includes("尚未配置微盘扫描"),
              disabled: text.includes("停用"),
              "records-empty": text.includes("暂无扫描记录"),
              unconfigured: text.includes("微盘空间暂时无法加载"),
              normal: text.includes("Alpha 交付资料"),
              "scan-success": text.includes("扫描已结束"),
              "scan-failure": text.includes("扫描未能完成"),
              forbidden: text.includes("保持只读"),
            }[scenario],
          };
        },
        { scenario, secrets },
      );
      const consoleLeak = consoleMessages.some((message) =>
        secrets.some((secret) => message.includes(secret)),
      );
      const idempotent = !scenario.startsWith("scan-") || Boolean(scanHeader);
      results.push({
        viewport: viewport.name,
        screenshot,
        ...metrics,
        consoleLeak,
        idempotent,
        pass:
          metrics.overflowX <= 2 &&
          metrics.safe &&
          metrics.consoleLayout &&
          metrics.readOnly &&
          metrics.stateVisible &&
          !consoleLeak &&
          idempotent,
      });
      await context.close();
    }
} finally {
  await browser?.close();
  await server?.close();
}
const reportPath = path.join(outDir, "report.json");
fs.writeFileSync(reportPath, JSON.stringify(results, null, 2));
console.log(JSON.stringify({ outDir, reportPath, results }, null, 2));
if (results.some((result) => !result.pass)) process.exitCode = 1;
