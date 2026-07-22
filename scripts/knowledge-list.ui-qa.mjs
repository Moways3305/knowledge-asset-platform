import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.UI_QA_BASE || "http://localhost:5179";
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "knowledge-list");
fs.mkdirSync(outDir, { recursive: true });

const projectId = "00000000-0000-0000-0000-000000000075";
const assetId = "00000000-0000-0000-0000-0000000000a1";
const scenarios = ["company", "project", "empty", "retry", "pure-admin"];
const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1280", width: 1280, height: 900 },
];

const asset = (overrides = {}) => ({
  id: assetId,
  title: "客户经营诊断方法论与跨部门交付复盘框架",
  scope: "company",
  zone: "asset",
  asset_type: "methodology",
  confidentiality_level: "L4",
  ai_access_level: "A3",
  asset_status: "active",
  visibility: "confidential",
  tags: ["经营诊断"],
  summary_text: "当前身份可查看的安全摘要，不包含客户敏感原文或内部存储信息。",
  project_name: null,
  lifecycle_phase: null,
  confidence: null,
  last_called_at: null,
  updated_at: "2026-07-15T08:00:00Z",
  access_info: {
    discovery: true,
    summary: true,
    original: false,
    effective_source: "company_role",
    can_request_original: true,
    existing_request_status: null,
    existing_grant_expires_at: null,
    can_delete: false,
    can_retry_index: false,
  },
  index_status: "indexed",
  weknora_parse_status: null,
  index_error_message: null,
  indexed_at: null,
  ...overrides,
});

const browser = await chromium.launch({ args: ["--disable-gpu"] });
const results = [];

for (const scenario of scenarios) {
  for (const viewport of viewports) {
    let knowledgeCalls = 0;
    let retried = false;
    let allowRetrySuccess = false;
    let projectQuery = null;
    const context = await browser.newContext({ viewport });
    await context.route("**/api/v1/**", async (route) => {
      const requestUrl = new URL(route.request().url());
      const fulfill = (body, status = 200) =>
        route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

      if (requestUrl.pathname === "/api/v1/auth/me") {
        const pureAdmin = scenario === "pure-admin";
        return fulfill({
          user_id: "00000000-0000-0000-0000-000000000099",
          name: pureAdmin ? "系统管理员验收用户" : "知识顾问验收用户",
          email: "identity-not-rendered@example.test",
          status: "active",
          company_roles: pureAdmin ? ["admin"] : ["consultant"],
          is_business_user: !pureAdmin,
          can_discover_l5: false,
          project_memberships: pureAdmin
            ? []
            : [
                {
                  project_id: projectId,
                  project_name: "华东交付项目",
                  project_role: "consultant",
                  status: "active",
                },
              ],
        });
      }

      if (requestUrl.pathname === "/api/v1/knowledge") {
        knowledgeCalls += 1;
        if (requestUrl.searchParams.get("project_id")) {
          projectQuery = Object.fromEntries(requestUrl.searchParams);
        }
        if (scenario === "retry" && !allowRetrySuccess) {
          return fulfill({ detail: { message: "upstream detail must stay hidden" } }, 503);
        }
        if (scenario === "retry") retried = true;
        if (scenario === "empty") {
          return fulfill({ items: [], total: 0, page: 1, page_size: 20, has_next: false });
        }
        const projectMode = requestUrl.searchParams.get("scope") === "project";
        const items = [
          asset(
            projectMode
              ? {
                  scope: "project",
                  project_name: "华东交付项目",
                  confidentiality_level: "L2",
                  access_info: {
                    ...asset().access_info,
                    original: true,
                    effective_source: "project_membership",
                  },
                }
              : {},
          ),
          asset({
            id: "00000000-0000-0000-0000-0000000000a2",
            title:
              "用于验证紧凑表格在超长知识资产名称与多行安全摘要情况下仍不撑破页面边界的交付模板",
            asset_type: "template",
            confidentiality_level: "L2",
            summary_text: "长文本会在资产主列内稳定换行，其余列和详情操作保持可见。",
            ...(projectMode ? { scope: "project", project_name: "华东交付项目" } : {}),
            access_info: {
              ...asset().access_info,
              original: true,
              effective_source: projectMode ? "project_membership" : "company_role",
            },
          }),
        ];
        return fulfill({ items, total: 42, page: 1, page_size: 20, has_next: true });
      }

      return fulfill({ detail: { message: "UI QA route not configured" } }, 404);
    });

    const page = await context.newPage();
    await page.goto(`${base}/knowledge`, { waitUntil: "networkidle" });

    if (scenario === "pure-admin") {
      await page.getByText("当前账号无此入口").waitFor();
    } else if (scenario === "empty") {
      await page.getByText("暂无可浏览的知识资产").waitFor();
    } else if (scenario === "retry") {
      await page.getByText("知识资产加载失败").waitFor();
      allowRetrySuccess = true;
      await page.getByRole("button", { name: "重试" }).click();
      await page.getByText("客户经营诊断方法论与跨部门交付复盘框架").waitFor();
    } else if (scenario === "project") {
      await page.getByText("客户经营诊断方法论与跨部门交付复盘框架").waitFor();
      await page.getByRole("tab", { name: "项目" }).click();
      await page.getByLabel("项目", { exact: true }).selectOption(projectId);
      await page.waitForFunction(() => document.body.innerText.includes("可查看摘要与原文"));
    } else {
      await page.getByText("客户经营诊断方法论与跨部门交付复盘框架").waitFor();
      await page.getByText("可查看摘要，原文受限").waitFor();
    }

    await page.waitForTimeout(180);
    const metrics = await page.evaluate(() => {
      const root = document.documentElement;
      const rail = document.querySelector(".rail")?.getBoundingClientRect();
      const deck = document.querySelector(".deck")?.getBoundingClientRect();
      const tableWrap = document.querySelector(".kbl-table-wrap");
      const filterFields = document
        .querySelector(".product-filter-fields")
        ?.getBoundingClientRect();
      const bodyText = document.body.innerText;
      const clippedActions = [...document.querySelectorAll("button, a.product-button")].filter(
        (element) => element.scrollWidth > element.clientWidth + 2,
      ).length;
      return {
        overflowX: root.scrollWidth - root.clientWidth,
        shellOverlap: rail && deck ? Math.max(0, rail.right - deck.left) : 1,
        tableOverflowMode: tableWrap ? getComputedStyle(tableWrap).overflowX : "missing",
        filterFieldsHeight: filterFields?.height ?? 999,
        clippedActions,
        moduleTitle: document.querySelector(".deck-title")?.textContent?.trim() ?? "",
        forbiddenFeatureVisible: /批量导入|导出|新建项目|运营洞察|语义检索|全局搜索/.test(bodyText),
        sensitiveTextVisible:
          bodyText.includes("00000000-0000-0000-0000-0000000000a1") ||
          /storage_ref|SECRET-LIKE|upstream detail|WeKnora|fetch token|api[_ -]?key/i.test(
            bodyText,
          ),
        tableVisible: Boolean(document.querySelector(".kbl-table")),
      };
    });

    await page.screenshot({
      path: path.join(outDir, `${scenario}-${viewport.name}.png`),
      fullPage: false,
      animations: "disabled",
    });

    let collapsedMetrics = {};
    if (scenario === "company") {
      await page.getByRole("button", { name: "折叠主导航" }).click();
      await page.waitForTimeout(160);
      collapsedMetrics = await page.evaluate(() => ({
        collapsedOverflowX:
          document.documentElement.scrollWidth - document.documentElement.clientWidth,
        collapsedButtonName:
          document.querySelector(".rail-collapse")?.getAttribute("aria-label") ?? "",
        collapsedKnowledgeTooltip:
          document.querySelector('a[aria-label="知识资产库"]')?.getAttribute("title") ?? "",
      }));
      await page.screenshot({
        path: path.join(outDir, `company-${viewport.name}-collapsed.png`),
        fullPage: false,
        animations: "disabled",
      });
    }

    results.push({
      scenario,
      viewport: viewport.name,
      knowledgeCalls,
      retried,
      projectQuery,
      ...metrics,
      ...collapsedMetrics,
    });
    await context.close();
  }
}

await browser.close();
fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify({ outDir, results }, null, 2));

if (
  results.some(
    (result) =>
      result.overflowX > 2 ||
      result.shellOverlap > 1 ||
      result.clippedActions > 0 ||
      result.moduleTitle !== "知识资产库" ||
      result.forbiddenFeatureVisible ||
      result.sensitiveTextVisible ||
      (result.scenario !== "pure-admin" &&
        (!["auto", "scroll"].includes(result.tableOverflowMode) ||
          result.filterFieldsHeight > 40 ||
          !result.tableVisible)) ||
      (result.scenario === "pure-admin" && (result.knowledgeCalls !== 0 || result.tableVisible)) ||
      (result.scenario === "retry" && (!result.retried || result.knowledgeCalls < 2)) ||
      (result.scenario === "project" &&
        (result.projectQuery?.scope !== "project" ||
          result.projectQuery?.project_id !== projectId)) ||
      (typeof result.collapsedOverflowX === "number" &&
        (result.collapsedOverflowX > 2 ||
          result.collapsedButtonName !== "展开主导航" ||
          result.collapsedKnowledgeTooltip !== "知识资产库")),
  )
) {
  process.exit(1);
}
