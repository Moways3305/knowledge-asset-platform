import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5198);
const externalBase = process.env.UI_QA_BASE?.replace(/\/$/, "") || null;
const base = externalBase || `http://127.0.0.1:${port}`;
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "personal-knowledge");
fs.mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "1440", width: 1440, height: 1100 },
  { name: "1024", width: 1024, height: 900 },
  { name: "390", width: 390, height: 844 },
];
const scenarios = [
  "default",
  "filter-search",
  "pending-active",
  "no-results",
  "empty",
  "forbidden",
  "list-error",
  "dialogs",
  "publication",
  "page-2",
];

const authMe = {
  user_id: "00000000-0000-0000-0000-000000000083",
  name: "个人知识验收用户",
  email: "personal-qa@example.test",
  status: "active",
  company_roles: ["consultant"],
  active_company_role: "consultant",
  is_business_user: true,
  can_discover_l5: false,
  project_memberships: [
    {
      project_id: "00000000-0000-0000-0000-0000000000a3",
      project_name: "企业知识治理项目",
      project_role: "consultant",
      status: "active",
    },
  ],
};

const accessInfo = {
  discovery: true,
  summary: true,
  original: true,
  effective_source: "owner",
  can_request_original: false,
  existing_request_status: null,
  existing_grant_expires_at: null,
  can_delete: true,
  can_manage_lifecycle: true,
};

function item({ id, title, type, state, label, updatedAt, project = null, evidence = null }) {
  return {
    id,
    title,
    scope: "personal",
    zone: state === "awaiting_confirmation" ? "material" : "asset",
    asset_type: type,
    confidentiality_level: "L2",
    ai_access_level: "A2",
    asset_status: "active",
    visibility: "confidential",
    tags: ["方法沉淀"],
    summary_text: null,
    project_name: null,
    lifecycle_phase: null,
    confidence: null,
    last_called_at: null,
    updated_at: updatedAt,
    created_at: "2026-07-02T03:00:00Z",
    access_info: accessInfo,
    personal_state: state,
    personal_state_label: label,
    project_submission: project,
    evidence_summary: evidence,
  };
}

const allItems = [
  item({
    id: "00000000-0000-0000-0000-000000000831",
    title: "客户访谈洞察整理",
    type: "insight",
    state: "awaiting_confirmation",
    label: "待本人确认",
    updatedAt: "2026-07-17T02:30:00Z",
  }),
  item({
    id: "00000000-0000-0000-0000-000000000832",
    title: "项目复盘方法模板",
    type: "template",
    state: "ready_to_submit",
    label: "可提交项目",
    updatedAt: "2026-07-16T07:20:00Z",
    evidence: {
      registered_count: 2,
      latest_status: "candidate",
      updated_at: "2026-07-16T07:20:00Z",
    },
  }),
  item({
    id: "00000000-0000-0000-0000-000000000833",
    title: "组织诊断交付清单",
    type: "deliverable",
    state: "pending_project_review",
    label: "待项目经理审批",
    updatedAt: "2026-07-15T06:10:00Z",
    project: {
      status: "pending",
      target_project_name: "企业知识治理项目",
      submitted_at: "2026-07-15T06:00:00Z",
      resolved_at: null,
    },
  }),
  item({
    id: "00000000-0000-0000-0000-000000000834",
    title: "治理项目案例总结",
    type: "case",
    state: "active_in_project",
    label: "已进入项目",
    updatedAt: "2026-07-14T05:00:00Z",
    project: {
      status: "approved",
      target_project_name: "企业知识治理项目",
      submitted_at: "2026-07-12T04:00:00Z",
      resolved_at: "2026-07-14T05:00:00Z",
    },
  }),
];

const pageTwoItem = item({
  id: "00000000-0000-0000-0000-000000000835",
  title: "第二页的调研方法",
  type: "methodology",
  state: "project_rejected",
  label: "项目未通过",
  updatedAt: "2026-07-01T02:00:00Z",
});

const summary = {
  total_assets: 21,
  awaiting_confirmation: 3,
  pending_project_review: 4,
  active_in_project: 8,
  created_this_month: 5,
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
      const browserMessages = [];
      const listQueries = [];
      let unexpectedCalls = 0;
      let publicationPayload = null;
      let publicationScreenshot = null;
      await context.route("**/api/v1/**", async (route) => {
        const url = new URL(route.request().url());
        const method = route.request().method();
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

        if (url.pathname === "/api/v1/auth/me") return fulfill(authMe);
        if (url.pathname === "/api/v1/workbench/overview") return fulfill(workbenchOverview);
        if (url.pathname === "/api/v1/notifications/unread-count")
          return fulfill({ unread_count: 0 });
        if (url.pathname === "/api/v1/notifications")
          return fulfill({ items: [], total: 0, page: 1, page_size: 20 });
        if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "csrf-safe-83" });
        if (url.pathname === "/api/v1/naming-options") {
          return fulfill({
            required: true,
            rule_version: 7,
            categories: [
              {
                id: "category-project-safe",
                scope: "project",
                primary: "项目资料",
                secondary: "交付成果",
                prefix: "交付",
                asset_type: "deliverable",
                default_confidentiality: "L2",
                enabled: true,
                sort_order: 10,
                suggested_directory_key: "project.deliverables",
              },
            ],
            directories: [
              {
                directory_key: "project.deliverables",
                scope: "project",
                display_name: "03 交付成果",
                sort_order: 30,
                enabled: true,
              },
            ],
            default_confidentiality: "L2",
            message: null,
          });
        }
        if (url.pathname === "/api/v1/weknora/model-options")
          return fulfill({ items: [], default_missing: false });
        if (url.pathname === "/api/v1/my/knowledge-base" && method === "GET") {
          if (scenario === "forbidden") return fulfill({ detail: "private_denial" }, 403);
          return fulfill({
            exists: true,
            display_name: "我的方法知识库",
            status: "active",
            knowledge_count: 21,
          });
        }
        if (url.pathname === "/api/v1/my/knowledge" && method === "GET") {
          listQueries.push(Object.fromEntries(url.searchParams));
          if (scenario === "forbidden") return fulfill({ detail: "private_denial" }, 403);
          if (scenario === "list-error") return fulfill({ detail: "SECRET-LIKE upstream" }, 500);
          const page = Number(url.searchParams.get("page") || "1");
          const noResults = scenario === "no-results" && url.searchParams.has("keyword");
          const empty = scenario === "empty" || noResults;
          const filtered = scenario === "filter-search" && url.searchParams.has("asset_type");
          const pageItems =
            page === 2 ? [pageTwoItem] : filtered ? [allItems[1]] : empty ? [] : allItems;
          return fulfill({
            items: pageItems,
            total: empty ? 0 : page === 2 ? 21 : filtered ? 1 : 21,
            page,
            page_size: 20,
            has_next: !empty && !filtered && page === 1,
            summary: empty ? { ...summary, total_assets: 0 } : summary,
          });
        }
        if (url.pathname.includes("/api/v1/my/knowledge/") && method === "PATCH") {
          return fulfill({ ...allItems[1], title: "更新后的项目复盘模板" });
        }
        if (
          url.pathname.includes("/api/v1/knowledge/") &&
          url.pathname.endsWith("/delete") &&
          method === "POST"
        ) {
          return fulfill({ status: "deleted" });
        }
        if (url.pathname.endsWith("/submit-to-project-preview") && method === "POST") {
          return fulfill({
            required: true,
            canonical_name: "【KAP-2026-交付成果】项目复盘方法模板_20260817_V1_L2.docx",
            rule_version: 7,
            fields: { directory_key: "project.deliverables" },
            notices: [],
            message: null,
          });
        }
        if (url.pathname.endsWith("/submit-to-project") && method === "POST") {
          publicationPayload = route.request().postDataJSON();
          return fulfill({
            submission_id: "safe-submission",
            asset_id: allItems[1].id,
            target_project_id: authMe.project_memberships[0].project_id,
            target_project_name: "企业知识治理项目",
            submission_type: "submit_to_project",
            status: "pending",
            review_task_id: "safe-review",
            evidence_id: null,
            created_at: "2026-08-17T00:00:00Z",
            message: "已提交，等待项目经理确认",
            next_action: "等待项目经理确认",
          });
        }
        unexpectedCalls += 1;
        return fulfill({ detail: "unexpected endpoint" }, 500);
      });

      const page = await context.newPage();
      page.on("console", (message) => browserMessages.push(message.text()));
      page.on("pageerror", (error) => browserMessages.push(error.message));
      await page.goto(`${base}/my/knowledge`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "我的个人知识" }).waitFor();

      if (scenario === "filter-search") {
        await page.getByRole("button", { name: "筛选" }).click();
        const panel = page.getByRole("dialog", { name: "筛选个人资料" });
        await panel.getByLabel("资料类型").selectOption("template");
        await page.getByRole("textbox", { name: "搜索个人资料" }).fill("复盘");
        const filteredResponse = page.waitForResponse((response) => {
          const url = new URL(response.url());
          return (
            url.pathname === "/api/v1/my/knowledge" &&
            url.searchParams.get("asset_type") === "template" &&
            url.searchParams.get("keyword") === "复盘"
          );
        });
        await page.getByRole("button", { name: "搜索", exact: true }).click();
        await filteredResponse;
        await page.getByRole("button", { name: "清除搜索" }).waitFor();
        await page.getByText("项目复盘方法模板").waitFor();
      } else if (scenario === "no-results") {
        await page.getByRole("textbox", { name: "搜索个人资料" }).fill("不存在的资料");
        await page.getByRole("button", { name: "搜索", exact: true }).click();
        await page.getByText("没有符合条件的资料").waitFor();
      } else if (scenario === "dialogs") {
        const row = page
          .getByRole("link", { name: "项目复盘方法模板" })
          .locator("xpath=ancestor::tr");
        await row.getByRole("button", { name: "更多操作：项目复盘方法模板" }).click();
        await page.getByRole("menuitem", { name: "编辑资料" }).click();
        await page.getByRole("dialog").waitFor();
        await page.screenshot({
          path: path.join(outDir, `edit-dialog-${viewport.name}.png`),
          animations: "disabled",
        });
        await page.getByRole("dialog").getByRole("button", { name: "取消" }).click();
        await row.getByRole("button", { name: "更多操作：项目复盘方法模板" }).click();
        await page.getByRole("menuitem", { name: "删除资料" }).click();
        await page.getByRole("dialog").waitFor();
        await page.screenshot({
          path: path.join(outDir, `delete-dialog-${viewport.name}.png`),
          animations: "disabled",
        });
      } else if (scenario === "publication") {
        const row = page
          .getByRole("link", { name: "项目复盘方法模板" })
          .locator("xpath=ancestor::tr");
        await row.getByRole("button", { name: "提交项目" }).click();
        const dialog = page.getByRole("dialog", { name: "提交到项目" });
        await dialog.getByLabel("目标项目").selectOption(authMe.project_memberships[0].project_id);
        await dialog.getByText("03 交付成果").waitFor();
        if ((await dialog.getByRole("combobox", { name: "正式目录" }).count()) !== 0) {
          throw new Error("mapped publication directory must be read-only");
        }
        await dialog.getByRole("button", { name: "预览目标文件名" }).click();
        await dialog.getByText(/【KAP-2026-交付成果】/).waitFor();
        publicationScreenshot = path.join(outDir, `publication-preview-${viewport.name}.png`);
        await dialog.screenshot({ path: publicationScreenshot, animations: "disabled" });
        await dialog.getByRole("button", { name: "提交" }).click();
        await page.getByText("已提交，等待项目经理确认").waitFor();
      } else if (scenario === "page-2") {
        await page.getByRole("button", { name: "下一页" }).click();
        await page.getByText("第二页的调研方法").waitFor();
      }

      const result = await page.evaluate((scenarioName) => {
        const text = document.body.innerText;
        const root = document.documentElement;
        const table = document.querySelector(".mk83-table")?.getBoundingClientRect();
        const stats = [...document.querySelectorAll(".mk83-stats article")].map((node) =>
          node.getBoundingClientRect(),
        );
        const internalTerms = [
          "awaiting_confirmation",
          "ready_to_submit",
          "pending_project_review",
          "active_in_project",
          "project_rejected",
          "storage_ref",
          "weknora",
          "SECRET-LIKE",
          "private_denial",
        ];
        return {
          scenario: scenarioName,
          overflowX: root.scrollWidth - root.clientWidth,
          clippedControls: [...document.querySelectorAll("a, button")].filter(
            (node) => node.scrollWidth > node.clientWidth + 2,
          ).length,
          statsReady:
            scenarioName === "forbidden" ||
            (stats.length === 4 && stats.every((box) => box.height >= 120)),
          tableReady: !table || table.width >= 820,
          internalVisible: internalTerms.some((term) =>
            text.toLowerCase().includes(term.toLowerCase()),
          ),
          defaultReady:
            text.includes("客户访谈洞察整理") &&
            text.includes("待本人确认") &&
            text.includes("上传资料"),
          filterSearchReady: text.includes("项目复盘方法模板") && text.includes("清除搜索"),
          pendingActiveReady: text.includes("待项目经理审批") && text.includes("已进入项目"),
          noResultsReady: text.includes("没有符合条件的资料"),
          emptyReady: text.includes("还没有个人资料"),
          forbiddenReady:
            text.includes("当前身份无法使用个人知识") && !text.includes("客户访谈洞察整理"),
          listErrorReady: text.includes("个人资料暂时无法加载") && !text.includes("SECRET-LIKE"),
          dialogsReady:
            text.includes("删除个人资料") &&
            text.includes("项目复盘方法模板") &&
            text.includes("删除原因"),
          publicationReady: text.includes("已提交，等待项目经理确认"),
          page2Ready: text.includes("第二页的调研方法") && text.includes("第 2 页"),
        };
      }, scenario);

      const stateKey = `${scenario.replace(/-([a-z0-9])/g, (_, char) => char.toUpperCase())}Ready`;
      const queryReady =
        scenario === "filter-search"
          ? listQueries.some((query) => query.asset_type === "template" && query.keyword === "复盘")
          : scenario === "page-2"
            ? listQueries.some((query) => query.page === "2")
            : true;
      Object.assign(result, {
        queryReady,
        unexpectedCalls,
        consoleLeak: browserMessages.some((message) => /SECRET-LIKE|private_denial/.test(message)),
        publicationPayloadValid:
          scenario !== "publication" ||
          (publicationPayload?.target_project_id === authMe.project_memberships[0].project_id &&
            publicationPayload?.naming?.directory_key === "project.deliverables" &&
            publicationPayload?.naming?.category_id === "category-project-safe" &&
            publicationPayload?.naming?.subject === "项目复盘方法模板"),
        publicationScreenshot,
      });
      result.passed =
        result.overflowX <= 1 &&
        result.clippedControls === 0 &&
        result.statsReady &&
        result.tableReady &&
        !result.internalVisible &&
        !result.consoleLeak &&
        result.unexpectedCalls === 0 &&
        result.queryReady &&
        result.publicationPayloadValid &&
        Boolean(result[stateKey]);
      await page.screenshot({
        path: path.join(outDir, `${scenario}-${viewport.name}.png`),
        fullPage: false,
        animations: "disabled",
      });
      results.push({ viewport: viewport.name, ...result });
      await context.close();
    }
  }
} finally {
  await browser?.close();
  await server?.close();
}

fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify({ port, outDir, results }, null, 2));
const failed = results.filter((result) => !result.passed);
if (failed.length)
  throw new Error(`PBC-83 personal knowledge UI QA failed in ${failed.length} scenario(s)`);
