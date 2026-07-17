import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5200);
const base = `http://127.0.0.1:${port}`;
const outDir = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "pbc85-admin-operations-closure",
);
fs.mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "1440", width: 1440, height: 1100 },
  { name: "1920", width: 1920, height: 1200 },
];
const scenarios = [
  "normal-trend",
  "category-filter",
  "insufficient-data",
  "worker-stale",
  "beat-stale",
  "target-running",
  "target-success",
  "target-conflict",
  "indexing-error",
  "health-error",
  "forbidden",
  "empty",
];

const authMe = {
  user_id: "secret-admin-user-85",
  name: "运维闭环验收管理员",
  email: "secret-admin@example.test",
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
const failure = (overrides = {}) => ({
  asset_id: "secret-target-asset-85",
  title: "绝不能显示的业务标题",
  scope: "project",
  project_name: "绝不能显示的项目名称",
  owner_name: "绝不能显示的人员名称",
  index_status: "index_failed",
  index_error_code: "weknora_call_failed",
  index_error_message: "知识底座暂时不可用",
  operator_error_message: "连接检查未通过，请确认平台配置。",
  remediation_hint: "storage_ref=s3://secret/private",
  severity: "error",
  diagnostic_category: "external_service",
  diagnostic_label: "外部服务",
  retry_eligible: true,
  updated_at: "2026-07-17T02:30:00Z",
  ...overrides,
});
const job = (status = "completed") => ({
  job_id: "secret-job-id-85",
  operation_type: "retry_index",
  status,
  scope_filter: { scope: "project" },
  requested_by_name: "绝不能显示的操作人",
  requested_at: "2026-07-17T02:30:00Z",
  started_at: "2026-07-17T02:31:00Z",
  finished_at: status === "completed" ? "2026-07-17T02:32:00Z" : null,
  total_count: 1,
  success_count: status === "completed" ? 1 : 0,
  failed_count: 0,
  skipped_count: 0,
  error_code: "SECRET_JOB_CODE",
  error_message: "SECRET JOB MESSAGE",
  trace_id: "secret-trace-id-85",
});
const bucket = (hour, completed, failed) => ({
  observed_at: `2026-07-17T${String(hour).padStart(2, "0")}:00:00Z`,
  ...counts,
  completed_jobs: completed,
  failed_jobs: failed,
  queued_jobs: 0,
  oldest_queued_seconds: null,
});
const health = (scenario) => {
  const insufficient = scenario === "insufficient-data";
  const workerStale = scenario === "worker-stale";
  const beatStale = scenario === "beat-stale";
  return {
    generated_at: "2026-07-17T03:00:00Z",
    window_hours: 24,
    insufficient_data: insufficient,
    message: insufficient ? "正在积累运维数据" : "最近运行趋势已更新",
    queue: {
      status: "healthy",
      queued_count: 0,
      oldest_queued_seconds: null,
      message: "索引作业队列运行正常。",
    },
    worker: {
      status: workerStale ? "stale" : "healthy",
      last_heartbeat_at: workerStale ? "2026-07-17T01:00:00Z" : "2026-07-17T02:59:00Z",
      message: workerStale ? "最近心跳已过期，请检查运行服务。" : "任务执行进程心跳正常。",
    },
    beat: {
      status: beatStale ? "stale" : "healthy",
      last_heartbeat_at: beatStale ? "2026-07-17T01:00:00Z" : "2026-07-17T02:59:00Z",
      message: beatStale ? "最近心跳已过期，请检查运行服务。" : "定时调度进程心跳正常。",
    },
    trend_points: insufficient
      ? [bucket(2, 2, 1)]
      : [bucket(0, 1, 0), bucket(1, 3, 1), bucket(2, 2, 0)],
  };
};
const ingest = {
  items: [
    {
      id: "secret-ingest-id-85",
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
  ],
  total: 1,
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

  for (const scenario of scenarios) {
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport });
      const messages = [];
      let targetCalls = 0;
      let releaseTarget;
      await context.route("**/*", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
        if (!url.pathname.startsWith("/api/") && !url.pathname.startsWith("/admin/ops/")) {
          return route.continue();
        }
        if (url.pathname === "/api/v1/auth/me") return fulfill(authMe);
        if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "safe-csrf-85" });
        if (url.pathname === "/api/v1/weknora/model-options")
          return fulfill({ items: [], default_missing: false });
        const forbidden = scenario === "forbidden";
        if (url.pathname === "/api/v1/admin/ingest") {
          return forbidden ? fulfill({ detail: "SECRET denial" }, 403) : fulfill(ingest);
        }
        if (url.pathname === "/admin/ops/indexing/health") {
          if (forbidden) return fulfill({ detail: "SECRET denial" }, 403);
          if (scenario === "health-error") return fulfill({ detail: "SECRET health payload" }, 500);
          return fulfill(health(scenario));
        }
        if (url.pathname === "/admin/ops/indexing/jobs") {
          const items = scenario === "target-running" ? [job("running")] : [];
          return forbidden
            ? fulfill({ detail: "SECRET denial" }, 403)
            : fulfill({ items, total: items.length });
        }
        if (url.pathname.endsWith("/retry") && url.pathname.includes("/failures/")) {
          targetCalls += 1;
          if (scenario === "target-running") {
            await new Promise((resolve) => (releaseTarget = resolve));
          }
          if (scenario === "target-conflict") {
            return fulfill(
              { detail: { denied_reason: "target_retry_in_progress", message: "SECRET conflict" } },
              409,
            );
          }
          return fulfill(job("completed"), 202);
        }
        if (
          url.pathname === "/admin/ops/indexing/retry" ||
          url.pathname === "/admin/ops/indexing/reparse"
        ) {
          return fulfill(job("completed"), 202);
        }
        if (url.pathname === "/admin/ops/indexing") {
          if (forbidden) return fulfill({ detail: "SECRET denial" }, 403);
          if (scenario === "indexing-error")
            return fulfill({ detail: "SECRET indexing payload" }, 500);
          const empty = scenario === "empty";
          const retryEligible = scenario !== "target-running";
          return fulfill({
            counts: empty ? { ...counts, index_failed: 0 } : counts,
            recent_failed: empty
              ? []
              : [
                  failure({ retry_eligible: retryEligible }),
                  failure({
                    asset_id: "secret-config-target-85",
                    diagnostic_category: "configuration",
                    diagnostic_label: "配置问题",
                    operator_error_message: "请完成平台默认模型配置。",
                    retry_eligible: false,
                  }),
                ],
            diagnostic_counts: {
              configuration: empty ? 0 : 1,
              external_service: empty ? 0 : 2,
              source_content: 0,
              permission: 0,
              platform: 0,
              unknown: 0,
            },
            title_visible: false,
          });
        }
        return fulfill({});
      });

      const page = await context.newPage();
      page.on("console", (message) => messages.push(message.text()));
      page.on("pageerror", (error) => messages.push(error.message));
      await page.goto(`${base}/admin/ingest`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "管理员运维" }).waitFor();

      if (scenario === "category-filter") {
        await page.locator(".ao85-diagnostics button", { hasText: "配置问题" }).click();
        await page.getByText("请完成平台默认模型配置。").waitFor();
      } else if (scenario === "target-success" || scenario === "target-conflict") {
        await page.locator(".ao85-target-retry").first().click();
        await page.getByText("此操作仅重新尝试索引，不查看、不下载、不修改原文。").waitFor();
        await page.getByRole("button", { name: "确认重试" }).click();
        await page
          .getByText(
            scenario === "target-success"
              ? /单条索引重试已提交：共 1 项/
              : "任务状态已变化或正在执行，请刷新后重试。",
          )
          .waitFor();
      } else if (scenario === "target-running") {
        await page.getByRole("button", { name: "作业执行中" }).waitFor();
      } else if (scenario === "insufficient-data") {
        await page.getByText("正在积累运维数据").waitFor();
      } else if (scenario === "worker-stale" || scenario === "beat-stale") {
        await page.getByText("心跳过期").waitFor();
      } else if (scenario === "indexing-error") {
        await page.getByText("索引状态暂时无法加载").waitFor();
      } else if (scenario === "health-error") {
        await page.getByText("运行健康暂时无法加载。").waitFor();
      } else if (scenario === "forbidden") {
        await page.getByText("入库概览暂时无法加载。").waitFor();
      } else if (scenario === "empty") {
        await page.getByText("当前没有索引失败任务").waitFor();
      } else {
        await page.getByLabel("最近 24 小时索引作业趋势").waitFor();
      }

      const screenshot = path.join(outDir, `${scenario}-${viewport.name}.png`);
      await page.screenshot({ path: screenshot, animations: "disabled", fullPage: true });
      releaseTarget?.();
      const result = await page.evaluate((scenarioName) => {
        const text = document.body.innerText;
        const root = document.documentElement;
        const panels = [...document.querySelectorAll(".ao84-console > .ao84-panel")].map((node) =>
          node.getBoundingClientRect(),
        );
        const secrets = [
          "secret-target-asset-85",
          "secret-config-target-85",
          "secret-job-id-85",
          "secret-trace-id-85",
          "绝不能显示的业务标题",
          "绝不能显示的项目名称",
          "绝不能显示的人员名称",
          "绝不能显示的原始文件名",
          "storage_ref",
          "SECRET_JOB_CODE",
          "SECRET JOB MESSAGE",
          "SECRET denial",
          "SECRET health payload",
          "SECRET indexing payload",
          "SECRET conflict",
        ];
        const enums = [
          "index_failed",
          "retry_index",
          "external_service",
          "configuration",
          "healthy",
          "stale",
        ];
        return {
          scenario: scenarioName,
          overflowX: root.scrollWidth - root.clientWidth,
          clipped: [...document.querySelectorAll("a, button, select")].filter(
            (node) => node.scrollWidth > node.clientWidth + 2,
          ).length,
          panels: panels.length,
          leftNarrower: panels.length === 2 && panels[0].width < panels[1].width,
          safe: secrets.every((term) => !text.includes(term)),
          localized: enums.every((term) => !text.includes(term)),
          healthVisible: text.includes("运行健康"),
          trendVisible: Boolean(document.querySelector(".ao85-trend")),
          insufficient: text.includes("正在积累运维数据"),
          stale: text.includes("心跳过期"),
          categoryFiltered:
            text.includes("请完成平台默认模型配置。") &&
            !text.includes("连接检查未通过，请确认平台配置。"),
          success: text.includes("单条索引重试已提交：共 1 项"),
          conflict: text.includes("任务状态已变化或正在执行，请刷新后重试。"),
          targetHidden: !document.querySelector(".ao85-target-retry"),
          indexingError: text.includes("索引状态暂时无法加载"),
          healthError: text.includes("运行健康暂时无法加载"),
          forbidden: text.includes("入库概览暂时无法加载") && text.includes("索引状态暂时无法加载"),
          empty: text.includes("当前没有索引失败任务"),
        };
      }, scenario);
      result.consoleLeak = messages.some((message) => /secret|storage_ref|token/i.test(message));
      result.targetCalls = targetCalls;
      const scenarioPass = {
        "normal-trend": result.trendVisible,
        "category-filter": result.categoryFiltered,
        "insufficient-data": result.insufficient && !result.trendVisible,
        "worker-stale": result.stale,
        "beat-stale": result.stale,
        "target-running": result.targetHidden,
        "target-success": result.success && result.targetCalls === 1,
        "target-conflict": result.conflict && result.targetCalls === 1,
        "indexing-error": result.indexingError,
        "health-error": result.healthError,
        forbidden: result.forbidden,
        empty: result.empty,
      }[scenario];
      result.pass = Boolean(
        result.overflowX <= 2 &&
        result.clipped === 0 &&
        result.panels === 2 &&
        result.leftNarrower &&
        result.safe &&
        result.localized &&
        result.healthVisible &&
        !result.consoleLeak &&
        scenarioPass,
      );
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
