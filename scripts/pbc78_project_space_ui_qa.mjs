import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5193);
const base = `http://127.0.0.1:${port}`;
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "pbc78-project-space");
fs.mkdirSync(outDir, { recursive: true });

const projectA = "00000000-0000-0000-0000-000000000078";
const projectB = "00000000-0000-0000-0000-000000000079";
const hiddenMemberId = "member-secret-78";
const hiddenAssetId = "asset-secret-78";
const scenarios = [
  "member",
  "manager",
  "switch-project",
  "empty-projects",
  "inaccessible",
  "list-failure",
  "overview-failure",
];
const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1920", width: 1920, height: 1080 },
];

const projectItems = [
  {
    id: projectA,
    name: "华东增长项目",
    client_name: "华东客户中心",
    status: "active",
    lifecycle_route_key: "route_A",
    lifecycle_phase_key: "诊断",
    created_at: "2026-07-01T08:00:00Z",
    project_role: "consultant",
    can_manage: false,
  },
  {
    id: projectB,
    name: "年度辅导项目",
    client_name: "战略发展中心",
    status: "active",
    lifecycle_route_key: "route_B",
    lifecycle_phase_key: "年度复盘",
    created_at: "2026-07-02T08:00:00Z",
    project_role: "project_manager",
    can_manage: true,
  },
];

const authMe = {
  user_id: "user-secret-78",
  name: "项目空间验收用户",
  email: "identity-hidden@example.test",
  status: "active",
  company_roles: ["consultant"],
  is_business_user: true,
  can_discover_l5: false,
  project_memberships: [
    {
      project_id: projectA,
      project_name: "华东增长项目",
      project_role: "consultant",
      status: "active",
    },
  ],
};

function overview(projectId, manager = false) {
  const item = projectItems.find((project) => project.id === projectId) || projectItems[0];
  return {
    project: {
      project_id: item.id,
      name: item.name,
      client_name: item.client_name,
      status: item.status,
      project_role: manager ? "project_manager" : item.project_role,
      lifecycle_route_key: item.lifecycle_route_key,
      lifecycle_phase_key: item.lifecycle_phase_key,
      can_manage: manager,
    },
    capabilities: {
      can_view_knowledge: true,
      can_upload_material: true,
      can_manage_members: manager,
      can_manage_kb: false,
      can_confirm_assets: manager,
    },
    counts: {
      material_count: 12,
      asset_count: 7,
      pending_confirmation_count: 3,
      pending_review_count: 2,
      original_access_request_count: 1,
    },
    knowledge_base: { configured: true, status: "active" },
    members: manager
      ? [
          {
            user_id: hiddenMemberId,
            name: "周项目经理",
            project_role: "project_manager",
            status: "active",
          },
        ]
      : [],
    recent_activity: [
      {
        asset_id: hiddenAssetId,
        title: "客户访谈洞察",
        zone: "asset",
        asset_type: "insight",
        confidentiality_level: "L2",
        updated_at: "2026-07-16T08:00:00Z",
      },
    ],
  };
}

function accepted(result) {
  if (
    result.overflowX > 2 ||
    result.shellOverlap > 1 ||
    result.clippedActions > 0 ||
    result.chartCount > 0 ||
    result.deckTitle !== "项目空间"
  ) {
    return false;
  }
  if (result.sensitiveVisible || result.internalEnumVisible) return false;
  if (result.scenario === "member") {
    return (
      result.projectAVisible &&
      result.countsVisible &&
      result.memberSectionCount === 0 &&
      !result.settingsVisible
    );
  }
  if (result.scenario === "manager") {
    return result.memberVisible && result.settingsVisible && result.confirmVisible;
  }
  if (result.scenario === "switch-project") {
    return (
      result.projectBHeading && result.pathEndsWithProjectB && result.projectBOverviewCalls === 1
    );
  }
  if (result.scenario === "empty-projects")
    return result.emptyVisible && result.overviewCalls === 0;
  if (result.scenario === "inaccessible")
    return result.inaccessibleVisible && result.overviewCalls === 0;
  if (result.scenario === "list-failure") {
    return result.listFailureSeen && result.retrySucceeded && result.overviewCalls === 1;
  }
  if (result.scenario === "overview-failure") {
    return result.overviewFailureSeen && result.retrySucceeded && result.overviewCalls === 2;
  }
  return false;
}

let previewServer;
let browser;
const results = [];

try {
  await build({ logLevel: "warn" });
  previewServer = await preview({
    logLevel: "warn",
    preview: { host: "127.0.0.1", port, strictPort: true },
  });
  browser = await chromium.launch({ args: ["--disable-gpu"] });

  for (const scenario of scenarios) {
    for (const viewport of viewports) {
      let overviewCalls = 0;
      let projectBOverviewCalls = 0;
      let listCalls = 0;
      let listFailureSeen = false;
      let overviewFailureSeen = false;
      let retrySucceeded = false;
      const context = await browser.newContext({ viewport });
      await context.route("**/api/v1/**", async (route) => {
        const url = new URL(route.request().url());
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

        if (url.pathname === "/api/v1/auth/me") return fulfill(authMe);
        if (url.pathname === "/api/v1/projects") {
          listCalls += 1;
          if (scenario === "list-failure" && listCalls === 1) {
            return fulfill({ detail: { message: "项目列表暂时不可用" } }, 503);
          }
          return fulfill({ items: scenario === "empty-projects" ? [] : projectItems });
        }
        const match = url.pathname.match(/^\/api\/v1\/projects\/([^/]+)\/overview$/);
        if (match) {
          overviewCalls += 1;
          if (match[1] === projectB) projectBOverviewCalls += 1;
          if (scenario === "overview-failure" && overviewCalls === 1) {
            return fulfill({ detail: { message: "项目概览暂时不可用" } }, 503);
          }
          return fulfill(overview(match[1], scenario === "manager" || match[1] === projectB));
        }
        return fulfill({ detail: { message: "UI QA route not configured" } }, 404);
      });

      const page = await context.newPage();
      const initialProject = scenario === "inaccessible" ? "not-accessible" : projectA;
      await page.goto(`${base}/project/${initialProject}`, { waitUntil: "networkidle" });

      if (scenario === "switch-project") {
        await page.getByLabel("切换项目").selectOption(projectB);
        await page.getByRole("heading", { name: "年度辅导项目" }).waitFor();
      } else if (scenario === "empty-projects") {
        await page.getByText("暂无可访问项目").waitFor();
      } else if (scenario === "inaccessible") {
        await page.getByText("项目不可访问").waitFor();
      } else if (scenario === "list-failure") {
        await page.getByText("项目列表加载失败").waitFor();
        listFailureSeen = true;
        await page.getByRole("button", { name: "重试" }).click();
        await page.getByText("最近更新的知识").waitFor();
        retrySucceeded = true;
      } else if (scenario === "overview-failure") {
        await page.getByText("项目概览加载失败").waitFor();
        overviewFailureSeen = true;
        await page.getByRole("button", { name: "重试" }).click();
        await page.getByText("最近更新的知识").waitFor();
        retrySucceeded = true;
      } else {
        await page.getByText("最近更新的知识").waitFor();
      }

      const result = await page.evaluate(
        ({
          scenarioName,
          projectBId,
          overviewCount,
          projectBCount,
          listFailureWasSeen,
          overviewFailureWasSeen,
          retryDidSucceed,
          secrets,
        }) => {
          const bodyText = document.body.innerText;
          const rail = document.querySelector(".rail")?.getBoundingClientRect();
          const main = document.querySelector(".app-main")?.getBoundingClientRect();
          const actionLinks = [...document.querySelectorAll(".project78-action-list a")];
          return {
            scenario: scenarioName,
            overflowX: document.documentElement.scrollWidth - window.innerWidth,
            shellOverlap: rail && main ? Math.max(0, rail.right - main.left) : 0,
            clippedActions: actionLinks.filter((link) => {
              const rect = link.getBoundingClientRect();
              return rect.left < 0 || rect.right > window.innerWidth || rect.height < 32;
            }).length,
            chartCount: document.querySelectorAll("canvas, .chart, [data-chart]").length,
            deckTitle: document.querySelector(".deck-title")?.textContent?.trim() || "",
            projectAVisible: bodyText.includes("华东增长项目"),
            projectBVisible: bodyText.includes("年度辅导项目"),
            countsVisible: ["项目资料", "知识资产", "待确认", "待升级审核", "原文访问申请"].every(
              (text) => bodyText.includes(text),
            ),
            memberSectionCount: document.querySelectorAll(".project78-members").length,
            memberVisible: bodyText.includes("周项目经理"),
            projectBHeading:
              document.querySelector(".project78-heading h2")?.textContent?.trim() ===
              "年度辅导项目",
            settingsVisible: Boolean(
              document.querySelector('.project78-action-list a[href$="/settings"]'),
            ),
            confirmVisible: Boolean(
              [...document.querySelectorAll(".project78-action-list a")].find((link) =>
                link.textContent?.includes("处理待确认（3）"),
              ),
            ),
            emptyVisible: bodyText.includes("暂无可访问项目"),
            inaccessibleVisible: bodyText.includes("项目不可访问"),
            listFailureVisible: bodyText.includes("项目列表加载失败"),
            overviewFailureVisible: bodyText.includes("项目概览加载失败"),
            listFailureSeen: listFailureWasSeen,
            overviewFailureSeen: overviewFailureWasSeen,
            retrySucceeded: retryDidSucceed,
            pathEndsWithProjectB: window.location.pathname === `/project/${projectBId}`,
            overviewCalls: overviewCount,
            projectBOverviewCalls: projectBCount,
            sensitiveVisible: secrets.some((secret) => bodyText.includes(secret)),
            internalEnumVisible: [
              "route_A",
              "route_B",
              "project_manager",
              "consultant",
              "archived",
              "storage_ref",
              "weknora",
              "token",
            ].some((value) => bodyText.includes(value)),
          };
        },
        {
          scenarioName: scenario,
          projectBId: projectB,
          overviewCount: overviewCalls,
          projectBCount: projectBOverviewCalls,
          listFailureWasSeen: listFailureSeen,
          overviewFailureWasSeen: overviewFailureSeen,
          retryDidSucceed: retrySucceeded,
          secrets: [
            projectA,
            projectB,
            hiddenMemberId,
            hiddenAssetId,
            "identity-hidden@example.test",
          ],
        },
      );

      await page.screenshot({
        path: path.join(outDir, `${scenario}-${viewport.name}.png`),
        fullPage: true,
      });
      results.push({ viewport: viewport.name, ...result, passed: accepted(result) });
      await context.close();
    }
  }
} finally {
  await browser?.close();
  await previewServer?.close();
}

console.log(JSON.stringify(results, null, 2));
const failed = results.filter((result) => !result.passed);
if (failed.length > 0) throw new Error(`PBC-78 UI QA failed in ${failed.length} scenario(s)`);
