import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5194);
const base = `http://127.0.0.1:${port}`;
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "project-knowledge");
fs.mkdirSync(outDir, { recursive: true });

const projectA = "00000000-0000-0000-0000-000000000079";
const projectB = "00000000-0000-0000-0000-00000000007b";
const inaccessibleProject = "00000000-0000-0000-0000-00000000007c";
const assetA = "asset-secret-79-a";
const assetB = "asset-secret-79-b";
const modelRef = "model-ref-secret-79";
const scenarios = [
  "member-list",
  "manager-list",
  "filters-pagination",
  "switch-late",
  "empty-projects",
  "inaccessible",
  "list-failure",
  "filtered-empty",
  "no-model",
  "qa-success",
  "qa-failure",
  "upgrade-failure",
];
const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1280", width: 1280, height: 900 },
];

const knowledgeItem = (overrides = {}) => ({
  id: assetA,
  title: "客户经营诊断与交付复盘框架",
  scope: "project",
  zone: "material",
  asset_type: "methodology",
  confidentiality_level: "L2",
  ai_access_level: "A2",
  asset_status: "active",
  visibility: "project_only",
  tags: ["经营诊断"],
  summary_text: "列表不展示的安全摘要",
  project_name: "华东增长项目",
  lifecycle_phase: "internal_phase_secret",
  confidence: null,
  last_called_at: null,
  updated_at: "2026-07-15T08:00:00Z",
  access_info: {
    discovery: true,
    summary: true,
    original: false,
    effective_source: "internal_access_secret",
    can_request_original: true,
    existing_request_status: null,
    existing_grant_expires_at: null,
    can_delete: false,
    can_manage_lifecycle: false,
    can_retry_index: false,
  },
  index_status: "indexed",
  weknora_parse_status: null,
  index_error_message: null,
  indexed_at: null,
  ...overrides,
});

const qaResponse = {
  call_id: "call-secret-79",
  trace_id: "trace-secret-79",
  model_key: modelRef,
  decision_status: "internal_allowed",
  response_text: "访谈材料显示，客户当前最关注交付节奏与复盘机制。",
  citations: [
    {
      asset_id: assetA,
      asset_title: "客户访谈纪要",
      scope: "project",
      cited_zone: "material",
      used_access_layer: "internal_access_secret",
      is_pending_review: true,
      is_asset_zone: false,
      citation_order: 1,
      snippet: "original content secret",
    },
  ],
  created_at: "2026-07-16T08:00:00Z",
};

function authMe(scenario) {
  const memberships =
    scenario === "empty-projects"
      ? []
      : [
          {
            project_id: projectA,
            project_name: "华东增长项目",
            project_role: "consultant",
            status: "active",
          },
          {
            project_id: projectB,
            project_name: "年度辅导项目",
            project_role: "project_manager",
            status: "active",
          },
        ];
  return {
    user_id: "user-secret-79",
    name: "项目知识验收用户",
    email: "identity-secret@example.test",
    status: "active",
    company_roles: ["consultant"],
    active_company_role: "consultant",
    is_business_user: true,
    can_discover_l5: false,
    project_memberships: memberships,
  };
}

function accepted(result) {
  const basePass =
    result.overflowX <= 2 &&
    result.shellOverlap <= 1 &&
    result.clippedControls === 0 &&
    result.moduleTitle === "项目知识库" &&
    !result.sensitiveVisible &&
    !result.internalVisible &&
    !result.oldImplementationVisible &&
    result.pathCorrect;
  if (!basePass) return false;
  if (["empty-projects", "inaccessible"].includes(result.scenario)) {
    return !result.tableVisible && result.safeStateVisible;
  }
  if (!result.tableVisible || !result.toolbarBeforeTable || result.maxRowHeight > 76) return false;
  if (result.scenario === "member-list") {
    return (
      result.qaInitiallyCollapsed &&
      result.modelOptionsLazy &&
      result.domOrderCorrect &&
      result.qaEntryCount === 1 &&
      result.qaOutsideInitialViewport &&
      result.bottomQaVisible &&
      !result.managerActionVisible
    );
  }
  if (result.scenario === "manager-list") {
    return (
      result.qaInitiallyCollapsed &&
      result.modelOptionsLazy &&
      result.domOrderCorrect &&
      result.qaEntryCount === 1 &&
      result.qaOutsideInitialViewport &&
      result.bottomQaVisible &&
      result.managerActionVisible
    );
  }
  if (result.scenario === "filters-pagination") {
    return result.filterRequestCorrect && result.pageRequestCorrect && result.resetToFirstPage;
  }
  if (result.scenario === "switch-late") {
    return result.switchedToB && result.lateProjectContentHidden;
  }
  if (result.scenario === "list-failure") return result.failureSeen && result.retrySucceeded;
  if (result.scenario === "filtered-empty") return result.filteredEmptyVisible;
  if (result.scenario === "no-model") {
    return (
      result.modelOptionsLazy &&
      result.qaModelCalls === 1 &&
      result.noModelVisible &&
      result.qaInputDisabled
    );
  }
  if (result.scenario === "qa-success") {
    return result.modelOptionsLazy && result.qaModelCalls === 1 && result.safeAnswerVisible;
  }
  if (result.scenario === "qa-failure") {
    return result.modelOptionsLazy && result.qaModelCalls === 1 && result.qaFailureVisible;
  }
  if (result.scenario === "upgrade-failure") return result.upgradeFailureVisible;
  return true;
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
      let knowledgeCalls = 0;
      let qaModelCalls = 0;
      let capturedFilterQuery = null;
      let capturedPageQuery = null;
      let listFailureSeen = false;
      let retrySucceeded = false;
      let qaFailureSeen = false;
      let upgradeFailureSeen = false;
      let releaseLateList = () => {};
      const lateListGate = new Promise((resolve) => {
        releaseLateList = resolve;
      });
      const context = await browser.newContext({ viewport });

      await context.route("**/api/v1/**", async (route) => {
        const requestUrl = new URL(route.request().url());
        const method = route.request().method();
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

        if (requestUrl.pathname === "/api/v1/auth/me") return fulfill(authMe(scenario));

        if (requestUrl.pathname === "/api/v1/knowledge") {
          knowledgeCalls += 1;
          const query = Object.fromEntries(requestUrl.searchParams);
          if (scenario === "list-failure" && knowledgeCalls === 1) {
            listFailureSeen = true;
            return fulfill({ detail: { message: "storage_ref=s3://secret-upstream" } }, 503);
          }
          if (scenario === "list-failure") retrySucceeded = true;
          if (scenario === "switch-late" && query.project_id === projectA) {
            await lateListGate;
            return fulfill({
              items: [knowledgeItem({ title: "华东迟到知识" })],
              total: 1,
              page: 1,
              page_size: 20,
              has_next: false,
            });
          }
          if (scenario === "filtered-empty" && query.keyword) {
            return fulfill({ items: [], total: 0, page: 1, page_size: 20, has_next: false });
          }
          if (scenario === "filters-pagination") {
            if (query.keyword && query.zone === "asset" && query.sort_by === "title") {
              capturedFilterQuery = query;
            }
            if (query.page === "2") capturedPageQuery = query;
          }
          const isProjectB = query.project_id === projectB;
          const currentPage = Number(query.page || 1);
          const items = [
            knowledgeItem({
              id: isProjectB ? assetB : assetA,
              title: isProjectB ? "年度辅导项目知识" : "客户经营诊断与交付复盘框架",
              zone: isProjectB ? "asset" : "material",
              project_name: isProjectB ? "年度辅导项目" : "华东增长项目",
            }),
            knowledgeItem({
              id: `${isProjectB ? assetB : assetA}-2`,
              title: "跨部门协同交付模板",
              zone: "material",
              asset_type: "template",
              confidentiality_level: "L3",
              asset_status: "needs_update",
            }),
          ];
          return fulfill({
            items,
            total: scenario === "filters-pagination" ? 42 : items.length,
            page: currentPage,
            page_size: 20,
            has_next: scenario === "filters-pagination" && currentPage === 1,
          });
        }

        if (requestUrl.pathname.endsWith("/qa/model-options")) {
          qaModelCalls += 1;
          if (scenario === "no-model") return fulfill({ items: [], total: 0 });
          return fulfill({
            items: [
              { model_ref: "fallback-secret-79", display_name: "备用问答模型", is_default: false },
              { model_ref: modelRef, display_name: "项目默认问答模型", is_default: true },
            ],
            total: 2,
          });
        }

        if (requestUrl.pathname.endsWith("/qa") && method === "POST") {
          if (scenario === "qa-failure") {
            qaFailureSeen = true;
            return fulfill({ detail: { message: "provider token secret" } }, 503);
          }
          return fulfill(qaResponse);
        }

        if (requestUrl.pathname.endsWith("/upgrade-company") && method === "POST") {
          if (scenario === "upgrade-failure") {
            upgradeFailureSeen = true;
            return fulfill({ detail: { message: "internal approval secret" } }, 500);
          }
          return fulfill({ status: "pending" });
        }

        return fulfill({ detail: { message: "UI QA route not configured" } }, 404);
      });

      const page = await context.newPage();
      const initialProject = ["manager-list", "upgrade-failure"].includes(scenario)
        ? projectB
        : scenario === "inaccessible"
          ? inaccessibleProject
          : projectA;
      await page.goto(`${base}/project/${initialProject}/knowledge`, {
        waitUntil: scenario === "switch-late" ? "domcontentloaded" : "networkidle",
      });
      const modelOptionsLazy = qaModelCalls === 0;

      let filteredEmptyVisible = false;
      let safeAnswerVisible = false;
      let qaFailureVisible = false;
      let noModelVisible = false;
      let upgradeFailureVisible = false;
      let failureSeen = false;
      let switchedToB = false;
      let lateProjectContentHidden = true;
      let pageRequestCorrect = false;
      let resetToFirstPage = false;
      let initialLayout = {
        domOrderCorrect: false,
        qaEntryCount: 0,
        qaInitiallyCollapsed: false,
        qaOutsideInitialViewport: false,
      };
      let bottomQaVisible = false;

      if (scenario === "empty-projects") {
        await page.getByText("当前账号无此入口").waitFor();
      } else if (scenario === "inaccessible") {
        await page.getByText("项目不可访问").waitFor();
      } else if (scenario === "list-failure") {
        await page.getByText("项目知识加载失败").waitFor();
        failureSeen = true;
        await page.getByRole("button", { name: "重试" }).click();
        await page.getByText("客户经营诊断与交付复盘框架").waitFor();
      } else if (scenario === "switch-late") {
        await page.getByLabel("切换项目").selectOption(projectB);
        await page.getByText("年度辅导项目知识").waitFor();
        switchedToB = page.url().endsWith(`/project/${projectB}/knowledge`);
        releaseLateList();
        await page.waitForTimeout(120);
        lateProjectContentHidden = !(await page
          .getByText("华东迟到知识")
          .isVisible()
          .catch(() => false));
      } else {
        await page
          .getByText(
            ["manager-list", "upgrade-failure"].includes(scenario)
              ? "年度辅导项目知识"
              : "客户经营诊断与交付复盘框架",
          )
          .waitFor();

        if (["member-list", "manager-list"].includes(scenario)) {
          initialLayout = await page.evaluate(() => {
            const toolbar = document.querySelector(".pk-filter-form");
            const list = document.querySelector(".pk-list-section");
            const pagination = document.querySelector(".pk-pagination");
            const qa = document.querySelector(".pk-qa-section");
            const follows = (first, second) =>
              Boolean(first?.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
            return {
              domOrderCorrect:
                follows(toolbar, list) && follows(list, pagination) && follows(pagination, qa),
              qaEntryCount: document.querySelectorAll(".pk-qa-section").length,
              qaInitiallyCollapsed:
                document.querySelector(".pk-qa-toggle")?.getAttribute("aria-expanded") === "false",
              qaOutsideInitialViewport: Boolean(
                qa && qa.getBoundingClientRect().top >= window.innerHeight,
              ),
            };
          });
          await page.screenshot({
            path: path.join(outDir, `${scenario}-${viewport.name}-first-fold.png`),
            fullPage: false,
            animations: "disabled",
          });
          await page.locator(".pk-qa-section").scrollIntoViewIfNeeded();
          bottomQaVisible = await page.locator(".pk-qa-toggle").isVisible();
          await page.screenshot({
            path: path.join(outDir, `${scenario}-${viewport.name}-page-bottom.png`),
            fullPage: false,
            animations: "disabled",
          });
          await page.evaluate(() => window.scrollTo(0, 0));
        }

        if (scenario === "filters-pagination") {
          await page.getByPlaceholder("按标题或标签搜索").fill("交付");
          await page.getByLabel("资料区域").selectOption("asset");
          await page.getByLabel("资产类型").selectOption("case");
          await page.getByLabel("资产状态").selectOption("active");
          await page.getByLabel("保密级别").selectOption("L2");
          await page.getByText("更多筛选").click();
          await page.getByLabel("更新开始").fill("2026-01-01");
          await page.getByLabel("更新结束").fill("2026-07-16");
          await page.getByLabel("排序字段").selectOption("title");
          await page.getByLabel("排序方向").selectOption("asc");
          await page.getByRole("button", { name: "搜索" }).click();
          await page.waitForFunction(() => document.body.innerText.includes("共 42 条"));
          await page.getByRole("button", { name: "下一页" }).click();
          await page.waitForFunction(() => document.body.innerText.includes("显示 21-40 条"));
          pageRequestCorrect = capturedPageQuery?.page === "2";
          await page.getByLabel("资料区域").selectOption("material");
          await page.waitForFunction(() => document.body.innerText.includes("显示 1-20 条"));
          resetToFirstPage = true;
        }

        if (scenario === "filtered-empty") {
          await page.getByPlaceholder("按标题或标签搜索").fill("不存在");
          await page.getByRole("button", { name: "搜索" }).click();
          await page.getByText("当前条件没有匹配内容").waitFor();
          filteredEmptyVisible = true;
        }

        if (["no-model", "qa-success", "qa-failure"].includes(scenario)) {
          await page.getByRole("button", { name: /项目问答/ }).click();
          if (scenario === "no-model") {
            await page.getByText("当前项目暂无可用问答模型。").waitFor();
            noModelVisible = true;
          } else {
            await page.getByLabel("问答模型").selectOption("1");
            await page.getByPlaceholder("向当前项目知识提问…").fill("项目风险是什么？");
            await page.getByRole("button", { name: "提问", exact: true }).click();
            if (scenario === "qa-success") {
              await page.getByText(qaResponse.response_text).waitFor();
              safeAnswerVisible =
                (await page.getByText("客户访谈纪要").isVisible()) &&
                (await page.getByText("内容待审核，请谨慎参考").isVisible());
            } else {
              await page.getByText("问答暂时未完成，请稍后重试。").waitFor();
              qaFailureVisible = true;
            }
          }
        }

        if (scenario === "manager-list") {
          await page.getByLabel("更多操作：年度辅导项目知识").click();
          await page.getByRole("button", { name: "申请升格公司资产" }).waitFor();
        }

        if (scenario === "upgrade-failure") {
          await page.getByLabel("更多操作：年度辅导项目知识").click();
          await page.getByRole("button", { name: "申请升格公司资产" }).click();
          await page.getByText("升级申请提交失败，请稍后重试。").waitFor();
          upgradeFailureVisible = true;
        }
      }

      const result = await page.evaluate(
        ({ scenarioName, expectedPath, secrets }) => {
          const root = document.documentElement;
          const rail = document.querySelector(".rail")?.getBoundingClientRect();
          const deck = document.querySelector(".deck")?.getBoundingClientRect();
          const toolbar = document.querySelector(".pk-filter-form")?.getBoundingClientRect();
          const table = document.querySelector(".pk-table-wrap")?.getBoundingClientRect();
          const rows = [...document.querySelectorAll(".pk-table tbody tr")].filter((row) =>
            row.querySelector("td:not(.product-table-state)"),
          );
          const bodyText = document.body.innerText;
          const clippedControls = [...document.querySelectorAll("button, select, input")].filter(
            (element) => element.scrollWidth > element.clientWidth + 2,
          ).length;
          return {
            scenario: scenarioName,
            overflowX: root.scrollWidth - root.clientWidth,
            shellOverlap: rail && deck ? Math.max(0, rail.right - deck.left) : 1,
            clippedControls,
            moduleTitle: document.querySelector(".deck-title")?.textContent?.trim() ?? "",
            tableVisible: Boolean(document.querySelector(".pk-table")),
            toolbarBeforeTable: Boolean(toolbar && table && toolbar.bottom <= table.top + 24),
            maxRowHeight: Math.max(0, ...rows.map((row) => row.getBoundingClientRect().height)),
            qaInitiallyCollapsed:
              document.querySelector(".pk-qa-toggle")?.getAttribute("aria-expanded") === "false",
            managerActionVisible: Boolean(document.querySelector('[aria-label^="更多操作："]')),
            qaInputDisabled:
              document.querySelector(".pk-qa-body textarea") instanceof HTMLTextAreaElement &&
              document.querySelector(".pk-qa-body textarea").disabled,
            safeStateVisible: /暂无可访问项目|当前账号无此入口|项目不可访问/.test(bodyText),
            noModelVisible: bodyText.includes("当前项目暂无可用问答模型。"),
            safeAnswerVisible:
              bodyText.includes("访谈材料显示，客户当前最关注交付节奏与复盘机制。") &&
              bodyText.includes("内容待审核，请谨慎参考"),
            qaFailureVisible: bodyText.includes("问答暂时未完成，请稍后重试。"),
            upgradeFailureVisible: bodyText.includes("升级申请提交失败，请稍后重试。"),
            filteredEmptyVisible: bodyText.includes("当前条件没有匹配内容"),
            oldImplementationVisible:
              Boolean(document.querySelector(".pj-asset-grid, .lifecycle-row, .risk-list")) ||
              /生命周期阶段|资产沉淀提醒|常用问题/.test(bodyText),
            sensitiveVisible: secrets.some((secret) => bodyText.includes(secret)),
            internalVisible: [
              "internal_phase_secret",
              "internal_access_secret",
              "internal_allowed",
              "storage_ref",
              "provider token",
              "original content",
              "decision_status",
              "used_access_layer",
              "WeKnora",
            ].some((value) => bodyText.includes(value)),
            pathCorrect: window.location.pathname === expectedPath,
          };
        },
        {
          scenarioName: scenario,
          expectedPath:
            scenario === "switch-late"
              ? `/project/${projectB}/knowledge`
              : `/project/${initialProject}/knowledge`,
          secrets: [
            assetA,
            assetB,
            modelRef,
            "fallback-secret-79",
            "call-secret-79",
            "trace-secret-79",
            "user-secret-79",
            "identity-secret@example.test",
          ],
        },
      );

      Object.assign(result, {
        failureSeen,
        retrySucceeded,
        filterRequestCorrect:
          capturedFilterQuery?.scope === "project" &&
          capturedFilterQuery?.project_id === projectA &&
          capturedFilterQuery?.keyword === "交付" &&
          capturedFilterQuery?.zone === "asset" &&
          capturedFilterQuery?.asset_type === "case" &&
          capturedFilterQuery?.asset_status === "active" &&
          capturedFilterQuery?.confidentiality_level === "L2" &&
          capturedFilterQuery?.updated_from === "2026-01-01" &&
          capturedFilterQuery?.updated_to === "2026-07-16" &&
          capturedFilterQuery?.sort_by === "title" &&
          capturedFilterQuery?.sort_direction === "asc",
        pageRequestCorrect,
        resetToFirstPage,
        switchedToB,
        lateProjectContentHidden,
        filteredEmptyVisible,
        noModelVisible,
        safeAnswerVisible,
        qaFailureVisible: qaFailureVisible && qaFailureSeen,
        upgradeFailureVisible: upgradeFailureVisible && upgradeFailureSeen,
        listFailureSeen,
        knowledgeCalls,
        qaModelCalls,
        modelOptionsLazy,
        bottomQaVisible,
        ...initialLayout,
      });

      await page.screenshot({
        path: path.join(outDir, `${scenario}-${viewport.name}.png`),
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
  throw new Error(`PBC-79 project knowledge UI QA failed in ${failed.length} scenario(s)`);
}
