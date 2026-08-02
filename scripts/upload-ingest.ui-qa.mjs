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
const uploadSessionId = "upload-session-secret-77";
const longPendingFileName =
  "2026年度华东区域重点客户战略经营计划执行复盘与下一阶段增长行动方案最终评审修订版_v12.pptx";
const longPendingSubject =
  "华东区域重点客户战略经营计划执行复盘与下一阶段增长行动方案及关键管理举措";
const scenarios = [
  "local-empty",
  "local-queue",
  "local-degraded",
  "local-upload-failure-retry",
  "batch-naming-ready",
  "confirm-ready",
  "project-naming-ready",
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
  { name: "1920", width: 1920, height: 1080 },
];

const authMe = {
  user_id: "user-secret-77",
  name: "知识顾问验收用户",
  email: "identity-hidden@example.test",
  status: "active",
  company_roles: ["consultant"],
  active_company_role: "consultant",
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

const localPendingTask = {
  ...pendingTask,
  source: "path_b_upload",
  source_file_name: longPendingFileName,
  suggested_title: longPendingSubject,
  target_scope: null,
  target_project_id: null,
  can_batch_confirm: true,
  can_batch_reject: true,
};

const batchNamingFields = {
  primary_category: "客户项目",
  secondary_category: "交付成果",
  topic: "客户增长项目复盘方法论",
  subject_or_client: "",
  date: "20210307",
  version: "V1",
  confidentiality_level: "L2",
  ai_access_level: "A2",
  normalized_title: "",
  inferred_fields: ["secondary_category"],
  missing_fields: [],
  source_file_name: longPendingFileName,
  original_naming_compliant: false,
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
  if (result.scenario === "local-queue")
    return (
      result.compactCompletionVisible &&
      result.localPendingRefreshed &&
      result.longPendingLayoutValid &&
      result.pendingScrollContainerValid &&
      Boolean(result.pendingScreenshot)
    );
  if (result.scenario === "local-degraded") {
    // A recovered awaiting-confirmation session is authoritative.  Historical
    // parse metadata must not leave a stale failure visible after completion.
    return !result.degradedWarningVisible;
  }
  if (result.scenario === "local-upload-failure-retry")
    return result.failureRetried && result.localPendingRefreshed;
  if (result.scenario === "batch-naming-ready") {
    return result.batchNamingLayoutValid;
  }
  if (result.scenario === "confirm-ready") return result.confirmVisible;
  if (result.scenario === "project-naming-ready") {
    return result.confirmVisible && result.projectNamingLayoutValid;
  }
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
      let localPendingCalls = 0;
      let localPendingAvailable = false;
      let confirmPayload = null;
      const uploadSession = (state) => {
        const itemError =
          state === "failed"
            ? "上传失败"
            : scenario === "local-degraded"
              ? "内容建议暂不可用，请人工核对后继续"
              : null;
        const files =
          scenario === "local-queue" || scenario === "batch-naming-ready"
            ? [
                ["upload-item-1", "客户增长复盘.md"],
                ["upload-item-2", "客户访谈纪要.txt"],
              ]
            : [["upload-item-1", "客户增长复盘.md"]];
        return {
          id: uploadSessionId,
          status: state === "failed" ? "active" : "completed",
          total_files: files.length,
          completed_files: state === "awaiting_confirmation" ? files.length : 0,
          processing_files: 0,
          waiting_files: 0,
          failed_files: state === "failed" ? files.length : 0,
          current_batch_number: null,
          total_batches: 1,
          created_at: "2026-07-16T08:00:00Z",
          updated_at: "2026-07-16T08:05:00Z",
          items: files.map(([id, fileName], index) => ({
            id,
            ordinal: index + 1,
            batch_number: 1,
            file_name: fileName,
            file_size: 42,
            file_type: fileName.endsWith(".txt") ? "TXT" : "MD",
            status: state,
            error_code: state === "failed" ? "upload_failed" : null,
            error_message: itemError,
            same_name_warning: false,
            retryable: state === "failed",
          })),
        };
      };
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
        if (url.pathname === "/api/v1/naming-options") {
          if (scenario === "project-naming-ready" || scenario === "batch-naming-ready") {
            return fulfill({
              required: true,
              rule_version: 2,
              categories: [
                {
                  id: "category-foundation",
                  primary: "项目资料",
                  secondary: "项目基础信息",
                  prefix: "项目资料-项目基础信息",
                  default_confidentiality: "L2",
                },
                {
                  id: "category-deliverable",
                  primary: "项目资料",
                  secondary: "交付成果",
                  prefix: "项目资料-交付成果",
                  default_confidentiality: "L2",
                },
              ],
              default_confidentiality: "L2",
              message: null,
            });
          }
          return fulfill({
            required: false,
            rule_version: null,
            categories: [],
            default_confidentiality: null,
            message: "命名规则尚未发布，不强制规范命名",
          });
        }
        if (url.pathname === "/api/v1/ingest/pending") {
          wecomCalls += 1;
          if (scenario === "wecom-failure") {
            return fulfill({ detail: { message: "待确认列表暂时不可用" } }, 503);
          }
          const local = url.searchParams.get("source") === "path_b_upload";
          if (local) localPendingCalls += 1;
          const items = local
            ? localPendingAvailable
              ? scenario === "batch-naming-ready"
                ? [
                    { ...localPendingTask, naming_parsed_fields: batchNamingFields },
                    {
                      ...localPendingTask,
                      id: "task-safe-78",
                      source_file_name: "年度经营计划.md",
                      suggested_title: "年度经营计划",
                      naming_parsed_fields: {
                        ...batchNamingFields,
                        topic: "年度经营计划",
                        date: "20210116",
                        source_file_name: "年度经营计划.md",
                      },
                    },
                  ]
                : [localPendingTask]
              : []
            : scenario === "wecom-empty"
              ? []
              : [pendingTask];
          return fulfill({ items, total: items.length });
        }
        if (url.pathname === "/api/v1/ingest/upload-sessions" && request.method() === "GET") {
          return fulfill({ items: [], total: 0 });
        }
        if (url.pathname === "/api/v1/ingest/upload-sessions" && request.method() === "POST") {
          uploadCalls += 1;
          if (scenario === "local-upload-failure-retry") return fulfill(uploadSession("failed"));
          localPendingAvailable = true;
          return fulfill(uploadSession("awaiting_confirmation"));
        }
        if (
          url.pathname ===
            `/api/v1/ingest/upload-sessions/${uploadSessionId}/items/upload-item-1/retry` &&
          request.method() === "POST"
        ) {
          uploadCalls += 1;
          localPendingAvailable = true;
          return fulfill(uploadSession("awaiting_confirmation"));
        }
        if (url.pathname === "/api/v1/ingest/upload") {
          uploadCalls += 1;
          if (scenario === "local-upload-failure-retry" && uploadCalls === 1) {
            return fulfill({ detail: { message: "上传暂时失败" } }, 503);
          }
          localPendingAvailable = true;
          return fulfill({ ingest_task_id: taskId, status: "processing", upload_url: null });
        }
        if (url.pathname === `/api/v1/ingest/${taskId}/ai-result`) {
          aiCalls += 1;
          if (scenario === "processing") return fulfill(aiResult("processing"));
          if (scenario === "processing-failed") return fulfill(aiResult("failed"));
          const result = aiResult("ready");
          if (scenario === "project-naming-ready") {
            result.naming_parsed_fields = {
              primary_category: "客户项目",
              secondary_category: "交付成果",
              topic: "客户增长项目复盘方法论",
              subject_or_client: "",
              date: "20210307",
              version: "V1",
              confidentiality_level: "L2",
              ai_access_level: "A2",
              normalized_title: "",
              inferred_fields: ["secondary_category"],
              missing_fields: [],
              source_file_name: "客户增长复盘.md",
              original_naming_compliant: false,
            };
          }
          return fulfill(result);
        }
        if (url.pathname === `/api/v1/ingest/${taskId}/naming-preview`) {
          return fulfill({
            required: true,
            canonical_name: "【PROJECT-2021-交付成果】客户增长项目复盘方法论_20210307_V1_L2.md",
            rule_version: 2,
            fields: { subject: "客户增长项目复盘方法论" },
            notices: [],
            message: null,
          });
        }
        if (url.pathname === `/api/v1/ingest/${taskId}/status`) {
          if (scenario === "local-degraded") {
            return fulfill({
              task_id: taskId,
              stage: "degraded_complete",
              status: "degraded",
              updated_at: null,
              retryable: false,
              next_action: {
                key: "review_and_confirm",
                route_key: "upload_task",
                enabled: true,
              },
              error: {
                code: "content_generation_unavailable",
                message: "内容建议暂不可用，请人工核对后继续",
                recovery_hint: "review_and_confirm",
              },
              result_asset_id: null,
              review_id: null,
            });
          }
          return fulfill({
            task_id: taskId,
            stage: "awaiting_confirmation",
            status: "action_required",
            updated_at: null,
            retryable: false,
            next_action: null,
            error: null,
            result_asset_id: null,
            review_id: null,
          });
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
        const localFiles = [
          {
            name: "客户增长复盘.md",
            mimeType: "text/markdown",
            buffer: Buffer.from("# 客户增长复盘\n安全验收内容"),
          },
        ];
        if (
          scenario === "local-queue" ||
          scenario === "local-upload-failure-retry" ||
          scenario === "batch-naming-ready"
        ) {
          localFiles.push({
            name: "客户访谈纪要.txt",
            mimeType: "text/plain",
            buffer: Buffer.from("安全验收内容"),
          });
        }
        await page.locator('input[type="file"]').first().setInputFiles(localFiles);

        if (scenario === "local-upload-failure-retry") {
          await page.getByText("上传失败", { exact: true }).first().waitFor();
          await page.getByRole("button", { name: "重试" }).click();
          await page.getByText("上传失败", { exact: true }).first().waitFor({ state: "detached" });
        }
        await page.getByText("待确认入库", { exact: true }).first().waitFor();
        if (
          scenario === "local-queue" ||
          scenario === "local-upload-failure-retry" ||
          scenario === "batch-naming-ready"
        ) {
          const localPendingSection = page.locator(
            'section[aria-labelledby="local-pending-title"]',
          );
          await localPendingSection.getByRole("button", { name: "刷新" }).click();
          await localPendingSection.locator("tbody tr").first().waitFor();
        }
        if (!scenario.startsWith("local-") && scenario !== "batch-naming-ready") {
          await page.getByRole("button", { name: longPendingFileName }).click();
          await page.getByRole("heading", { name: "内容建议预览" }).waitFor();
        }
      }

      if (scenario === "batch-naming-ready") {
        await page.getByRole("checkbox", { name: "全选当前可处理的待确认项" }).check();
        await page.getByRole("button", { name: "批量确认入库（2）" }).click();
        await page.getByRole("combobox", { name: "批量入库目标知识库" }).selectOption("project");
        await page.getByRole("combobox", { name: "批量入库目标项目" }).selectOption(projectId);
        await page.getByRole("button", { name: "下一步：核对命名" }).click();
        await page.getByRole("heading", { name: "逐条核对 2 项规范命名" }).waitFor();
      }
      if (scenario === "project-submitted") {
        await page.locator("#upload77-target-library").selectOption("project");
        await page.locator("#upload77-target-project").selectOption(projectId);
        await page.getByRole("button", { name: "确认入库" }).click();
        await page.getByRole("heading", { name: "已提交，等待项目经理确认" }).waitFor();
      }
      if (scenario === "project-naming-ready") {
        await page.locator("#upload77-target-library").selectOption("project");
        await page.locator("#upload77-target-project").selectOption(projectId);
        await page.locator("#upload77-naming-category").waitFor();
        await page.waitForFunction(
          () =>
            document.querySelector("#upload77-naming-category")?.value === "category-deliverable",
        );
        await page.getByText(/【PROJECT-2021-交付成果】/).waitFor();
      }
      if (scenario === "personal-submitted") {
        await page.locator("#upload77-target-library").selectOption("personal");
        await page.getByRole("button", { name: "确认入库" }).click();
        await page.getByRole("link", { name: /查看资产/ }).waitFor();
      }

      const metrics = await page.evaluate(
        ({ longPendingFileName, longPendingSubject }) => {
          const root = document.documentElement;
          const rail = document.querySelector(".rail")?.getBoundingClientRect();
          const deck = document.querySelector(".deck")?.getBoundingClientRect();
          const text = document.body.innerText;
          const pendingTable = document.querySelector(
            'section[aria-labelledby="local-pending-title"] .upload77-pending-table',
          );
          const pendingWrap = pendingTable?.closest(".upload77-table-wrap");
          const fileButton = pendingTable?.querySelector(".upload77-task-select");
          const subject = pendingTable?.querySelector(".upload77-pending-truncate");
          const formColumn = document.querySelector(".upload77-form-column");
          const titleField = document.querySelector("#upload77-edit-title")?.closest("label");
          const oneLinerField = document
            .querySelector("#upload77-edit-one-liner")
            ?.closest("label");
          const summaryField = document.querySelector("#upload77-edit-summary")?.closest("label");
          const batchRows = [...document.querySelectorAll(".upload77-batch-naming-row")];
          const batchRowAligned = (row) => {
            const controls = [
              row.querySelector('input[aria-label$="主题"]'),
              row.querySelector('select[aria-label$="目录类别"]'),
              row.querySelector('input[aria-label$="文件形成日期"]'),
              row.querySelector('input[aria-label$="版本"]'),
              row.querySelector('select[aria-label$="密级"]'),
            ].filter(Boolean);
            const tops = controls.map((control) => control.getBoundingClientRect().top);
            const labelsAligned = [
              ...row.querySelectorAll(".upload77-batch-naming-grid label"),
            ].every((label) => getComputedStyle(label).alignContent === "start");
            return (
              controls.length === 5 &&
              Math.max(...tops) - Math.min(...tops) <= 2 &&
              labelsAligned &&
              row.querySelector('select[aria-label$="目录类别"]')?.value === "category-deliverable"
            );
          };
          const verticalGap = (before, after) => {
            if (!before || !after) return Number.POSITIVE_INFINITY;
            return after.getBoundingClientRect().top - before.getBoundingClientRect().bottom;
          };
          const pendingOverflowX = pendingWrap ? getComputedStyle(pendingWrap).overflowX : "";
          const pendingRequiresHorizontalScroll = window.innerWidth <= 1280;
          let pendingAcceptsHorizontalScroll = !pendingRequiresHorizontalScroll;
          if (pendingWrap && pendingRequiresHorizontalScroll) {
            const originalScrollLeft = pendingWrap.scrollLeft;
            pendingWrap.scrollLeft = 1;
            pendingAcceptsHorizontalScroll = pendingWrap.scrollLeft > originalScrollLeft;
            pendingWrap.scrollLeft = originalScrollLeft;
          }
          const hasTwoLineClamp = (element) => {
            if (!element) return false;
            const style = getComputedStyle(element);
            const lineHeight = Number.parseFloat(style.lineHeight);
            return (
              style.webkitLineClamp === "2" &&
              Number.isFinite(lineHeight) &&
              element.getBoundingClientRect().height <= lineHeight * 2 + 2
            );
          };
          return {
            overflowX: root.scrollWidth - root.clientWidth,
            shellOverlap: rail && deck ? Math.max(0, rail.right - deck.left) : 1,
            clippedActions: [...document.querySelectorAll("button, a")].filter(
              (element) =>
                !element.classList.contains("upload77-task-select") &&
                element.scrollWidth > element.clientWidth + 2,
            ).length,
            pageTitle: document.querySelector(".product-page-header h2")?.textContent?.trim() ?? "",
            emptyUploadReady:
              text.includes("拖放文件到这里") &&
              [...document.querySelectorAll("button")].filter(
                (button) => button.textContent?.trim() === "选择文件",
              ).length === 1,
            queueOrderValid:
              text.indexOf("客户增长复盘.md") >= 0 &&
              text.indexOf("客户访谈纪要.txt") > text.indexOf("客户增长复盘.md"),
            compactCompletionVisible:
              Boolean(document.querySelector(".upload77-upload-complete")) &&
              !document.querySelector("#local-upload-queue-title"),
            localPendingVisible: text.includes("待确认入库") && text.includes(longPendingFileName),
            pendingWrapClientWidth: pendingWrap?.clientWidth ?? 0,
            pendingWrapScrollWidth: pendingWrap?.scrollWidth ?? 0,
            pendingOverflowX,
            pendingScrollContainerValid:
              Boolean(pendingTable && pendingWrap) &&
              (pendingOverflowX === "auto" || pendingOverflowX === "scroll") &&
              pendingWrap.scrollWidth >= pendingTable.scrollWidth &&
              (!pendingRequiresHorizontalScroll ||
                (pendingWrap.scrollWidth > pendingWrap.clientWidth + 2 &&
                  pendingAcceptsHorizontalScroll)),
            longPendingLayoutValid:
              Boolean(pendingTable && pendingWrap && fileButton && subject) &&
              pendingTable.querySelectorAll("colgroup col").length === 7 &&
              Number.parseFloat(getComputedStyle(pendingTable).minWidth) >= 1120 &&
              pendingWrap.scrollWidth >= pendingTable.scrollWidth &&
              fileButton.getAttribute("title") === longPendingFileName &&
              subject.getAttribute("title") === longPendingSubject &&
              hasTwoLineClamp(fileButton) &&
              hasTwoLineClamp(subject),
            projectNamingLayoutValid:
              Boolean(formColumn && titleField && oneLinerField && summaryField) &&
              getComputedStyle(formColumn).alignContent === "start" &&
              verticalGap(titleField, oneLinerField) <= 24 &&
              verticalGap(oneLinerField, summaryField) <= 24 &&
              document.querySelector("#upload77-naming-category")?.value === "category-deliverable",
            batchNamingLayoutValid:
              batchRows.length === 2 && batchRows.every((row) => batchRowAligned(row)),
            uploadFailureVisible: text.includes("上传失败"),
            degradedWarningVisible: text.includes("内容建议暂不可用，请人工核对后继续"),
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
        },
        { longPendingFileName, longPendingSubject },
      );

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
      let pendingScreenshot = null;
      if (scenario === "local-queue") {
        const pendingSection = page.locator('section[aria-labelledby="local-pending-title"]');
        await pendingSection.scrollIntoViewIfNeeded();
        pendingScreenshot = path.join(outDir, `${scenario}-pending-${viewport.name}.png`);
        await pendingSection.screenshot({
          path: pendingScreenshot,
          animations: "disabled",
        });
      }
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
        pendingScreenshot,
        ...metrics,
        queueOrderValid: metrics.queueOrderValid,
        localPendingRefreshed:
          localPendingCalls >= 2 && localPendingAvailable && metrics.localPendingVisible,
        failureRetried: scenario === "local-upload-failure-retry" && !metrics.uploadFailureVisible,
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
