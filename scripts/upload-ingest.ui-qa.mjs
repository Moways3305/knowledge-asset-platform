import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5192);
const base = `http://127.0.0.1:${port}`;
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "upload-ingest");
fs.mkdirSync(outDir, { recursive: true });

const taskId = "task-secret-77";
const projectId = "project-secret-77";
const assetId = "asset-result-77";
const scenarios = [
  "local-empty",
  "local-selected",
  "processing",
  "processing-failed",
  "confirm-ready",
  "project-submitted",
  "personal-submitted",
  "wecom-list",
  "wecom-empty",
  "wecom-failure",
  "wecom-selected",
];
const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1280", width: 1280, height: 900 },
];

const authMe = {
  user_id: "user-secret-77",
  name: "知识顾问验收用户",
  email: "identity-hidden@example.test",
  status: "active",
  company_roles: ["consultant"],
  is_business_user: true,
  can_discover_l5: false,
  project_memberships: [
    {
      project_id: projectId,
      project_name: "华东增长策略项目",
      project_role: "consultant",
      status: "active",
    },
  ],
};

const aiResult = (status) => ({
  ingest_task_id: taskId,
  status,
  suggested_title: status === "failed" ? null : "客户增长项目复盘方法论",
  suggested_one_liner: status === "failed" ? null : "归纳项目中的关键假设与复盘方法。",
  suggested_summary: status === "failed" ? null : "覆盖目标拆解、假设验证和复盘沉淀。",
  summary: status === "failed" ? null : "覆盖目标拆解、假设验证和复盘沉淀。",
  summary_status:
    status === "processing" ? "processing" : status === "failed" ? "failed" : "generated",
  generation_model_ref: "generation-ref-secret",
  suggested_key_points: status === "failed" ? [] : ["优先验证关键假设", "沉淀复盘结论"],
  suggested_tags: status === "failed" ? [] : ["增长", "复盘"],
  llm_provider: status === "failed" ? null : "external",
  llm_model: null,
  content_processing_status: status,
  desensitization_status: "unchanged",
  desensitization_counts: {},
  desensitization_message: "未发现需要处理的敏感信息",
  suggested_asset_type: "methodology",
  suggested_confidentiality_level: "L2",
  suggested_ai_access_level: "A2",
  suggested_phase_key: "年度复盘",
  confidence: status === "failed" ? null : 0.91,
  naming_compliant: true,
  naming_parsed_fields: null,
  naming_anomalies: [],
  extraction_status: status === "failed" ? "failed" : status === "processing" ? null : "extracted",
  extracted_char_count: status === "ready" ? 860 : null,
  error_type: status === "failed" ? "processing_error" : null,
  error_message: status === "failed" ? "未能生成内容建议，请重新处理" : null,
  is_possible_duplicate: false,
  duplicate_of_task_id: null,
  duplicate_of_asset_id: null,
  extracted_text_preview: null,
});

const pendingTask = {
  id: taskId,
  source: "path_a_wecom",
  status: "pending_confirmation",
  source_file_name: "企微客户访谈纪要.docx",
  target_scope: "project",
  target_project_id: projectId,
  extraction_status: "extracted",
  error_type: null,
  error_message: null,
  suggested_title: "客户访谈关键洞察",
  suggested_one_liner: "归纳客户访谈中的关键反馈。",
  naming_parsed_fields: null,
  confidence: 0.88,
  result_asset_id: null,
  created_at: "2026-07-16T08:00:00Z",
  updated_at: "2026-07-16T08:05:00Z",
};

function assertResult(result) {
  const commonFailure =
    result.overflowX > 2 ||
    result.shellOverlap > 1 ||
    result.clippedActions > 0 ||
    result.pageTitle !== "上传与入库" ||
    result.fakeFeatureVisible ||
    result.sensitiveTextVisible;
  if (commonFailure) return false;
  if (result.scenario === "local-empty") return result.emptyUploadReady;
  if (result.scenario === "local-selected") return result.selectedFileReady;
  if (result.scenario === "processing") return result.processingVisible && !result.confirmVisible;
  if (result.scenario === "processing-failed")
    return result.failureRecoverable && !result.confirmVisible;
  if (result.scenario === "confirm-ready") return result.confirmVisible;
  if (result.scenario === "project-submitted") {
    return result.projectWaiting && !result.claimsProjectComplete && result.confirmPayloadValid;
  }
  if (result.scenario === "personal-submitted") {
    return result.assetLinkVisible && result.confirmPayloadValid;
  }
  if (result.scenario === "wecom-list") return result.wecomRowVisible;
  if (result.scenario === "wecom-empty") return result.wecomEmptyVisible;
  if (result.scenario === "wecom-failure") return result.wecomRetryVisible;
  if (result.scenario === "wecom-selected") return result.confirmVisible && result.wecomCalls === 2;
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
      let uploadCalls = 0;
      let aiCalls = 0;
      let wecomCalls = 0;
      let confirmPayload = null;
      const context = await browser.newContext({ viewport });
      await context.route("**/api/v1/**", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

        if (url.pathname === "/api/v1/auth/me") return fulfill(authMe);
        if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "csrf-secret-77" });
        if (url.pathname === "/api/v1/weknora/model-options") {
          return fulfill({ items: [], default_missing: false });
        }
        if (url.pathname === "/api/v1/ingest/pending") {
          wecomCalls += 1;
          if (scenario === "wecom-failure") {
            return fulfill({ detail: { message: "待确认列表暂时不可用" } }, 503);
          }
          return fulfill({ items: scenario === "wecom-empty" ? [] : [pendingTask], total: 1 });
        }
        if (url.pathname === "/api/v1/ingest/upload") {
          uploadCalls += 1;
          return fulfill({ ingest_task_id: taskId, status: "processing", upload_url: null });
        }
        if (url.pathname === `/api/v1/ingest/${taskId}/ai-result`) {
          aiCalls += 1;
          if (scenario === "processing") return fulfill(aiResult("processing"));
          if (scenario === "processing-failed") return fulfill(aiResult("failed"));
          return fulfill(aiResult("ready"));
        }
        if (url.pathname === `/api/v1/ingest/${taskId}/confirm`) {
          confirmPayload = request.postDataJSON();
          if (scenario === "project-submitted") {
            return fulfill({
              task_id: taskId,
              status: "waiting_review",
              result_asset_id: null,
              review_id: "review-secret-77",
              index_status: null,
            });
          }
          return fulfill({
            task_id: taskId,
            status: "completed",
            result_asset_id: assetId,
            review_id: null,
            index_status: "indexed",
          });
        }
        return fulfill({ detail: { message: "UI QA route not configured" } }, 404);
      });

      const page = await context.newPage();
      await page.goto(`${base}/upload`, { waitUntil: "networkidle" });

      const isWecom = scenario.startsWith("wecom-");
      if (isWecom) {
        await page.getByRole("button", { name: "企微微盘待确认" }).click();
        if (scenario === "wecom-list" || scenario === "wecom-selected") {
          await page.getByRole("button", { name: "企微客户访谈纪要.docx" }).waitFor();
        } else if (scenario === "wecom-empty") {
          await page.getByText("暂无待确认资料").waitFor();
        } else {
          await page.getByRole("button", { name: "重试" }).waitFor();
        }
        if (scenario === "wecom-selected") {
          await page.getByRole("button", { name: "企微客户访谈纪要.docx" }).click();
          await page.getByRole("heading", { name: "内容建议预览" }).waitFor();
        }
      } else if (scenario !== "local-empty") {
        await page.locator('input[type="file"]').setInputFiles({
          name: "客户增长复盘.md",
          mimeType: "text/markdown",
          buffer: Buffer.from("# 客户增长复盘\n安全验收内容"),
        });
        if (scenario !== "local-selected") {
          await page.getByRole("button", { name: "开始处理" }).click();
          if (scenario === "processing") {
            await page.getByText("处理中…", { exact: true }).waitFor();
          } else if (scenario === "processing-failed") {
            await page.getByRole("button", { name: "重新处理" }).waitFor();
          } else {
            await page.getByRole("heading", { name: "内容建议预览" }).waitFor();
          }
        }
      }

      if (scenario === "project-submitted") {
        await page.getByLabel("目标知识库").selectOption("project");
        await page.getByRole("button", { name: "确认入库" }).click();
        await page.getByRole("heading", { name: "已提交，等待项目经理确认" }).waitFor();
      }
      if (scenario === "personal-submitted") {
        await page.getByRole("button", { name: "确认入库" }).click();
        await page.getByRole("link", { name: /查看资产/ }).waitFor();
      }

      const metrics = await page.evaluate(() => {
        const root = document.documentElement;
        const rail = document.querySelector(".rail")?.getBoundingClientRect();
        const deck = document.querySelector(".deck")?.getBoundingClientRect();
        const text = document.body.innerText;
        return {
          overflowX: root.scrollWidth - root.clientWidth,
          shellOverlap: rail && deck ? Math.max(0, rail.right - deck.left) : 1,
          clippedActions: [...document.querySelectorAll("button, a")].filter(
            (element) => element.scrollWidth > element.clientWidth + 2,
          ).length,
          pageTitle: document.querySelector(".product-page-header h2")?.textContent?.trim() ?? "",
          emptyUploadReady:
            text.includes("拖放文件到这里") &&
            [...document.querySelectorAll("button")].filter(
              (button) => button.textContent?.trim() === "选择文件",
            ).length === 1,
          selectedFileReady: text.includes("客户增长复盘.md") && text.includes("开始处理"),
          processingVisible: text.includes("处理中…"),
          failureRecoverable: text.includes("处理失败") && text.includes("重新处理"),
          confirmVisible: text.includes("内容建议预览") && text.includes("确认入库"),
          projectWaiting: text.includes("已提交，等待项目经理确认"),
          claimsProjectComplete: text.includes("已进入项目知识库"),
          assetLinkVisible: text.includes("查看资产"),
          wecomRowVisible: text.includes("企微客户访谈纪要.docx"),
          wecomEmptyVisible: text.includes("暂无待确认资料"),
          wecomRetryVisible: text.includes("待确认列表暂时不可用") && text.includes("重试"),
          fakeFeatureVisible:
            /保存草稿|Import from URL|从 URL|上传速度|剩余时间|AI 健康度|最近活动|手动扫描|扫描配置/.test(
              text,
            ),
          sensitiveTextVisible:
            /storage_ref|SECRET-LIKE|task-secret-77|project-secret-77|user-secret-77|review-secret-77|generation-ref-secret|csrf-secret-77|identity-hidden|api[_ -]?key|presigned|weknora/i.test(
              text,
            ),
        };
      });

      const confirmPayloadValid = confirmPayload
        ? confirmPayload.title === "客户增长项目复盘方法论" &&
          confirmPayload.target_zone === "material" &&
          confirmPayload.asset_type === "methodology" &&
          Array.isArray(confirmPayload.tags) &&
          !("embedding_model_id" in confirmPayload) &&
          !("rerank_model_id" in confirmPayload) &&
          (scenario !== "project-submitted" ||
            (confirmPayload.target_scope === "project" &&
              confirmPayload.target_project_id === projectId))
        : false;
      const screenshot = path.join(outDir, `${scenario}-${viewport.name}.png`);
      await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
      const result = {
        scenario,
        viewport: viewport.name,
        port,
        uploadCalls,
        aiCalls,
        wecomCalls,
        confirmPayloadValid,
        screenshot,
        ...metrics,
      };
      results.push({ ...result, passed: assertResult(result) });
      await context.close();
    }
  }
} finally {
  await browser?.close();
  await previewServer?.close();
}

fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify({ port, outDir, scenarios, viewports, results }, null, 2));

if (
  results.length !== scenarios.length * viewports.length ||
  results.some((item) => !assertResult(item))
) {
  process.exit(1);
}
