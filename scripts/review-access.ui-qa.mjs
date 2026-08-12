import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5195);
const base = `http://127.0.0.1:${port}`;
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "review-access");
fs.mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1280", width: 1280, height: 900 },
];

const scenarios = [
  { name: "review-normal", path: "/review" },
  { name: "review-filter", path: "/review" },
  { name: "review-actions", path: "/review" },
  { name: "review-loading", path: "/review" },
  { name: "review-empty", path: "/review" },
  { name: "review-forbidden", path: "/review" },
  { name: "review-list-failure", path: "/review" },
  { name: "review-action-failure", path: "/review" },
  { name: "access-inbox", path: "/original-access?box=inbox" },
  { name: "access-mine", path: "/original-access" },
  { name: "access-actions", path: "/original-access?box=inbox" },
  { name: "access-loading", path: "/original-access?box=inbox" },
  { name: "access-empty", path: "/original-access?box=inbox" },
  { name: "access-forbidden", path: "/original-access?box=inbox" },
  { name: "access-list-failure", path: "/original-access?box=inbox" },
  { name: "access-action-failure", path: "/original-access?box=inbox" },
];

const secrets = [
  "secret-review-80",
  "secret-review-81",
  "secret-review-82",
  "secret-request-80",
  "secret-request-81",
  "secret-asset-80",
  "secret-project-80",
  "secret-user-80",
  "secret-reviewer-80",
  "secret-original-layer",
  "secret-trigger",
  "secret_review_type",
  "secret_review_status",
  "secret_scope",
  "secret_access_status",
  "storage_ref=s3://secret",
  "signed_url=https://secret",
  "upstream secret body",
  "deniedReason",
];

const reviewItem = (overrides = {}) => ({
  id: "secret-review-80",
  review_type: "project_ingest_approval",
  trigger_source: "secret-trigger",
  status: "pending_reviewer",
  target_asset_id: "secret-asset-80",
  asset_title: "客户交付复盘",
  target_scope: "project",
  target_project_id: "secret-project-80",
  project_name: "华东增长项目",
  submitted_by: "secret-user-80",
  reviewer_user_id: "secret-reviewer-80",
  evidence_count: 0,
  review_comment: null,
  reviewed_at: null,
  created_at: "2026-07-16T02:00:00Z",
  can_decide: true,
  can_withdraw: false,
  general_manager_confirmation_status: null,
  consulting_director_confirmation_status: null,
  ...overrides,
});

const accessItem = (overrides = {}) => ({
  request_id: "secret-request-80",
  asset_id: "secret-asset-80",
  asset_title: "客户访谈原文",
  scope: "project",
  project_id: "secret-project-80",
  requester_user_id: "secret-user-80",
  requester_name: "王顾问",
  reviewer_user_id: "secret-reviewer-80",
  reviewer_name: null,
  requested_access_layer: "secret-original-layer",
  status: "pending",
  reason: "核对客户原始反馈",
  review_note: null,
  created_at: "2026-07-16T02:00:00Z",
  reviewed_at: null,
  ...overrides,
});

const authMe = {
  user_id: "auth-user-secret",
  name: "治理验收用户",
  email: "governance-secret@example.test",
  status: "active",
  company_roles: ["consultant"],
  active_company_role: "consultant",
  is_business_user: true,
  can_discover_l5: false,
  project_memberships: [],
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

function accepted(result) {
  const basePass =
    result.overflowX <= 2 &&
    result.shellOverlap <= 1 &&
    result.clippedControls === 0 &&
    result.workspaceCount === 1 &&
    result.routeTabCount === 3 &&
    result.tableVisible &&
    result.maxRowHeight <= 72 &&
    !result.oldSurfaceVisible &&
    !result.sensitiveVisible &&
    !result.internalVisible &&
    !result.consoleLeak &&
    result.pathCorrect;
  if (!basePass) return false;

  const expectations = {
    "review-normal": result.reviewSafe && result.reviewReadonly && result.routeRoundTrip,
    "review-filter": result.reviewFilterCorrect,
    "review-actions":
      result.reviewApproveCalls === 1 &&
      result.reviewRejectCalls === 1 &&
      result.reviewWithdrawCalls === 1 &&
      result.reviewGetCalls >= 4,
    "review-loading": result.loadingSeen,
    "review-empty": result.emptySeen,
    "review-forbidden": result.forbiddenSeen,
    "review-list-failure": result.failureSeen && result.retrySucceeded,
    "review-action-failure": result.actionFailureSeen,
    "access-inbox": result.accessSafe && result.accessTerminalReadonly && result.routeRoundTrip,
    "access-mine": result.mineQueryCorrect && result.mineRecordSeen && result.noAccessActions,
    "access-actions":
      result.accessApproveCalls === 1 &&
      result.accessRejectCalls === 1 &&
      result.accessGetCalls >= 3,
    "access-loading": result.loadingSeen,
    "access-empty": result.emptySeen,
    "access-forbidden": result.forbiddenSeen,
    "access-list-failure": result.failureSeen && result.retrySucceeded,
    "access-action-failure": result.actionFailureSeen,
  };
  return Boolean(expectations[result.scenario]);
}

let previewServer;
let browser;
const results = [];

try {
  await build({ logLevel: "warn" });
  previewServer = await preview({
    preview: { host: "127.0.0.1", port, strictPort: true },
    logLevel: "warn",
  });
  browser = await chromium.launch({ args: ["--disable-gpu"] });

  for (const scenario of scenarios) {
    for (const viewport of viewports) {
      let reviewGetCalls = 0;
      let accessGetCalls = 0;
      let reviewApproveCalls = 0;
      let reviewRejectCalls = 0;
      let reviewWithdrawCalls = 0;
      let accessApproveCalls = 0;
      let accessRejectCalls = 0;
      let capturedReviewQuery = null;
      let capturedAccessBox = null;
      let retrySucceeded = false;
      let releaseLoading = () => {};
      const loadingGate = new Promise((resolve) => {
        releaseLoading = resolve;
      });
      const context = await browser.newContext({ viewport });

      await context.route("**/api/v1/**", async (route) => {
        const requestUrl = new URL(route.request().url());
        const method = route.request().method();
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

        if (requestUrl.pathname === "/api/v1/auth/me") return fulfill(authMe);
        if (requestUrl.pathname === "/api/v1/auth/csrf")
          return fulfill({ csrf_token: "csrf-safe" });
        if (requestUrl.pathname === "/api/v1/workbench/overview") return fulfill(workbenchOverview);
        if (requestUrl.pathname === "/api/v1/notifications")
          return fulfill({
            items: [],
            total: 0,
            page: 1,
            page_size: 20,
            unread_count: 0,
            categories: [],
          });

        if (requestUrl.pathname === "/api/v1/reviews" && method === "GET") {
          reviewGetCalls += 1;
          capturedReviewQuery = Object.fromEntries(requestUrl.searchParams);
          if (scenario.name === "review-loading" && reviewGetCalls === 1) await loadingGate;
          if (scenario.name === "review-forbidden") {
            return fulfill(
              { detail: { message: "manager secret", denied_reason: "role_secret" } },
              403,
            );
          }
          if (scenario.name === "review-list-failure" && reviewGetCalls === 1) {
            return fulfill(
              { detail: { message: "storage_ref=s3://secret", denied_reason: "upstream_secret" } },
              503,
            );
          }
          if (scenario.name === "review-list-failure" && reviewGetCalls > 1) retrySucceeded = true;
          if (scenario.name === "review-empty") return fulfill({ items: [], total: 0 });

          const items = [
            reviewItem(),
            reviewItem({
              id: "secret-review-81",
              asset_title: "待补充方案",
              can_decide: scenario.name === "review-actions",
            }),
            reviewItem({
              id: "secret-review-82",
              asset_title: "本人已确认事项",
              status: "approved",
              can_decide: false,
              can_withdraw: true,
            }),
            reviewItem({
              id: "secret-review-unknown",
              asset_title: null,
              project_name: null,
              review_type: "secret_review_type",
              status: "secret_review_status",
              can_decide: false,
            }),
          ];
          return fulfill({ items, total: items.length });
        }

        if (requestUrl.pathname.endsWith("/approve") && requestUrl.pathname.includes("/reviews/")) {
          reviewApproveCalls += 1;
          if (scenario.name === "review-action-failure") {
            return fulfill({ detail: { message: "upstream secret body" } }, 500);
          }
          return fulfill({});
        }
        if (requestUrl.pathname.endsWith("/reject") && requestUrl.pathname.includes("/reviews/")) {
          reviewRejectCalls += 1;
          return fulfill({});
        }
        if (requestUrl.pathname.endsWith("/withdraw")) {
          reviewWithdrawCalls += 1;
          return fulfill({});
        }

        if (requestUrl.pathname === "/api/v1/original-access/requests" && method === "GET") {
          accessGetCalls += 1;
          capturedAccessBox = requestUrl.searchParams.get("box");
          if (scenario.name === "access-loading" && accessGetCalls === 1) await loadingGate;
          if (scenario.name === "access-forbidden") {
            return fulfill(
              { detail: { message: "boss secret", denied_reason: "role_secret" } },
              403,
            );
          }
          if (scenario.name === "access-list-failure" && accessGetCalls === 1) {
            return fulfill(
              {
                detail: { message: "signed_url=https://secret", denied_reason: "upstream_secret" },
              },
              503,
            );
          }
          if (scenario.name === "access-list-failure" && accessGetCalls > 1) retrySucceeded = true;
          if (scenario.name === "access-empty") return fulfill({ items: [], total: 0 });
          if (capturedAccessBox === "mine") {
            return fulfill({
              items: [
                accessItem({
                  request_id: "secret-request-mine",
                  asset_title: "本人申请记录",
                  status: "approved",
                  reviewer_name: "李经理",
                  reviewed_at: "2026-07-17T03:00:00Z",
                }),
              ],
              total: 1,
            });
          }
          const items = [
            accessItem(),
            accessItem({
              request_id: "secret-request-81",
              asset_title: "已完成访问申请",
              status: "approved",
            }),
            accessItem({
              request_id: "secret-request-unknown",
              asset_id: "secret-asset-unknown",
              asset_title: null,
              scope: "secret_scope",
              status: "secret_access_status",
              requester_name: null,
              reason: null,
            }),
          ];
          return fulfill({ items, total: items.length });
        }

        if (
          requestUrl.pathname.endsWith("/approve") &&
          requestUrl.pathname.includes("/original-access/requests/")
        ) {
          accessApproveCalls += 1;
          if (scenario.name === "access-action-failure") {
            return fulfill({ detail: { message: "upstream secret body" } }, 500);
          }
          return fulfill({ status: "approved" });
        }
        if (
          requestUrl.pathname.endsWith("/reject") &&
          requestUrl.pathname.includes("/original-access/requests/")
        ) {
          accessRejectCalls += 1;
          return fulfill({ status: "rejected" });
        }

        return fulfill({ detail: { message: "unconfigured UI QA route" } }, 404);
      });

      const page = await context.newPage();
      const browserMessages = [];
      page.on("console", (message) => browserMessages.push(message.text()));
      page.on("pageerror", (error) => browserMessages.push(error.message));
      const emptyResponse = ["review-empty", "access-empty"].includes(scenario.name)
        ? page.waitForResponse((response) => {
            const pathname = new URL(response.url()).pathname;
            return scenario.name === "review-empty"
              ? pathname === "/api/v1/reviews"
              : pathname === "/api/v1/original-access/requests";
          })
        : null;
      await page.goto(`${base}${scenario.path}`, { waitUntil: "domcontentloaded" });

      let routeRoundTrip = false;
      let reviewFilterCorrect = false;
      let loadingSeen = false;
      let emptySeen = false;
      let forbiddenSeen = false;
      let failureSeen = false;
      let actionFailureSeen = false;
      let mineQueryCorrect = false;
      let mineRecordSeen = false;

      if (scenario.name === "review-loading") {
        await page.getByText("正在加载审核队列…").waitFor();
        loadingSeen = true;
        releaseLoading();
        await page.getByText("客户交付复盘").waitFor();
      } else if (scenario.name === "access-loading") {
        await page.getByText("正在加载原文访问申请…").waitFor();
        loadingSeen = true;
        releaseLoading();
        await page.getByText("客户访谈原文").waitFor();
      } else if (scenario.name === "review-empty") {
        await emptyResponse;
        await page.waitForFunction(
          () => document.querySelector("table")?.getAttribute("aria-busy") === "false",
        );
        await page.getByText("暂无审核事项").waitFor();
        emptySeen = true;
      } else if (scenario.name === "access-empty") {
        await emptyResponse;
        await page.waitForFunction(
          () => document.querySelector("table")?.getAttribute("aria-busy") === "false",
        );
        await page.getByText("暂无待审批申请").waitFor();
        emptySeen = true;
      } else if (scenario.name === "review-forbidden") {
        await page.getByText("无审核权限").waitFor();
        forbiddenSeen = true;
      } else if (scenario.name === "access-forbidden") {
        await page.getByText("无原文访问权限").waitFor();
        forbiddenSeen = true;
      } else if (scenario.name === "review-list-failure") {
        await page.getByText("审核队列加载失败").waitFor();
        failureSeen = true;
        await page.getByRole("button", { name: "重试" }).click();
        await page.getByText("客户交付复盘").waitFor();
      } else if (scenario.name === "access-list-failure") {
        await page.getByText("原文访问申请加载失败").waitFor();
        failureSeen = true;
        await page.getByRole("button", { name: "重试" }).click();
        await page.getByText("客户访谈原文").waitFor();
      } else if (scenario.path.startsWith("/review")) {
        await page.getByText("客户交付复盘").waitFor();
        if (scenario.name === "review-normal") {
          await page
            .getByRole("navigation", { name: "治理工作区" })
            .getByRole("link", { name: "原文访问" })
            .click();
          await page.waitForURL(`${base}/original-access`);
          await page.getByText("本人申请记录").waitFor();
          await page
            .getByRole("navigation", { name: "治理工作区" })
            .getByRole("link", { name: "审核待办" })
            .click();
          await page.waitForURL(`${base}/review`);
          await page.getByText("客户交付复盘").waitFor();
          routeRoundTrip = true;
        }
        if (scenario.name === "review-filter") {
          await page.getByLabel("审核状态").selectOption("2");
          await page.getByLabel("审核类型").selectOption("1");
          await page.waitForFunction(() => document.body.innerText.includes("客户交付复盘"));
          reviewFilterCorrect =
            capturedReviewQuery?.status === "pending_reviewer" &&
            capturedReviewQuery?.review_type === "project_ingest_approval";
        }
        if (scenario.name === "review-actions") {
          await page
            .getByText("客户交付复盘")
            .locator("xpath=ancestor::tr")
            .getByRole("button", { name: "确认" })
            .click();
          await page.getByText("审核已通过。").waitFor();
          await page
            .getByText("待补充方案")
            .locator("xpath=ancestor::tr")
            .getByRole("button", { name: "拒绝" })
            .click();
          await page.getByLabel("拒绝原因").fill("缺少客户确认记录");
          await page.getByRole("button", { name: "确认拒绝" }).click();
          await page.getByText("审核已拒绝。").waitFor();
          await page
            .getByText("本人已确认事项")
            .locator("xpath=ancestor::tr")
            .getByRole("button", { name: "撤回" })
            .click();
          await page.getByText("确认已撤回。").waitFor();
        }
        if (scenario.name === "review-action-failure") {
          await page
            .getByText("客户交付复盘")
            .locator("xpath=ancestor::tr")
            .getByRole("button", { name: "确认" })
            .click();
          await page.getByText("操作未完成，请稍后重试。").waitFor();
          actionFailureSeen = true;
        }
      } else {
        if (scenario.name === "access-mine") {
          await page.getByText("本人申请记录").waitFor();
        } else {
          await page.getByText("客户访谈原文").waitFor();
        }
        if (scenario.name === "access-inbox") {
          await page
            .getByRole("navigation", { name: "治理工作区" })
            .getByRole("link", { name: "审核待办" })
            .click();
          await page.waitForURL(`${base}/review`);
          await page.getByText("客户交付复盘").waitFor();
          await page
            .getByRole("navigation", { name: "治理工作区" })
            .getByRole("link", { name: "原文访问" })
            .click();
          await page.waitForURL(`${base}/original-access`);
          await page.getByText("本人申请记录").waitFor();
          await page.getByRole("button", { name: "待我审批" }).click();
          await page.getByText("客户访谈原文").waitFor();
          routeRoundTrip = true;
        }
        if (scenario.name === "access-mine") {
          await page.getByRole("button", { name: "我的申请" }).click();
          await page.getByText("本人申请记录").waitFor();
          mineQueryCorrect = capturedAccessBox === "mine";
          mineRecordSeen = await page.getByText(/李经理 · 2026-07-17/).isVisible();
        }
        if (scenario.name === "access-actions") {
          await page
            .getByText("客户访谈原文")
            .locator("xpath=ancestor::tr")
            .getByRole("button", { name: "通过" })
            .click();
          await page.getByText("原文访问申请已通过。").waitFor();
          await page
            .getByText("客户访谈原文")
            .locator("xpath=ancestor::tr")
            .getByRole("button", { name: "拒绝" })
            .click();
          await page.getByText("原文访问申请已拒绝。").waitFor();
        }
        if (scenario.name === "access-action-failure") {
          await page
            .getByText("客户访谈原文")
            .locator("xpath=ancestor::tr")
            .getByRole("button", { name: "通过" })
            .click();
          await page.getByText("操作未完成，请稍后重试。").waitFor();
          actionFailureSeen = true;
        }
      }

      const result = await page.evaluate(
        ({ expectedPath, scenarioName, forbiddenStrings }) => {
          const root = document.documentElement;
          const rail = document.querySelector(".rail")?.getBoundingClientRect();
          const deck = document.querySelector(".deck")?.getBoundingClientRect();
          const rows = [...document.querySelectorAll(".gw-table tbody tr")].filter((row) =>
            row.querySelector("td:not(.product-table-state)"),
          );
          const bodyText = document.body.innerText;
          const html = document.documentElement.innerHTML;
          const clippedControls = [...document.querySelectorAll("button, select")].filter(
            (element) => element.scrollWidth > element.clientWidth + 2,
          ).length;
          const terminalRow = [...rows].find((row) => row.textContent?.includes("已完成访问申请"));
          const readonlyReview = [...rows].find((row) => row.textContent?.includes("待补充方案"));
          return {
            scenario: scenarioName,
            overflowX: root.scrollWidth - root.clientWidth,
            shellOverlap: rail && deck ? Math.max(0, rail.right - deck.left) : 1,
            clippedControls,
            workspaceCount: document.querySelectorAll(".gw-page").length,
            routeTabCount: document.querySelectorAll(".gw-route-tabs a").length,
            tableVisible: Boolean(document.querySelector(".gw-table")),
            maxRowHeight: Math.max(0, ...rows.map((row) => row.getBoundingClientRect().height)),
            oldSurfaceVisible: Boolean(
              document.querySelector(".kl-kpis, .role-context-hint, .page-help-line, .asset-card"),
            ),
            sensitiveVisible: forbiddenStrings.some(
              (secret) => bodyText.includes(secret) || html.includes(secret),
            ),
            internalVisible: [
              "pending_reviewer",
              "project_ingest_approval",
              "requested_access_layer",
              "target_asset_id",
              "reviewer_user_id",
              "HTTP 403",
              "HTTP 500",
            ].some((value) => bodyText.includes(value) || html.includes(value)),
            pathCorrect: window.location.pathname === expectedPath,
            reviewSafe:
              bodyText.includes("客户交付复盘") &&
              bodyText.includes("待确认知识") &&
              bodyText.includes("信息待确认"),
            reviewReadonly: Boolean(readonlyReview && !readonlyReview.querySelector("button")),
            accessSafe:
              bodyText.includes("客户访谈原文") &&
              bodyText.includes("待确认资产") &&
              bodyText.includes("信息待确认"),
            accessTerminalReadonly: Boolean(terminalRow && !terminalRow.querySelector("button")),
            noAccessActions:
              !document.querySelector(".gw-access-table .gw-action.is-primary") &&
              !document.querySelector(".gw-access-table .gw-action.is-danger"),
          };
        },
        {
          expectedPath: scenario.path.split("?")[0],
          scenarioName: scenario.name,
          forbiddenStrings: secrets,
        },
      );

      Object.assign(result, {
        routeRoundTrip,
        reviewFilterCorrect,
        loadingSeen,
        emptySeen,
        forbiddenSeen,
        failureSeen,
        retrySucceeded,
        actionFailureSeen,
        mineQueryCorrect,
        mineRecordSeen,
        reviewGetCalls,
        accessGetCalls,
        reviewApproveCalls,
        reviewRejectCalls,
        reviewWithdrawCalls,
        accessApproveCalls,
        accessRejectCalls,
        consoleLeak: secrets.some((secret) => browserMessages.join("\n").includes(secret)),
      });

      await page.screenshot({
        path: path.join(outDir, `${scenario.name}-${viewport.name}.png`),
        fullPage: false,
        animations: "disabled",
      });
      results.push({ viewport: viewport.name, ...result, passed: accepted(result) });
      await context.close();
    }
  }
} finally {
  await browser?.close();
  await previewServer?.close();
}

fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify({ port, outDir, results }, null, 2));
const failed = results.filter((result) => !result.passed);
if (failed.length > 0) {
  throw new Error(`PBC-80 review/access UI QA failed in ${failed.length} scenario(s)`);
}
