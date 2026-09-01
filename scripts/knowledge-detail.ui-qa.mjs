import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.UI_QA_BASE || "http://localhost:5179";
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "knowledge-detail");
fs.mkdirSync(outDir, { recursive: true });

const assetId = "00000000-0000-0000-0000-000000000076";
const projectId = "00000000-0000-0000-0000-000000000176";
const directoryKey = "company.methodology";
const lifecycleCases = [
  ["archive_warning", "归档预警"],
  ["archive_candidate", "归档候选"],
  ["archived", "资产已归档"],
  ["reenable_requested", "申请重新启用"],
  ["reenabled", "资产已重新启用"],
  ["status_changed", "资产状态已变更"],
];
const scenarios = [
  "full",
  "requestable",
  "pending",
  "restricted",
  "failure",
  "denied",
  "preview-failure",
  "waiting-index",
  "indexing",
  "governed",
  "manager-publication",
];
const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1024", width: 1024, height: 900 },
  { name: "768", width: 768, height: 900 },
  { name: "390", width: 390, height: 844 },
];

const access = (overrides = {}) => ({
  discovery: true,
  summary: true,
  original: true,
  effective_source: "project_membership",
  can_request_original: false,
  existing_request_status: null,
  existing_grant_expires_at: null,
  can_delete: false,
  can_manage_lifecycle: false,
  can_retry_index: false,
  ...overrides,
});

const accessFor = (scenario) => {
  if (scenario === "requestable") return access({ original: false, can_request_original: true });
  if (scenario === "pending") {
    return access({
      original: false,
      can_request_original: true,
      existing_request_status: "pending",
    });
  }
  if (scenario === "restricted") return access({ summary: false, original: false });
  if (scenario === "governed") {
    return access({ can_delete: false, can_manage_lifecycle: true, can_retry_index: true });
  }
  return access();
};

const detail = (scenario) => ({
  id: assetId,
  title: "客户增长项目复盘方法论",
  scope: "project",
  zone: "asset",
  asset_type: "methodology",
  confidentiality_level: "L3",
  ai_access_level: "A2",
  asset_status: "active",
  visibility: "project_only",
  tags: ["增长", "复盘", "方法沉淀"],
  project_id: projectId,
  project_name: "华东增长策略项目",
  lifecycle_phase: "项目复盘",
  maintainer: { id: "maintainer-hidden", name: "知识治理负责人" },
  confidence: 0.94,
  last_called_at: null,
  updated_at: "2026-07-15T08:00:00Z",
  archived_at: null,
  archive_reason: null,
  summary:
    scenario === "restricted"
      ? null
      : {
          one_liner: "归纳增长项目中的假设验证、交付复盘和方法沉淀路径。",
          detailed: "覆盖目标拆解、关键假设验证、客户反馈归纳和项目复盘四个阶段。",
          key_points: ["优先验证关键假设", "将复盘结论沉淀为可复用方法"],
        },
  current_version: { id: "version-hidden", version_no: "v2", version_status: "active" },
  access_info: accessFor(scenario),
  index_status:
    scenario === "governed"
      ? "index_failed"
      : scenario === "waiting-index"
        ? "not_indexed"
        : scenario === "indexing"
          ? "indexing"
          : "indexed",
  canonical_markdown_status: "generated",
  weknora_parse_status: scenario === "indexing" ? "processing" : "success",
  index_error_code: scenario === "governed" ? "safe_retryable" : null,
  index_error_message: scenario === "governed" ? "问答处理未完成，可重新处理。" : null,
  indexed_at: ["waiting-index", "indexing"].includes(scenario) ? null : "2026-07-15T08:10:00Z",
});

const listItem = {
  id: assetId,
  title: "客户增长项目复盘方法论",
  scope: "project",
  zone: "asset",
  asset_type: "methodology",
  confidentiality_level: "L3",
  ai_access_level: "A2",
  asset_status: "active",
  visibility: "project_only",
  tags: ["增长"],
  summary_text: "归纳增长项目中的假设验证、交付复盘和方法沉淀路径。",
  project_name: "华东增长策略项目",
  lifecycle_phase: "项目复盘",
  confidence: 0.94,
  last_called_at: null,
  updated_at: "2026-07-15T08:00:00Z",
  access_info: access(),
  index_status: "indexed",
  weknora_parse_status: "success",
  index_error_message: null,
  indexed_at: "2026-07-15T08:10:00Z",
};

const browser = await chromium.launch({ args: ["--disable-gpu"] });
const results = [];

for (const scenario of scenarios) {
  for (const viewport of viewports) {
    let detailCalls = 0;
    let allowFailureRecovery = false;
    let lifecycleCalls = 0;
    const context = await browser.newContext({ viewport });
    await context.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url());
      const fulfill = (body, status = 200) =>
        route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

      if (url.pathname === "/api/v1/auth/me") {
        return fulfill({
          user_id: "user-hidden",
          name: "知识顾问验收用户",
          email: "identity-not-rendered@example.test",
          status: "active",
          company_roles: ["consultant"],
          active_company_role: "consultant",
          is_business_user: true,
          can_discover_l5: false,
          project_memberships: [
            {
              project_id: projectId,
              project_name: "华东增长策略项目",
              project_role: scenario === "manager-publication" ? "project_manager" : "consultant",
              status: "active",
            },
          ],
        });
      }
      if (url.pathname === "/api/v1/knowledge") {
        return fulfill({ items: [listItem], total: 1, page: 1, page_size: 20, has_next: false });
      }
      if (url.pathname === "/api/v1/knowledge/directories") {
        return fulfill({
          items: [
            {
              directory_key: directoryKey,
              name: "01 公司方法论",
              description: "公司级方法与标准资产",
              scope: "company",
              display_path: "公司库 / 01 公司方法论",
              parent_key: null,
              project_id: null,
              project_name: null,
            },
          ],
        });
      }
      if (url.pathname === `/api/v1/knowledge/${assetId}`) {
        detailCalls += 1;
        if (scenario === "denied") {
          return fulfill({ detail: { message: "authorization internals must stay hidden" } }, 404);
        }
        if (scenario === "failure" && !allowFailureRecovery) {
          return fulfill({ detail: { message: "SECRET-LIKE upstream detail" } }, 503);
        }
        return fulfill(detail(scenario));
      }
      if (url.pathname === `/api/v1/knowledge/${assetId}/preview`) {
        return fulfill({
          credential_id: "credential-must-not-render",
          preview_type: "full",
          credential_fingerprint: "fingerprint-must-not-render",
          preview_entry_url: "/api/v1/preview/entry-76",
          expires_at: "2026-07-16T09:00:00Z",
          credential_status: "active",
        });
      }
      if (url.pathname === "/api/v1/preview/entry-76") {
        return fulfill({
          preview_type: "full",
          document_title: "客户增长项目复盘方法论.docx",
          expires_at: "2026-07-16T09:00:00Z",
          credential_status: "active",
          onlyoffice_config: null,
          message: "onlyoffice_not_configured",
        });
      }
      if (url.pathname === `/api/v1/knowledge/${assetId}/lifecycle/events`) {
        lifecycleCalls += 1;
        return fulfill({
          items: lifecycleCases.map(([eventType], index) => ({
            event_id: `event-hidden-${index}`,
            event_type: eventType,
            old_status: "active",
            new_status: "active",
            reason: "完成年度复核",
            actor_display: "知识治理负责人",
            created_at: "2026-07-15T10:00:00Z",
            trace_id: "trace-must-not-render",
          })),
        });
      }
      return fulfill({ detail: { message: "UI QA route not configured" } }, 404);
    });

    const page = await context.newPage();
    if (scenario === "full") {
      await page.goto(`${base}/knowledge`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: /公司库/ }).click();
      await page.getByRole("button", { name: /01 公司方法论/ }).click();
      await page.getByRole("link", { name: "查看详情" }).click();
      await page.waitForURL(`**/knowledge/${assetId}`);
    } else {
      await page.goto(`${base}/knowledge/${assetId}`, { waitUntil: "networkidle" });
    }
    if (scenario === "denied") {
      await page.getByRole("heading", { name: "未找到或无权查看" }).waitFor();
    } else if (scenario === "failure") {
      await page.getByRole("heading", { name: "资产详情加载失败" }).waitFor();
      allowFailureRecovery = true;
      await page.getByRole("button", { name: "重新加载" }).click();
      await page.getByRole("heading", { name: "客户增长项目复盘方法论" }).waitFor();
    } else {
      await page.getByRole("heading", { name: "客户增长项目复盘方法论" }).waitFor();
    }
    if (scenario === "preview-failure") {
      await page.getByRole("button", { name: "预览原文" }).click();
      await page.getByText("在线预览服务暂未启用，可联系管理员开通后查看原文。").waitFor();
    }
    if (scenario === "governed") {
      await page.getByText("生命周期", { exact: true }).click();
      for (const [, label] of lifecycleCases) {
        await page.getByText(label, { exact: true }).waitFor();
      }
      await page.getByText("更多操作").click();
      await page.getByLabel("归档原因").fill("UI QA 归档原因");
    }

    const metrics = await page.evaluate((lifecycleCases) => {
      const root = document.documentElement;
      const rail = document.querySelector(".rail")?.getBoundingClientRect();
      const deck = document.querySelector(".deck")?.getBoundingClientRect();
      const layout = document.querySelector(".kdetail-layout")?.getBoundingClientRect();
      const main = document.querySelector(".kdetail-main-column")?.getBoundingClientRect();
      const side = document.querySelector(".kdetail-side-column")?.getBoundingClientRect();
      const text = document.body.innerText;
      return {
        overflowX: root.scrollWidth - root.clientWidth,
        shellOverlap:
          window.innerWidth >= 1000 && rail && deck ? Math.max(0, rail.right - deck.left) : 0,
        layoutWidth: layout?.width ?? 0,
        mainWidth: main?.width ?? 0,
        sideWidth: side?.width ?? 0,
        clippedActions: [
          ...document.querySelectorAll("button, a.btn-primary, a.btn-secondary"),
        ].filter((element) => element.scrollWidth > element.clientWidth + 2).length,
        moduleTitle: document.querySelector(".deck-title")?.textContent?.trim() ?? "",
        originalActionCount: [...document.querySelectorAll("button, a.btn-secondary")].filter(
          (button) => /预览原文|申请原文访问|申请审批中/.test(button.textContent ?? ""),
        ).length,
        oldSectionVisible: /处理进度|原文入口|知识卡片|高级信息/.test(text),
        fakeFeatureVisible: /下载资产|导出|分享|编辑资产|评论|AI 问答|新建项目/.test(text),
        pendingProgressLinkCount: [
          ...document.querySelectorAll('a[href="/original-access?box=mine"]'),
        ].length,
        sensitiveTextVisible:
          /storage_ref|SECRET-LIKE|trace-must-not-render|credential-must-not-render|fingerprint-must-not-render|authorization internals|weknora[_ -]?(doc|kb)[_ -]?id|fetch token|api[_ -]?key/i.test(
            text,
          ) ||
          text.includes("00000000-0000-0000-0000-000000000076") ||
          text.includes("00000000-0000-0000-0000-000000000176"),
        deniedVisible: text.includes("未找到或无权查看"),
        previewFailureVisible: text.includes("在线预览服务暂未启用"),
        deleteActionVisible: text.includes("删除资产"),
        lifecycleLabelsLocalized: lifecycleCases.every(([, label]) => text.includes(label)),
        canonicalMarkdownVisible: text.includes("Markdown 已生成"),
        waitingIndexVisible: text.includes("已入库，等待索引"),
        indexingVisible: text.includes("索引处理中"),
        publicationActionVisible: text.includes("发布到公司知识库"),
        publicationReasonVisible: text.includes("仅项目经理可提交公司发布申请"),
        internalLifecycleEventVisible: lifecycleCases.some(([eventType]) =>
          text.includes(eventType),
        ),
      };
    }, lifecycleCases);
    const screenshot = path.join(outDir, `${scenario}-${viewport.name}.png`);
    await page.screenshot({
      path: screenshot,
      fullPage: scenario === "governed",
      animations: "disabled",
    });
    results.push({
      scenario,
      viewport: viewport.name,
      detailCalls,
      lifecycleCalls,
      routedFromList: scenario !== "full" || page.url().endsWith(`/knowledge/${assetId}`),
      screenshot,
      ...metrics,
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
      (result.scenario !== "denied" &&
        (result.layoutWidth === 0 ||
          (result.viewport === "1440" && result.mainWidth <= result.sideWidth) ||
          (["1440", "1024"].includes(result.viewport) && result.sideWidth < 280))) ||
      result.clippedActions > 0 ||
      result.moduleTitle !== "知识资产库" ||
      result.oldSectionVisible ||
      result.fakeFeatureVisible ||
      result.sensitiveTextVisible ||
      !result.routedFromList ||
      (["restricted", "denied", "pending"].includes(result.scenario)
        ? result.originalActionCount !== 0
        : result.originalActionCount !== 1) ||
      (result.scenario === "pending" && result.pendingProgressLinkCount !== 1) ||
      (result.scenario === "failure" && result.detailCalls < 2) ||
      (result.scenario === "denied" && !result.deniedVisible) ||
      (result.scenario === "preview-failure" && !result.previewFailureVisible) ||
      (result.scenario !== "denied" && !result.canonicalMarkdownVisible) ||
      (result.scenario === "waiting-index" && !result.waitingIndexVisible) ||
      (result.scenario === "indexing" && !result.indexingVisible) ||
      (result.scenario === "manager-publication" && !result.publicationActionVisible) ||
      (result.scenario !== "manager-publication" &&
        !["denied", "failure"].includes(result.scenario) &&
        !result.publicationReasonVisible) ||
      (result.scenario === "governed" && result.lifecycleCalls !== 1) ||
      (result.scenario === "governed" && result.deleteActionVisible) ||
      (result.scenario === "governed" && !result.lifecycleLabelsLocalized) ||
      result.internalLifecycleEventVisible ||
      (result.scenario !== "governed" && result.lifecycleCalls !== 0),
  )
) {
  process.exit(1);
}
