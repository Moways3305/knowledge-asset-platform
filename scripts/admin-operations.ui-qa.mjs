import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5200);
const externalBase = process.env.UI_QA_BASE?.replace(/\/$/, "") || null;
const base = externalBase || `http://127.0.0.1:${port}`;
const outDir = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "admin-operations",
);
fs.mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "1440", width: 1440, height: 1100 },
  { name: "1024", width: 1024, height: 900 },
  { name: "390", width: 390, height: 844 },
];
const scenarios = [
  "normal-trend",
  "parse-only",
  "category-filter",
  "view-all",
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
  "timeout-recovery",
];

const authMe = {
  user_id: "secret-admin-user-85",
  name: "运维闭环验收管理员",
  email: "secret-admin@example.test",
  status: "active",
  company_roles: ["admin"],
  active_company_role: "admin",
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
  retry_target: "opaque-retry-target-85",
  title: "（业务资产标题已隐藏）",
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
  recovery_state: "interrupted",
  wait_seconds: 3600,
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
const shortTrend = [bucket(0, 1, 0), bucket(1, 3, 1), bucket(2, 2, 0)];
const fullTrend = Array.from({ length: 24 }, (_, index) => {
  if (index < shortTrend.length) return shortTrend[index];
  return bucket(index, index % 4, index % 5 === 0 ? 1 : 0);
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
    trend_points: insufficient ? [bucket(2, 2, 1)] : scenario === "empty" ? shortTrend : fullTrend,
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
  projects: { status: "empty", error_code: null, items: [], total: 0 },
  recent_activity: { status: "empty", error_code: null, items: [], total: 0 },
};

let server;
let browser;
const results = [];
try {
  if (!externalBase) {
    await build({ logLevel: "warn" });
    server = await preview({
      preview: { host: "127.0.0.1", port, strictPort: true },
      logLevel: "warn",
    });
  }
  browser = await chromium.launch({ args: ["--disable-gpu"] });

  for (const scenario of scenarios) {
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport });
      const messages = [];
      let targetCalls = 0;
      let targetPathSafe = true;
      let conflictObserved = false;
      let targetReadOnlyObserved = false;
      let timeoutRecoveryCalls = 0;
      let timeoutRecoveryPayloadValid = false;
      let timeoutRecoveryScreenshot = null;
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
        if (url.pathname === "/api/v1/workbench/overview") return fulfill(workbenchOverview);
        if (url.pathname === "/api/v1/notifications")
          return fulfill({
            items: [],
            total: 0,
            page: 1,
            page_size: 20,
            unread_count: 0,
            categories: [],
          });
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
        if (url.pathname === "/admin/ops/ingest/processing-timeout-recovery") {
          timeoutRecoveryCalls += 1;
          const body = request.postDataJSON?.() ?? {};
          const executing = body.dry_run === false;
          timeoutRecoveryPayloadValid =
            timeoutRecoveryPayloadValid ||
            (executing &&
              body.confirm === true &&
              body.limit === 3 &&
              body.expected_oom_kill_count === 4);
          return fulfill({
            dry_run: !executing,
            scanned: 35,
            candidates: 35,
            source_unavailable: 0,
            selected: executing ? 3 : 0,
            claimed: executing ? 3 : 0,
            enqueued: executing ? 3 : 0,
            conflicts: 0,
            stopped: false,
            stop_reason: null,
            preflight: {
              redis_ready: true,
              ocr_worker_ready: true,
              queue_within_budget: true,
              oom_kill_count: 4,
              ready: true,
              reason: null,
            },
            next_batch_not_before: executing ? "2026-09-01T08:00:15Z" : null,
          });
        }
        if (url.pathname.endsWith("/retry") && url.pathname.includes("/failures/")) {
          targetCalls += 1;
          targetPathSafe =
            targetPathSafe &&
            url.pathname.includes("opaque-retry-target-85") &&
            !url.pathname.includes("secret-target-asset-85");
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
          const parseOnly = scenario === "parse-only";
          const retryEligible = scenario !== "target-running";
          const allRecoveryItems = [
            failure({ retry_eligible: retryEligible }),
            failure({
              retry_target: null,
              diagnostic_category: "configuration",
              diagnostic_label: "配置问题",
              operator_error_message: "请完成平台默认模型配置。",
              retry_eligible: false,
              recovery_state: "failed",
            }),
            failure({
              retry_target: "opaque-failed-target-86",
              operator_error_message: "索引提交失败，可再次恢复。",
              recovery_state: "failed",
              wait_seconds: 2400,
            }),
            failure({
              retry_target: "opaque-waiting-target-87",
              operator_error_message: "正在等待可用运行资源。",
              recovery_state: "waiting",
              wait_seconds: 1200,
            }),
            failure({
              retry_target: "opaque-waiting-target-88",
              operator_error_message: "恢复请求正在排队。",
              recovery_state: "waiting",
              wait_seconds: 600,
            }),
            failure({
              retry_target: "opaque-skipped-target-89",
              operator_error_message: "当前条件不满足，已安全跳过。",
              recovery_state: "skipped",
              wait_seconds: 300,
            }),
            failure({
              retry_target: "opaque-skipped-target-90",
              operator_error_message: "等待治理范围确认。",
              recovery_state: "skipped",
              wait_seconds: 240,
            }),
            failure({
              retry_target: "opaque-skipped-target-91",
              operator_error_message: "等待恢复条件满足。",
              recovery_state: "skipped",
              wait_seconds: 180,
            }),
          ];
          const visibleRecoveryItems =
            url.searchParams.get("include_all") === "true"
              ? allRecoveryItems
              : allRecoveryItems.slice(0, 4);
          return fulfill({
            counts: empty
              ? { ...counts, index_failed: 0, not_indexed: 0, skipped: 0, parse_failed: 0 }
              : parseOnly
                ? { ...counts, index_failed: 0, not_indexed: 0, skipped: 0, parse_failed: 5 }
                : counts,
            reparse_actionable_count: parseOnly ? 2 : 0,
            recent_failed:
              empty || parseOnly
                ? []
                : [
                    failure({ retry_eligible: retryEligible }),
                    failure({
                      retry_target: null,
                      diagnostic_category: "configuration",
                      diagnostic_label: "配置问题",
                      operator_error_message: "请完成平台默认模型配置。",
                      retry_eligible: false,
                    }),
                  ],
            recovery_items: empty || parseOnly ? [] : visibleRecoveryItems,
            recovery_summary: {
              interrupted: empty || parseOnly ? 0 : 1,
              needs_recovery: empty || parseOnly ? 0 : 8,
              processing: 2,
              searchable: 18,
            },
            last_reconcile: {
              observed_at: "2026-08-17T10:30:00Z",
              processed: 50,
              updated: 1,
              failed: empty ? 0 : 2,
              duration_ms: 420,
            },
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
        if (url.pathname === "/admin/ops/llm-usage") {
          return fulfill({ days: 14, items: [] });
        }
        return fulfill({});
      });

      const page = await context.newPage();
      page.on("console", (message) => messages.push(message.text()));
      page.on("pageerror", (error) => messages.push(error.message));
      await page.goto(`${base}/admin/ingest`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "索引恢复控制台" }).waitFor();
      const outerRuntimeDetails = page.locator(".irc-runtime-details");
      await outerRuntimeDetails.locator(":scope > summary").click();
      const runtimeDetails = page.locator(".ao85-runtime-details");
      const runtimeSummary = runtimeDetails.locator("summary");
      await runtimeSummary.click();

      if (scenario === "category-filter") {
        await page.getByLabel("诊断类别筛选").selectOption("configuration");
        await page.getByText("请完成平台默认模型配置。").waitFor();
      } else if (scenario === "view-all") {
        await page.getByRole("button", { name: "查看全部 8 项" }).click();
        await page.getByText("当前条件不满足，已安全跳过。").waitFor();
      } else if (scenario === "target-success" || scenario === "target-conflict") {
        await page.locator(".ao85-target-retry").first().click();
        await page.getByText("此操作仅重新发起索引恢复，不查看、不下载、不修改原文。").waitFor();
        await page.getByRole("button", { name: "确认恢复" }).click();
        await page
          .getByText(
            scenario === "target-success"
              ? /单条索引恢复已到达终态：共 1 项/
              : "任务状态已变化或正在执行，请刷新后重试。",
          )
          .waitFor();
        if (scenario === "target-conflict") {
          conflictObserved = true;
          await page.getByRole("button", { name: "取消" }).click();
        }
      } else if (scenario === "target-running") {
        await page.getByRole("button", { name: "正在执行：恢复索引" }).first().waitFor();
        await page.locator(".ao85-target-retry").first().click();
        targetReadOnlyObserved = await page.getByRole("button", { name: "确认恢复" }).isDisabled();
        await page.getByRole("button", { name: "取消" }).click();
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
        await page.getByText("当前没有待恢复索引").first().waitFor();
      } else if (scenario === "timeout-recovery") {
        await page.getByRole("button", { name: "检查超时任务" }).click();
        const timeoutPanel = page.getByLabel("入库运行概览");
        await timeoutPanel.getByText("35", { exact: true }).waitFor();
        page.once("dialog", (dialog) => dialog.accept());
        await page.getByRole("button", { name: "二次确认并恢复最多 3 条" }).click();
        await page.waitForFunction(() =>
          [...document.querySelectorAll("button")].some(
            (button) => button.textContent?.includes("二次确认并恢复最多 3 条") && button.disabled,
          ),
        );
        timeoutRecoveryScreenshot = path.join(outDir, `timeout-recovery-open-${viewport.name}.png`);
        await page.screenshot({
          path: timeoutRecoveryScreenshot,
          animations: "disabled",
          fullPage: true,
        });
      } else {
        await page.getByLabel("近 24 小时索引运维趋势").waitFor();
      }

      await runtimeSummary.click();
      await outerRuntimeDetails.locator(":scope > summary").click();
      const trendInitiallyDeferred = await outerRuntimeDetails.evaluate((node) => !node.open);
      await page.evaluate(() => {
        window.scrollTo(0, 0);
        document.querySelectorAll("*").forEach((node) => {
          if (node instanceof HTMLElement && node.scrollTop > 0) node.scrollTop = 0;
        });
      });
      const screenshot = path.join(outDir, `${scenario}-${viewport.name}.png`);
      await page.screenshot({ path: screenshot, animations: "disabled", fullPage: true });
      await outerRuntimeDetails.locator(":scope > summary").click();
      await runtimeSummary.click();

      const trendExpected = !["insufficient-data", "health-error", "forbidden"].includes(scenario);
      const trendReadability = {
        legendVisible: false,
        tickCount: 0,
        accessiblePoints: false,
        detailInitiallyHidden: false,
        hoverDetailVisible: false,
        focusDetailVisible: false,
        detailHidesAfterLeave: false,
        detailContained: false,
        noUnexpectedTrend: false,
      };
      if (trendExpected) {
        const legend = page.locator(".ao85-trend-legend");
        await legend.getByText("深蓝：已完成索引运维作业数").waitFor();
        await legend.getByText("红色：失败或部分失败的索引运维作业数").waitFor();
        trendReadability.legendVisible = true;
        trendReadability.tickCount = await page.locator(".ao85-trend-tick:not(.is-hidden)").count();
        const points = page.locator(".ao85-trend-point");
        const pointLabels = await points.evaluateAll((nodes) =>
          nodes.map((node) => node.getAttribute("aria-label") || ""),
        );
        const expectedPointCount = scenario === "empty" ? 3 : 24;
        trendReadability.accessiblePoints =
          pointLabels.length === expectedPointCount &&
          pointLabels.every(
            (label) =>
              label.includes("已完成作业") &&
              label.includes("失败或部分失败作业") &&
              label.includes("排队作业") &&
              label.includes("索引失败存量") &&
              !label.includes("T02:") &&
              !label.includes("Z"),
          );
        const detailPoint = points.nth(1);
        const detail = detailPoint.locator('[role="tooltip"]');
        trendReadability.detailInitiallyHidden = await detail.isHidden();
        await detailPoint.hover();
        await detail.waitFor({ state: "visible" });
        const tooltipText = (await detail.textContent()) || "";
        trendReadability.hoverDetailVisible =
          tooltipText.includes("已完成作业 3") &&
          tooltipText.includes("失败或部分失败作业 1") &&
          tooltipText.includes("排队作业 0") &&
          tooltipText.includes("索引失败存量 3");
        const trendBox = await page.locator(".ao85-trend").boundingBox();
        const detailBox = await detail.boundingBox();
        trendReadability.detailContained = Boolean(
          trendBox &&
          detailBox &&
          detailBox.x >= trendBox.x - 1 &&
          detailBox.x + detailBox.width <= trendBox.x + trendBox.width + 1 &&
          detailBox.y >= trendBox.y - 1 &&
          detailBox.y + detailBox.height <= trendBox.y + trendBox.height + 1,
        );
        await page.locator(".ao85-trend-heading").hover();
        await detail.waitFor({ state: "hidden" });
        trendReadability.detailHidesAfterLeave = true;
        await detailPoint.focus();
        await detail.waitFor({ state: "visible" });
        trendReadability.focusDetailVisible = true;
      } else {
        trendReadability.noUnexpectedTrend = (await page.locator(".ao85-trend").count()) === 0;
      }

      releaseTarget?.();
      const result = await page.evaluate((scenarioName) => {
        const text = document.body.innerText;
        const root = document.documentElement;
        const recoveryOverview = document
          .querySelector(".irc-recovery-overview")
          ?.getBoundingClientRect();
        const taskPanel = document.querySelector(".ao84-failures")?.getBoundingClientRect();
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
        const failureWrap = document.querySelector(".ao84-failures .irc-task-list-wrap");
        const failureState = failureWrap?.querySelector(".ao84-table-state");
        const mobileFailureLayout =
          root.clientWidth > 640 ||
          Boolean(
            failureWrap &&
            failureWrap.scrollWidth <= failureWrap.clientWidth + 2 &&
            [...failureWrap.querySelectorAll(".irc-task-list > li")].every(
              (row) => getComputedStyle(row).display === "grid",
            ),
          );
        const stateRect = failureState?.getBoundingClientRect();
        return {
          scenario: scenarioName,
          overflowX: root.scrollWidth - root.clientWidth,
          clipped: [...document.querySelectorAll("a, button, select")].filter(
            (node) => node.scrollWidth > node.clientWidth + 2,
          ).length,
          panels: Number(Boolean(recoveryOverview)) + Number(Boolean(taskPanel)),
          dispositionFirst: Boolean(
            recoveryOverview &&
            taskPanel &&
            recoveryOverview.y < taskPanel.y &&
            Math.abs(recoveryOverview.width - taskPanel.width) <= 2,
          ),
          safe: secrets.every((term) => !text.includes(term)),
          localized: enums.every((term) => !text.includes(term)),
          noInstructionCopy: !text.includes("优先恢复失败、卡住和待确认的入库与索引任务。"),
          mobileFailureLayout,
          compactFailureState:
            root.clientWidth > 640 ||
            !failureState ||
            Boolean(
              stateRect &&
              stateRect.width <= (failureWrap?.clientWidth ?? 0) + 2 &&
              stateRect.height <= 180,
            ),
          healthVisible: text.includes("运行健康"),
          trendVisible: Boolean(document.querySelector(".ao85-trend")),
          insufficient: text.includes("正在积累运维数据"),
          stale: text.includes("心跳过期"),
          categoryFiltered:
            text.includes("请完成平台默认模型配置。") &&
            !text.includes("连接检查未通过，请确认平台配置。"),
          success: text.includes("单条索引恢复已到达终态：共 1 项") && text.includes("作业已完成"),
          conflict: text.includes("任务状态已变化或正在执行，请刷新后重试。"),
          targetLocked:
            document.querySelectorAll(".ao85-target-retry").length > 0 &&
            [...document.querySelectorAll(".ao85-target-retry")].every((button) => button.disabled),
          indexingError: text.includes("索引状态暂时无法加载"),
          healthError: text.includes("运行健康暂时无法加载"),
          forbidden: text.includes("入库概览暂时无法加载") && text.includes("索引状态暂时无法加载"),
          empty: text.includes("当前没有待恢复索引"),
          parseRuntimeAction: Boolean(
            [...document.querySelectorAll("button")].find(
              (button) => button.textContent?.includes("重新解析（2 项）") && !button.disabled,
            ),
          ),
          viewAll: text.includes("当前条件不满足，已安全跳过。") && text.includes("收起为优先项"),
          oldTabsRemoved:
            !document.querySelector('[aria-label="管理员运维页面"]') &&
            !document.querySelector(".ao84-tabs"),
          recoveryHierarchy:
            text.includes("索引恢复控制台") &&
            text.includes("让未完成索引恢复为可检索资料") &&
            text.includes("已入库") &&
            text.includes("索引提交") &&
            (text.includes("解析中") || text.includes("中断待恢复")) &&
            text.includes("可检索"),
        };
      }, scenario);
      result.consoleLeak = messages.some((message) => /secret|storage_ref|token/i.test(message));
      result.targetCalls = targetCalls;
      result.targetPathSafe = targetPathSafe;
      result.conflict = result.conflict || conflictObserved;
      result.targetReadOnly = targetReadOnlyObserved;
      result.trendInitiallyDeferred = trendInitiallyDeferred;
      Object.assign(result, trendReadability);
      const scenarioPass = {
        "normal-trend": result.trendVisible,
        "parse-only": result.parseRuntimeAction,
        "category-filter": result.categoryFiltered,
        "view-all": result.viewAll,
        "insufficient-data": result.insufficient && !result.trendVisible,
        "worker-stale": result.stale,
        "beat-stale": result.stale,
        "target-running": result.targetReadOnly,
        "target-success": result.success && result.targetCalls === 1 && result.targetPathSafe,
        "target-conflict": result.conflict && result.targetCalls === 1 && result.targetPathSafe,
        "indexing-error": result.indexingError,
        "health-error": result.healthError,
        forbidden: result.forbidden,
        empty: result.empty,
        "timeout-recovery":
          timeoutRecoveryCalls === 2 &&
          timeoutRecoveryPayloadValid &&
          Boolean(timeoutRecoveryScreenshot),
      }[scenario];
      result.pass = Boolean(
        result.overflowX <= 2 &&
        result.clipped === 0 &&
        result.panels === 2 &&
        result.dispositionFirst &&
        result.trendInitiallyDeferred &&
        result.safe &&
        result.localized &&
        result.noInstructionCopy &&
        result.oldTabsRemoved &&
        result.mobileFailureLayout &&
        result.compactFailureState &&
        result.healthVisible &&
        (["indexing-error", "forbidden"].includes(scenario) || result.recoveryHierarchy) &&
        !result.consoleLeak &&
        (trendExpected
          ? result.legendVisible &&
            result.tickCount >= (scenario === "empty" ? 3 : 8) &&
            result.accessiblePoints &&
            result.detailInitiallyHidden &&
            result.hoverDetailVisible &&
            result.focusDetailVisible &&
            result.detailHidesAfterLeave &&
            result.detailContained
          : result.noUnexpectedTrend) &&
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
