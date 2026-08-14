import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5212);
const externalBase = process.env.UI_QA_BASE?.replace(/\/$/, "") || null;
const base = externalBase || `http://127.0.0.1:${port}`;
const outDir = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "admin-information-architecture",
);
fs.mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1024", width: 1024, height: 900 },
  { name: "390", width: 390, height: 844 },
];
const scenarios = ["normal", "empty", "partial-failure", "scoped-manager"];

const authMe = (scenario) => ({
  user_id: "secret-admin-ia-user",
  name: scenario === "scoped-manager" ? "项目经理" : "治理管理员",
  email: "secret-admin-ia@example.test",
  status: "active",
  company_roles: [scenario === "scoped-manager" ? "consultant" : "boss"],
  active_company_role: scenario === "scoped-manager" ? "consultant" : "boss",
  is_business_user: true,
  can_discover_l5: scenario !== "scoped-manager",
  project_memberships: [
    {
      project_id: "secret-project-id",
      project_name: "Alpha 项目",
      project_role: "project_manager",
      status: "active",
    },
  ],
});

const workbenchOverview = {
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
  projects: { status: "available", error_code: null, items: [], total: 0 },
  recent_activity: { status: "empty", error_code: null, items: [], total: 0 },
};

const indexing = (empty) => ({
  counts: {
    index_failed: empty ? 0 : 2,
    indexing: 1,
    not_indexed: 0,
    skipped: 0,
    parse_pending: 0,
    parse_processing: 1,
    parse_stalled: empty ? 0 : 1,
    parse_failed: empty ? 0 : 1,
    kb_init_failed: 0,
  },
  reparse_actionable_count: empty ? 0 : 1,
  recent_failed: [],
  diagnostic_counts: {
    configuration: 0,
    external_service: 0,
    source_content: 0,
    permission: 0,
    platform: 0,
    unknown: 0,
  },
  title_visible: true,
  last_reconcile: null,
});

let server;
let browser;
const results = [];

try {
  if (!externalBase) {
    await build({ logLevel: "warn" });
    server = await preview({
      logLevel: "warn",
      preview: { host: "127.0.0.1", port, strictPort: true },
    });
  }
  browser = await chromium.launch({ args: ["--disable-gpu"] });

  for (const scenario of scenarios) {
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport });
      const messages = [];
      const requestedAdminPaths = [];
      await context.route("**/*", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
        if (!url.pathname.startsWith("/api/") && !url.pathname.startsWith("/admin/ops/"))
          return route.continue();
        if (url.pathname === "/api/v1/auth/me") return fulfill(authMe(scenario));
        if (url.pathname === "/api/v1/workbench/overview") return fulfill(workbenchOverview);
        if (url.pathname === "/api/v1/notifications/unread-count")
          return fulfill({ unread_count: 0 });
        if (url.pathname === "/api/v1/notifications")
          return fulfill({ items: [], total: 0, page: 1, page_size: 20, unread_count: 0 });

        requestedAdminPaths.push(url.pathname);
        const empty = scenario === "empty";
        if (url.pathname === "/api/v1/admin/ingest") {
          return fulfill({
            items: empty
              ? []
              : [
                  {
                    id: "secret-ingest-id",
                    source: "path_b_upload",
                    source_file_name: "secret-file-name.docx",
                    status: "failed",
                    target_scope: "company",
                    confidentiality_level: "L2",
                    ai_access_level: "summary",
                    confidence: 0.8,
                    suggestion_generation_status: "generated",
                    suggestion_generation_reason: "ready",
                    naming_compliant: true,
                    extraction_status: "completed",
                    error_type: "service_unavailable",
                    error_message: "safe error",
                    result_asset_id: null,
                    created_at: "2026-08-14T01:00:00Z",
                  },
                ],
            total: empty ? 0 : 1,
          });
        }
        if (url.pathname === "/admin/ops/indexing") return fulfill(indexing(empty));
        if (url.pathname === "/api/v1/admin/wecom-scan/configs")
          return fulfill({
            items: empty
              ? []
              : [
                  {
                    id: "secret-scan-id",
                    name: "项目扫描",
                    scope_type: "project",
                    related_project_id: "secret-project-id",
                    related_project_name: "Alpha 项目",
                    scan_space_status: "ready",
                    manager_access_status: "ready",
                    enabled: true,
                    created_by: "secret-user-id",
                    task_owner_name: "王顾问",
                    task_owner_role_label: "项目经理",
                    scan_frequency: null,
                    last_scan_at: null,
                    created_at: "2026-08-14T01:00:00Z",
                    updated_at: "2026-08-14T01:00:00Z",
                  },
                ],
          });
        if (url.pathname === "/api/v1/admin/weknora/models")
          return fulfill([
            {
              model_ref: "secret-model-ref",
              name: "Embedding",
              type: "embedding",
              source: "remote",
              provider: "provider",
              enabled: true,
              is_builtin: false,
              description: null,
              credential_status: "configured",
            },
          ]);
        if (url.pathname === "/api/v1/admin/weknora/kb-configs") return fulfill([]);
        if (url.pathname === "/api/v1/admin/audit") {
          if (scenario === "partial-failure")
            return fulfill({ detail: "SECRET audit failure" }, 503);
          return fulfill({
            items: empty
              ? []
              : [
                  {
                    id: "secret-audit-id",
                    log_type: "operation",
                    action: "config.permission_rule_updated",
                    actor_user_id: "secret-actor-id",
                    actor_name: "治理管理员",
                    actor_company_role: "boss",
                    actor_project_role: null,
                    target_type: "permission_rule",
                    target_id: "secret-rule-id",
                    severity: null,
                    is_processed: true,
                    processed_by: null,
                    processed_at: null,
                    trace_id: "secret-trace-id",
                    denied_reason: null,
                    risk_level: null,
                    created_at: "2026-08-14T01:00:00Z",
                    before_snapshot: null,
                    after_snapshot: null,
                    extra: null,
                  },
                ],
            total: empty ? 0 : 1,
            page: 1,
            page_size: 80,
            view: "governance",
          });
        }
        return fulfill({});
      });

      const page = await context.newPage();
      page.on("console", (message) => messages.push(message.text()));
      page.on("pageerror", (error) => messages.push(error.message));
      await page.goto(`${base}/admin`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "运营中枢" }).waitFor();
      await page.getByText("系统运行", { exact: true }).waitFor();

      if (scenario === "normal") {
        await page.getByText("入库失败", { exact: true }).waitFor();
        await page.getByText("更新权限规则", { exact: true }).waitFor();
      } else if (scenario === "empty") {
        await page.getByText("当前没有需要管理员处理的事项").waitFor();
      } else if (scenario === "partial-failure") {
        await page.getByText("部分工作区暂时无法读取", { exact: false }).waitFor();
      } else {
        await page.locator(".admin-runtime-item", { hasText: "微盘扫描" }).waitFor();
      }

      const screenshot = path.join(outDir, `${scenario}-${viewport.name}.png`);
      await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
      const result = await page.evaluate(() => {
        const text = document.body.innerText;
        const root = document.documentElement;
        return {
          titleVisible: Boolean(document.querySelector(".product-page-header h2")),
          sectionCount: document.querySelectorAll(".admin-overview-grid .product-section").length,
          primaryActionCount: document.querySelectorAll(
            ".product-page-actions .btn-primary:not(:disabled)",
          ).length,
          noHorizontalOverflow: root.scrollWidth <= root.clientWidth + 1,
          secretsHidden: ![
            "secret-ingest-id",
            "secret-file-name",
            "secret-model-ref",
            "secret-audit-id",
            "secret-rule-id",
            "SECRET audit failure",
          ].some((secret) => text.includes(secret)),
        };
      });
      const managerOnlyRequestedAllowedSources =
        scenario !== "scoped-manager" ||
        requestedAdminPaths.every(
          (pathname) =>
            pathname === "/api/v1/admin/wecom-scan/configs" ||
            pathname === "/api/v1/admin/weknora/models" ||
            pathname === "/api/v1/admin/weknora/kb-configs",
        );
      const unexpectedMessages = messages.filter(
        (message) =>
          !(scenario === "partial-failure" && message.includes("503 (Service Unavailable)")),
      );
      const passed =
        result.titleVisible &&
        result.sectionCount === 4 &&
        result.primaryActionCount === 1 &&
        result.noHorizontalOverflow &&
        result.secretsHidden &&
        managerOnlyRequestedAllowedSources &&
        unexpectedMessages.length === 0;
      results.push({
        page: "admin-overview",
        scenario,
        viewport: viewport.name,
        passed,
        screenshot,
        requestedAdminPaths,
        ...result,
        managerOnlyRequestedAllowedSources,
        messages,
        unexpectedMessages,
      });
      await context.close();
    }
  }
} finally {
  await browser?.close();
  await server?.close();
}

fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
console.log(
  JSON.stringify(
    { outDir, total: results.length, passed: results.filter((item) => item.passed).length },
    null,
    2,
  ),
);
if (results.some((item) => !item.passed)) process.exitCode = 1;
