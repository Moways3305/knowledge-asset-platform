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
const modelRef = "qa-model-ref-secret-78";
const scenarios = [
  "member-initial",
  "manager",
  "manager-confirmation-only",
  "qa-success",
  "qa-sending",
  "qa-failure",
  "no-model",
  "model-failure",
  "switch-late-answer",
  "empty-projects",
  "inaccessible",
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

const models = {
  items: [
    { model_ref: "secondary-model-secret", display_name: "备用问答模型", is_default: false },
    { model_ref: modelRef, display_name: "项目默认问答模型", is_default: true },
  ],
  total: 2,
};

const qaAnswer = {
  call_id: "call-secret-78",
  response_text: "访谈材料显示，客户当前最关注交付节奏与复盘机制。",
  model_key: modelRef,
  decision_status: "allowed",
  citations: [
    {
      asset_id: hiddenAssetId,
      asset_title: "客户访谈纪要",
      scope: "project",
      cited_zone: "material",
      used_access_layer: "summary",
      is_pending_review: true,
      is_asset_zone: false,
      citation_order: 1,
      snippet: "original content must stay hidden",
    },
  ],
  trace_id: "trace-secret-78",
  created_at: "2026-07-16T08:00:00Z",
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
    recent_activity: [],
  };
}

function hasValidSkeleton(result) {
  return (
    result.contextWidth >= 200 &&
    result.contextWidth <= 300 &&
    result.assistantWidth / result.contextWidth >= 2.5 &&
    result.composerVisible &&
    result.conversationScrollable &&
    !result.oldDashboardPresent &&
    result.chartCount === 0
  );
}

function accepted(result) {
  if (
    result.overflowX > 2 ||
    result.shellOverlap > 1 ||
    result.clippedControls > 0 ||
    result.deckTitle !== "项目空间" ||
    result.sensitiveVisible ||
    result.internalEnumVisible
  ) {
    return false;
  }
  if (["empty-projects", "inaccessible"].includes(result.scenario)) {
    return result.scenario === "empty-projects" ? result.emptyVisible : result.inaccessibleVisible;
  }
  if (result.scenario === "overview-failure") {
    return result.overviewFailureSeen && result.retrySucceeded && hasValidSkeleton(result);
  }
  if (!hasValidSkeleton(result)) return false;
  if (result.scenario === "member-initial") {
    return (
      result.welcomeVisible &&
      result.defaultModelSelected &&
      result.inputEnabled &&
      result.emptySendDisabled &&
      result.memberSectionCount === 0 &&
      result.knowledgeLinkCorrect
    );
  }
  if (result.scenario === "manager") {
    return result.memberVisible && result.reviewLinkCorrect && result.settingsVisible;
  }
  if (result.scenario === "manager-confirmation-only") {
    return result.pendingConfirmationStat && !result.reviewActionVisible;
  }
  if (result.scenario === "qa-success") {
    return result.questionVisible && result.answerVisible && result.safeCitationVisible;
  }
  if (result.scenario === "qa-sending") return result.sendingVisible && result.inputDisabled;
  if (result.scenario === "qa-failure") {
    return result.qaFailureSeen && result.retrySucceeded && result.answerVisible;
  }
  if (result.scenario === "no-model") {
    return result.noModelVisible && result.inputDisabled && result.emptySendDisabled;
  }
  if (result.scenario === "model-failure") {
    return result.modelFailureSeen && result.retrySucceeded && result.defaultModelSelected;
  }
  if (result.scenario === "switch-late-answer") {
    return (
      result.projectBHeading &&
      result.projectBWelcome &&
      !result.oldQuestionVisible &&
      !result.answerVisible &&
      result.pathEndsWithProjectB
    );
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
      let modelCalls = 0;
      let qaCalls = 0;
      let overviewFailureSeen = false;
      let modelFailureSeen = false;
      let qaFailureSeen = false;
      let retrySucceeded = false;
      let releasePendingQa;
      const pendingQa = new Promise((resolve) => {
        releasePendingQa = resolve;
      });
      const context = await browser.newContext({ viewport });
      await context.route("**/api/v1/**", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

        if (url.pathname === "/api/v1/auth/me") return fulfill(authMe);
        if (url.pathname === "/api/v1/projects") {
          return fulfill({ items: scenario === "empty-projects" ? [] : projectItems });
        }

        const modelMatch = url.pathname.match(/^\/api\/v1\/projects\/([^/]+)\/qa\/model-options$/);
        if (modelMatch) {
          modelCalls += 1;
          if (scenario === "model-failure" && modelCalls === 1) {
            return fulfill({ detail: { message: "provider secret must stay hidden" } }, 503);
          }
          return fulfill(scenario === "no-model" ? { items: [], total: 0 } : models);
        }

        const qaMatch = url.pathname.match(/^\/api\/v1\/projects\/([^/]+)\/qa$/);
        if (qaMatch && request.method() === "POST") {
          qaCalls += 1;
          if (scenario === "qa-failure" && qaCalls === 1) {
            return fulfill({ detail: { message: "upstream trace secret" } }, 503);
          }
          if (scenario === "qa-sending" || scenario === "switch-late-answer") {
            await pendingQa;
          }
          return fulfill(qaAnswer);
        }

        const overviewMatch = url.pathname.match(/^\/api\/v1\/projects\/([^/]+)\/overview$/);
        if (overviewMatch) {
          overviewCalls += 1;
          if (scenario === "overview-failure" && overviewCalls === 1) {
            return fulfill({ detail: { message: "internal project secret" } }, 503);
          }
          const manager =
            scenario === "manager" ||
            scenario === "manager-confirmation-only" ||
            overviewMatch[1] === projectB;
          const payload = overview(overviewMatch[1], manager);
          if (scenario === "manager-confirmation-only") payload.counts.pending_review_count = 0;
          return fulfill(payload);
        }
        return fulfill({ detail: { message: "UI QA route not configured" } }, 404);
      });

      const page = await context.newPage();
      const initialProject = scenario === "inaccessible" ? "not-accessible" : projectA;
      await page.goto(`${base}/project/${initialProject}`, { waitUntil: "networkidle" });

      if (scenario === "empty-projects") {
        await page.getByText("暂无可访问项目").waitFor();
      } else if (scenario === "inaccessible") {
        await page.getByText("项目不可访问").waitFor();
      } else if (scenario === "overview-failure") {
        await page.getByText("项目概览加载失败").waitFor();
        overviewFailureSeen = true;
        await page.getByRole("button", { name: "重试" }).click();
        await page.getByRole("heading", { name: "项目 AI 助手" }).waitFor();
        retrySucceeded = true;
      } else {
        await page.getByRole("heading", { name: "项目 AI 助手" }).waitFor();
      }

      if (["qa-success", "qa-sending", "qa-failure", "switch-late-answer"].includes(scenario)) {
        await page
          .getByRole("textbox", { name: "向项目 AI 助手提问" })
          .fill("项目 A 的关键风险是什么？");
        await page.getByRole("button", { name: "提问" }).click();
      }
      if (scenario === "qa-success") {
        await page.getByText(qaAnswer.response_text).waitFor();
      } else if (scenario === "qa-failure") {
        await page.getByText("暂时无法完成回答，请稍后重试。").waitFor();
        qaFailureSeen = true;
        await page.getByRole("button", { name: "重新提问" }).click();
        await page.getByText(qaAnswer.response_text).waitFor();
        retrySucceeded = true;
      } else if (scenario === "qa-sending") {
        await page.getByText("正在整理项目知识…").waitFor();
      } else if (scenario === "switch-late-answer") {
        await page.getByText("正在整理项目知识…").waitFor();
        await page.getByLabel("切换项目").selectOption(projectB);
        await page.getByText("可以围绕“年度辅导项目”的项目知识提问。").waitFor();
        releasePendingQa();
        await page.waitForTimeout(80);
      } else if (scenario === "model-failure") {
        await page.getByText("问答模型暂时不可用").waitFor();
        modelFailureSeen = true;
        await page.getByRole("button", { name: "重试" }).click();
        await page.waitForFunction(
          (expected) =>
            document.querySelector('select[aria-label="问答模型"]')?.value === expected,
          modelRef,
        );
        retrySucceeded = true;
      } else if (scenario === "no-model") {
        await page.getByText("当前项目暂无可用问答模型").waitFor();
      }

      const result = await page.evaluate(
        ({
          scenarioName,
          projectAId,
          projectBId,
          defaultModelRef,
          overviewFailureWasSeen,
          modelFailureWasSeen,
          qaFailureWasSeen,
          retryDidSucceed,
          secrets,
        }) => {
          const bodyText = document.body.innerText;
          const rail = document.querySelector(".rail")?.getBoundingClientRect();
          const appMain = document.querySelector(".app-main")?.getBoundingClientRect();
          const contextPanel = document
            .querySelector(".project78-context")
            ?.getBoundingClientRect();
          const assistant = document.querySelector(".project78-assistant")?.getBoundingClientRect();
          const composer = document.querySelector(".project78-composer")?.getBoundingClientRect();
          const conversation = document.querySelector(".project78-conversation");
          const input = document.querySelector("#project78-question");
          const send = document.querySelector(".project78-send");
          const model = document.querySelector('select[aria-label="问答模型"]');
          const reviewLink = [...document.querySelectorAll(".project78-context-actions a")].find(
            (link) => link.textContent?.includes("处理待审核（2）"),
          );
          const interactive = [
            ...document.querySelectorAll(
              ".project78-assistant button, .project78-assistant textarea, .project78-assistant select",
            ),
          ];
          return {
            scenario: scenarioName,
            overflowX: document.documentElement.scrollWidth - window.innerWidth,
            shellOverlap: rail && appMain ? Math.max(0, rail.right - appMain.left) : 0,
            clippedControls: interactive.filter((element) => {
              const rect = element.getBoundingClientRect();
              return (
                rect.left < 0 || rect.right > window.innerWidth || rect.bottom > window.innerHeight
              );
            }).length,
            deckTitle: document.querySelector(".deck-title")?.textContent?.trim() || "",
            contextWidth: contextPanel?.width || 0,
            assistantWidth: assistant?.width || 0,
            composerVisible: Boolean(
              composer &&
              assistant &&
              composer.top >= assistant.top &&
              composer.bottom <= window.innerHeight,
            ),
            conversationScrollable:
              conversation instanceof HTMLElement &&
              ["auto", "scroll"].includes(getComputedStyle(conversation).overflowY),
            oldDashboardPresent: Boolean(
              document.querySelector(".project78-counts, .project78-action-list, .project78-main"),
            ),
            chartCount: document.querySelectorAll("canvas, .chart, [data-chart]").length,
            welcomeVisible: bodyText.includes("可以围绕“华东增长项目”的项目知识提问。"),
            projectBWelcome: bodyText.includes("可以围绕“年度辅导项目”的项目知识提问。"),
            projectBHeading: [...document.querySelectorAll(".project78-context h2")].some(
              (heading) => heading.textContent?.trim() === "年度辅导项目",
            ),
            memberSectionCount: document.querySelectorAll(".project78-members").length,
            memberVisible: bodyText.includes("周项目经理"),
            settingsVisible: Boolean(
              [...document.querySelectorAll(".project78-context-actions a")].find(
                (link) => link.textContent?.includes("项目设置"),
              ),
            ),
            reviewActionVisible: Boolean(reviewLink),
            reviewLinkCorrect:
              reviewLink?.getAttribute("href") === `/project/${projectAId}/settings`,
            pendingConfirmationStat: [...document.querySelectorAll(".project78-facts div")].some(
              (item) => item.textContent?.includes("待确认") && item.textContent?.includes("3"),
            ),
            knowledgeLinkCorrect:
              document.querySelector(".project78-context-actions a")?.getAttribute("href") ===
              `/project/${projectAId}/knowledge`,
            defaultModelSelected:
              model instanceof HTMLSelectElement && model.value === defaultModelRef,
            inputEnabled: input instanceof HTMLTextAreaElement && !input.disabled,
            inputDisabled: input instanceof HTMLTextAreaElement && input.disabled,
            emptySendDisabled: send instanceof HTMLButtonElement && send.disabled,
            sendingVisible: bodyText.includes("正在整理项目知识…"),
            noModelVisible: bodyText.includes("当前项目暂无可用问答模型"),
            questionVisible: bodyText.includes("项目 A 的关键风险是什么？"),
            oldQuestionVisible: bodyText.includes("项目 A 的关键风险是什么？"),
            answerVisible: bodyText.includes("访谈材料显示，客户当前最关注交付节奏与复盘机制。"),
            safeCitationVisible:
              bodyText.includes("客户访谈纪要") &&
              bodyText.includes("资料区") &&
              bodyText.includes("内容待审核，请谨慎参考"),
            emptyVisible: bodyText.includes("暂无可访问项目"),
            inaccessibleVisible: bodyText.includes("项目不可访问"),
            overviewFailureSeen: overviewFailureWasSeen,
            modelFailureSeen: modelFailureWasSeen,
            qaFailureSeen: qaFailureWasSeen,
            retrySucceeded: retryDidSucceed,
            pathEndsWithProjectB: window.location.pathname === `/project/${projectBId}`,
            sensitiveVisible: secrets.some((secret) => bodyText.includes(secret)),
            internalEnumVisible: [
              "route_A",
              "route_B",
              "project_manager",
              "consultant",
              "archived",
              "诊断",
              "年度复盘",
              "decision_status",
              "used_access_layer",
              "storage_ref",
              "weknora",
              "original content",
            ].some((value) => bodyText.includes(value)),
          };
        },
        {
          scenarioName: scenario,
          projectAId: projectA,
          projectBId: projectB,
          defaultModelRef: modelRef,
          overviewFailureWasSeen: overviewFailureSeen,
          modelFailureWasSeen: modelFailureSeen,
          qaFailureWasSeen: qaFailureSeen,
          retryDidSucceed: retrySucceeded,
          secrets: [
            projectA,
            projectB,
            hiddenMemberId,
            hiddenAssetId,
            modelRef,
            "secondary-model-secret",
            "call-secret-78",
            "trace-secret-78",
            "identity-hidden@example.test",
          ],
        },
      );

      await page.screenshot({
        path: path.join(outDir, `${scenario}-${viewport.name}.png`),
        fullPage: true,
      });
      results.push({ viewport: viewport.name, ...result, passed: accepted(result) });
      if (scenario === "qa-sending") releasePendingQa();
      await context.close();
    }
  }
} finally {
  await browser?.close();
  await previewServer?.close();
}

console.log(JSON.stringify(results, null, 2));
const failed = results.filter((result) => !result.passed);
if (failed.length > 0)
  throw new Error(`PBC-78 strict-reference UI QA failed in ${failed.length} scenario(s)`);
