import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5199);
const base = `http://127.0.0.1:${port}`;
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "pbc84-admin-operations");
fs.mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "1440", width: 1440, height: 1100 },
  { name: "1920", width: 1920, height: 1200 },
];
const scenarios = [
  "normal",
  "empty-failures",
  "indexing-error",
  "action-running",
  "action-completed",
  "forbidden",
];

const authMe = {
  user_id: "secret-auth-user-84",
  name: "运维验收管理员",
  email: "admin-secret@example.test",
  status: "active",
  company_roles: ["admin"],
  is_business_user: false,
  can_discover_l5: false,
  project_memberships: [],
};

const counts = {
  index_failed: 3,
  indexing: 2,
  not_indexed: 4,
  skipped: 1,
  parse_pending: 2,
  parse_processing: 1,
  kb_init_failed: 0,
};

const failure = {
  asset_id: "secret-asset-id-84",
  title: "绝不能显示的业务资产标题",
  scope: "project",
  project_name: "绝不能显示的项目名称",
  owner_name: "绝不能显示的人员名称",
  index_status: "index_failed",
  index_error_code: "SECRET_UPSTREAM_CODE",
  index_error_message: "索引服务暂时不可用",
  operator_error_message: "连接检查未通过，请确认平台配置。",
  remediation_hint: "storage_ref=s3://secret-bucket/private",
  severity: "critical",
  updated_at: "2026-07-17T02:30:00Z",
};

function job(status = "completed") {
  return {
    job_id: "secret-job-id-84",
    operation_type: "retry_index",
    status,
    scope_filter: { scope: "all" },
    requested_by_name: "绝不能显示的操作人",
    requested_at: "2026-07-17T02:30:00Z",
    started_at: "2026-07-17T02:31:00Z",
    finished_at: status === "completed" ? "2026-07-17T02:32:00Z" : null,
    total_count: 6,
    success_count: status === "completed" ? 5 : 0,
    failed_count: status === "completed" ? 1 : 0,
    skipped_count: 0,
    error_code: "SECRET_JOB_CODE",
    error_message: "SECRET JOB MESSAGE",
    trace_id: "secret-trace-id-84",
  };
}

const ingestItems = [
  {
    id: "secret-ingest-id-84",
    source: "path_b_upload",
    source_file_name: "绝不能显示的原始文件名.docx",
    status: "processing",
    target_scope: "project",
    confidentiality_level: "L4",
    ai_access_level: "A1",
    confidence: null,
    naming_compliant: null,
    extraction_status: "success",
    error_type: null,
    error_message: null,
    result_asset_id: null,
    created_at: "2026-07-17T02:20:00Z",
  },
  {
    id: "secret-ingest-id-85",
    source: "path_a_wecom",
    source_file_name: "绝不能显示的微盘文件名.pdf",
    status: "pending_confirmation",
    target_scope: "company",
    confidentiality_level: "L3",
    ai_access_level: "A2",
    confidence: null,
    naming_compliant: null,
    extraction_status: "success",
    error_type: null,
    error_message: null,
    result_asset_id: null,
    created_at: "2026-07-17T02:10:00Z",
  },
];

const forbiddenPaths = new Set([
  "/api/v1/admin/ingest",
  "/admin/ops/indexing",
  "/admin/ops/indexing/jobs",
]);
const forbiddenBody = { detail: "SECRET forbidden diagnostic" };

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
      const context = await browser.newContext({ viewport });
      const browserMessages = [];
      let retryCalls = 0;

      await context.route("**/*", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const method = request.method();
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

        if (!url.pathname.startsWith("/api/") && !url.pathname.startsWith("/admin/ops/")) {
          return route.continue();
        }
        if (url.pathname === "/api/v1/auth/me") return fulfill(authMe);
        if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "safe-csrf-84" });
        if (url.pathname === "/api/v1/weknora/model-options") {
          return fulfill({ items: [], default_missing: false });
        }
        if (scenario === "forbidden" && forbiddenPaths.has(url.pathname)) {
          return fulfill(forbiddenBody, 403);
        }
        if (url.pathname === "/api/v1/admin/ingest") {
          return fulfill({ items: ingestItems, total: ingestItems.length });
        }
        if (url.pathname === "/admin/ops/indexing/jobs") {
          const items = scenario === "action-running" ? [job("running")] : [];
          return fulfill({ items, total: items.length });
        }
        if (url.pathname === "/admin/ops/indexing/retry" && method === "POST") {
          retryCalls += 1;
          return fulfill(job("completed"));
        }
        if (url.pathname === "/admin/ops/indexing/reparse" && method === "POST") {
          return fulfill({ ...job("completed"), operation_type: "reparse" });
        }
        if (url.pathname === "/admin/ops/indexing") {
          if (scenario === "indexing-error") {
            return fulfill({ detail: "SECRET upstream indexing body" }, 500);
          }
          const empty = scenario === "empty-failures";
          return fulfill({
            counts: empty ? { ...counts, index_failed: 0 } : counts,
            recent_failed: empty ? [] : [failure],
            title_visible: true,
          });
        }
        return fulfill({});
      });

      const page = await context.newPage();
      page.on("console", (message) => browserMessages.push(message.text()));
      page.on("pageerror", (error) => browserMessages.push(error.message));
      await page.goto(`${base}/admin/ingest`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "管理员运维" }).waitFor();

      if (scenario === "normal") {
        await page.getByText("连接检查未通过，请确认平台配置。").waitFor();
      } else if (scenario === "empty-failures") {
        await page.getByText("当前没有索引失败任务").waitFor();
      } else if (scenario === "indexing-error") {
        await page.getByText("索引状态暂时无法加载").waitFor();
      } else if (scenario === "action-running") {
        await page.getByRole("button", { name: "作业执行中" }).waitFor();
      } else if (scenario === "action-completed") {
        await page.getByRole("button", { name: "批量重试索引" }).click();
        await page.getByText(/批量重试索引已提交：共 6 项/).waitFor();
      } else if (scenario === "forbidden") {
        await page.getByText("入库概览暂时无法加载。").waitFor();
      }

      const screenshot = path.join(outDir, `${scenario}-${viewport.name}.png`);
      await page.screenshot({ path: screenshot, animations: "disabled", fullPage: true });

      const result = await page.evaluate((scenarioName) => {
        const text = document.body.innerText;
        const root = document.documentElement;
        const consoleGrid = document.querySelector(".ao84-console")?.getBoundingClientRect();
        const panels = [...document.querySelectorAll(".ao84-console > .ao84-panel")].map((node) =>
          node.getBoundingClientRect(),
        );
        const tabs = [...document.querySelectorAll(".ao84-tabs a")].map((node) =>
          node.getBoundingClientRect(),
        );
        const sensitiveTerms = [
          "secret-asset-id-84",
          "secret-job-id-84",
          "secret-trace-id-84",
          "绝不能显示的业务资产标题",
          "绝不能显示的项目名称",
          "绝不能显示的人员名称",
          "绝不能显示的原始文件名",
          "绝不能显示的微盘文件名",
          "绝不能显示的操作人",
          "storage_ref",
          "SECRET_UPSTREAM_CODE",
          "SECRET_JOB_CODE",
          "SECRET JOB MESSAGE",
          "SECRET forbidden diagnostic",
          "SECRET upstream indexing body",
        ];
        const internalTerms = [
          "index_failed",
          "not_indexed",
          "parse_pending",
          "retry_index",
          "path_b_upload",
          "path_a_wecom",
        ];
        return {
          scenario: scenarioName,
          overflowX: root.scrollWidth - root.clientWidth,
          clippedControls: [...document.querySelectorAll("a, button, select")].filter(
            (node) => node.scrollWidth > node.clientWidth + 2,
          ).length,
          consoleVisible: Boolean(consoleGrid && consoleGrid.width > 900),
          panelCount: panels.length,
          leftNarrower: panels.length === 2 && panels[0].width < panels[1].width,
          alignedPanels: panels.length === 2 && Math.abs(panels[0].top - panels[1].top) <= 1,
          equalTabs:
            tabs.length === 3 &&
            Math.max(...tabs.map((tab) => tab.width)) - Math.min(...tabs.map((tab) => tab.width)) <=
              2,
          activeTab: document
            .querySelector('.ao84-tabs a[aria-current="page"]')
            ?.textContent?.includes("索引维护"),
          exactHeading:
            text.includes("管理员运维") && text.includes("查看索引运行、扫描任务和安全审计状态。"),
          refreshOnly: document.querySelectorAll(".product-page-actions button").length === 1,
          safeText: sensitiveTerms.every((term) => !text.includes(term)),
          localizedText: internalTerms.every((term) => !text.includes(term)),
          emptyVisible: text.includes("当前没有索引失败任务"),
          indexingErrorVisible:
            text.includes("索引状态暂时无法加载") &&
            text.includes("失败任务暂时无法加载") &&
            text.includes("共 2 项"),
          runningLocked:
            [...document.querySelectorAll(".ao84-action-buttons button")].length === 2 &&
            [...document.querySelectorAll(".ao84-action-buttons button")].every(
              (button) => button.disabled,
            ),
          completedVisible: text.includes("批量重试索引已提交：共 6 项"),
          forbiddenVisible:
            text.includes("索引状态暂时无法加载") &&
            text.includes("失败任务暂时无法加载") &&
            text.includes("入库概览暂时无法加载"),
        };
      }, scenario);

      result.consoleLeak = browserMessages.some((message) =>
        /secret|storage_ref|token/i.test(message),
      );
      result.retryCalls = retryCalls;
      const basePass =
        result.overflowX <= 2 &&
        result.clippedControls === 0 &&
        result.consoleVisible &&
        result.panelCount === 2 &&
        result.leftNarrower &&
        result.alignedPanels &&
        result.equalTabs &&
        result.activeTab &&
        result.exactHeading &&
        result.refreshOnly &&
        result.safeText &&
        result.localizedText &&
        !result.consoleLeak;
      const scenarioPass = {
        normal: true,
        "empty-failures": result.emptyVisible,
        "indexing-error": result.indexingErrorVisible,
        "action-running": result.runningLocked,
        "action-completed": result.completedVisible && result.retryCalls === 1,
        forbidden: result.forbiddenVisible,
      }[scenario];
      result.pass = Boolean(basePass && scenarioPass);
      results.push({ viewport: viewport.name, screenshot, ...result });
      await context.close();
    }
  }
} finally {
  await browser?.close();
  await server?.close();
}

const reportPath = path.join(outDir, "report.json");
fs.writeFileSync(reportPath, JSON.stringify(results, null, 2));
console.log(JSON.stringify({ outDir, reportPath, results }, null, 2));
if (results.some((result) => !result.pass)) process.exitCode = 1;
