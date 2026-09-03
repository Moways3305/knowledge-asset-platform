import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5192);
const externalBase = process.env.UI_QA_BASE?.replace(/\/$/, "") || null;
const base = externalBase || `http://127.0.0.1:${port}`;
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
  "canonical-processing",
  "local-queue",
  "local-degraded",
  "local-upload-failure-retry",
  "batch-naming-ready",
  "batch-personal-ready",
  "batch-company-directory-ready",
  "confirm-ready",
  "project-naming-ready",
  "project-submitted",
  "personal-submitted",
  "wecom-list",
  "wecom-empty",
  "wecom-failure",
  "wecom-selected",
];
const scenarioFilter = new Set(
  (process.env.UI_QA_SCENARIOS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean),
);
const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1024", width: 1024, height: 800 },
  { name: "768", width: 768, height: 900 },
  { name: "390", width: 390, height: 844 },
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
  topic: "客户增长项目复盘方法论",
  subject_or_client: "",
  date: "20210307",
  version: "V1",
  confidentiality_level: "L2",
  normalized_title: "",
  inferred_fields: [],
  missing_fields: [],
  source_file_name: longPendingFileName,
  original_naming_compliant: false,
};

function assertResult(result) {
  const commonFailure =
    result.overflowX > 2 ||
    result.shellOverlap > 1 ||
    result.clippedActions > 0 ||
    result.pageTitle !== "上传文件" ||
    result.fakeFeatureVisible ||
    result.sensitiveTextVisible ||
    !result.retiredInputsAbsent ||
    result.classificationCalls > 0;
  if (commonFailure) return false;
  if (result.scenario === "local-empty") return result.emptyUploadReady;
  if (result.scenario === "canonical-processing")
    return result.canonicalGenerating && Boolean(result.canonicalScreenshot);
  if (result.scenario === "local-queue")
    return (
      result.queueOrderValid &&
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
  if (result.scenario === "batch-personal-ready") {
    return (
      result.personalBatchReady &&
      result.personalBatchPayloadValid &&
      result.personalBatchReviewLayoutValid &&
      Boolean(result.personalBatchScreenshot) &&
      result.classificationCalls === 0 &&
      result.batchNamingPreviewCalls === 0
    );
  }
  if (result.scenario === "batch-company-directory-ready") {
    return (
      result.companyDirectoryPayloadValid &&
      result.companyDirectoryPreviewed &&
      Boolean(result.companyDirectoryScreenshot) &&
      result.classificationCalls === 0
    );
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
  if (!externalBase) {
    await build({ logLevel: "warn" });
    previewServer = await preview({
      logLevel: "warn",
      preview: { host: "127.0.0.1", port, strictPort: true },
    });
  }
  browser = await chromium.launch({ args: ["--disable-gpu"] });

  for (const scenario of scenarios) {
    if (scenarioFilter.size > 0 && !scenarioFilter.has(scenario)) continue;
    for (const viewport of viewports) {
      let uploadCalls = 0;
      let aiCalls = 0;
      let wecomCalls = 0;
      let localPendingCalls = 0;
      let localPendingAvailable = false;
      let confirmPayload = null;
      let bulkConfirmPayload = null;
      const retiredBusinessRequests = [];
      let batchNamingPreviewCalls = 0;
      let companyDirectoryPreviewed = false;
      let companyDirectoryScreenshot = null;
      let personalBatchReviewLayoutValid = false;
      let personalBatchScreenshot = null;
      const uploadSession = (state) => {
        const itemError =
          state === "failed"
            ? "上传失败"
            : scenario === "local-degraded"
              ? "内容建议暂不可用，请人工核对后继续"
              : null;
        const files =
          scenario === "local-queue" ||
          scenario === "batch-naming-ready" ||
          scenario === "batch-personal-ready" ||
          scenario === "batch-company-directory-ready"
            ? [
                ["upload-item-1", "客户增长复盘.md"],
                ["upload-item-2", "客户访谈纪要.txt"],
              ]
            : [["upload-item-1", "客户增长复盘.md"]];
        return {
          id: uploadSessionId,
          status: state === "awaiting_confirmation" ? "completed" : "active",
          upload_completed: state === "awaiting_confirmation",
          total_files: files.length,
          completed_files: state === "awaiting_confirmation" ? files.length : 0,
          processing_files: state === "processing" ? files.length : 0,
          waiting_files: 0,
          failed_files: state === "failed" ? files.length : 0,
          current_batch_number: null,
          total_batches: 1,
          uploaded_files: state === "waiting_upload" || state === "failed" ? 0 : files.length,
          uploaded_batches: state === "waiting_upload" ? 0 : 1,
          created_at: "2026-07-16T08:00:00Z",
          updated_at: "2026-07-16T08:05:00Z",
          items: files.map(([id, fileName], index) => ({
            id,
            ordinal: index,
            batch_number: 1,
            transport_batch_number: 1,
            file_name: fileName,
            file_size: Buffer.byteLength(
              fileName.endsWith(".txt") ? "安全验收内容" : "# 客户增长复盘\n安全验收内容",
            ),
            file_type: fileName.endsWith(".txt") ? "TXT" : "MD",
            status: state,
            ingest_task_id: state === "waiting_upload" || state === "failed" ? null : taskId,
            processing_stage:
              state === "processing" && scenario === "canonical-processing"
                ? "canonical_markdown_generation"
                : null,
            error_code: state === "failed" ? "upload_failed" : null,
            error_message: itemError,
            same_name_warning: false,
            retryable: state === "failed",
            bytes_available: state !== "waiting_upload" && state !== "failed",
          })),
        };
      };
      const context = await browser.newContext({ viewport });
      await context.route("**/api/v1/**", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

        if (url.pathname === "/api/v1/auth/me") {
          return fulfill(
            scenario === "batch-company-directory-ready"
              ? {
                  ...authMe,
                  company_roles: ["consulting_director"],
                  active_company_role: "consulting_director",
                  can_discover_l5: true,
                }
              : authMe,
          );
        }
        if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "csrf-secret-77" });
        if (url.pathname === "/api/v1/weknora/model-options") {
          return fulfill({ items: [], default_missing: false });
        }
        if (url.pathname === "/api/v1/naming-options") {
          if (scenario === "batch-company-directory-ready") {
            return fulfill({
              required: true,
              rule_version: 5,
              directories: [
                {
                  directory_key: "company.methodology",
                  scope: "company",
                  display_name: "02 方法论",
                  description: "模型、工具与可复用方法",
                  naming_code: "方法论",
                  default_confidentiality: "L3",
                  sort_order: 30,
                  enabled: true,
                },
              ],
              default_confidentiality: "L3",
              message: null,
            });
          }
          if (scenario === "project-naming-ready" || scenario === "batch-naming-ready") {
            return fulfill({
              required: true,
              rule_version: 2,
              directories: [
                {
                  directory_key: "project.basic_information",
                  scope: "project",
                  display_name: "项目基础信息",
                  description: null,
                  naming_code: "基础信息",
                  default_confidentiality: "L2",
                  sort_order: 10,
                  enabled: true,
                },
                {
                  directory_key: "project.deliverables",
                  scope: "project",
                  display_name: "交付成果",
                  description: null,
                  naming_code: "交付成果",
                  default_confidentiality: "L3",
                  sort_order: 30,
                  enabled: true,
                },
              ],
              default_confidentiality: "L2",
              message: null,
            });
          }
          const namingScope = url.searchParams.get("scope");
          return fulfill({
            required: false,
            rule_version: null,
            directories:
              namingScope === "project"
                ? [
                    {
                      directory_key: "project.basic_information",
                      scope: "project",
                      display_name: "项目基础信息",
                      description: null,
                      sort_order: 10,
                      enabled: true,
                    },
                  ]
                : [
                    {
                      directory_key: "personal.learning_notes",
                      scope: "personal",
                      display_name: "个人学习笔记",
                      description: null,
                      sort_order: 10,
                      enabled: true,
                    },
                    {
                      directory_key: "personal.project_materials",
                      scope: "personal",
                      display_name: "个人项目资料",
                      description: null,
                      sort_order: 20,
                      enabled: true,
                    },
                    {
                      directory_key: "personal.pending",
                      scope: "personal",
                      display_name: "待处理",
                      description: null,
                      sort_order: 40,
                      enabled: true,
                    },
                  ],
            default_confidentiality: null,
            message: "命名规则尚未发布，不强制规范命名",
          });
        }
        if (url.pathname === "/api/v1/ingest/bulk-naming-preview") {
          batchNamingPreviewCalls += 1;
          if (scenario === "batch-company-directory-ready") {
            const body = request.postDataJSON();
            return fulfill({
              items: (body.items || []).map((item) => {
                const directoryKey = item.naming?.directory_key;
                companyDirectoryPreviewed = directoryKey === "company.methodology";
                return {
                  task_id: item.task_id,
                  submittable: true,
                  canonical_name: `【公司资产-方法论】${longPendingSubject}_20210307_V1_L3.md`,
                  rule_version: 5,
                  fields: {
                    ...item.naming,
                    directory_key: directoryKey,
                    directory_rule_version: 5,
                  },
                  notices: [],
                  error_code: null,
                  message: null,
                };
              }),
            });
          }
          return fulfill({ items: [] });
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
              ? scenario === "batch-naming-ready" || scenario === "batch-personal-ready"
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
                : scenario === "batch-company-directory-ready"
                  ? [{ ...localPendingTask, naming_parsed_fields: batchNamingFields }]
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
          if (scenario === "canonical-processing") return fulfill(uploadSession("processing"));
          localPendingAvailable = true;
          return fulfill(uploadSession("awaiting_confirmation"));
        }
        if (url.pathname === "/api/v1/ingest/upload-sessions/init" && request.method() === "POST") {
          uploadCalls += 1;
          return fulfill(uploadSession("waiting_upload"));
        }
        if (
          url.pathname === `/api/v1/ingest/upload-sessions/${uploadSessionId}/batches` &&
          request.method() === "POST"
        ) {
          uploadCalls += 1;
          if (scenario === "local-upload-failure-retry") {
            return fulfill({ detail: { message: "上传暂时失败" } }, 503);
          }
          if (scenario === "canonical-processing") return fulfill(uploadSession("processing"));
          localPendingAvailable = true;
          return fulfill(uploadSession("awaiting_confirmation"));
        }
        if (
          url.pathname === `/api/v1/ingest/upload-sessions/${uploadSessionId}/transport-failure` &&
          request.method() === "POST"
        ) {
          return fulfill(uploadSession("failed"));
        }
        if (
          url.pathname ===
            `/api/v1/ingest/upload-sessions/${uploadSessionId}/items/upload-item-1/bytes` &&
          request.method() === "POST"
        ) {
          uploadCalls += 1;
          return fulfill(uploadSession("awaiting_confirmation"));
        }
        if (
          url.pathname === `/api/v1/ingest/upload-sessions/${uploadSessionId}/complete` &&
          request.method() === "POST"
        ) {
          if (scenario === "canonical-processing") return fulfill(uploadSession("processing"));
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
          if (scenario === "project-naming-ready")
            result.naming_parsed_fields = { ...batchNamingFields };
          return fulfill(result);
        }
        if (url.pathname === "/api/v1/ingest/task-safe-78/ai-result") {
          aiCalls += 1;
          return fulfill({
            ...aiResult("ready"),
            ingest_task_id: "task-safe-78",
            suggested_title: "年度经营计划",
          });
        }
        if (
          url.pathname === `/api/v1/ingest/${taskId}/naming-preview` ||
          url.pathname === "/api/v1/ingest/task-safe-78/naming-preview"
        ) {
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
          if (scenario === "canonical-processing") {
            return fulfill({
              task_id: taskId,
              stage: "canonical_markdown_generation",
              status: "processing",
              updated_at: null,
              retryable: false,
              next_action: null,
              error: null,
              result_asset_id: null,
              review_id: null,
            });
          }
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
        if (url.pathname === "/api/v1/ingest/bulk-confirm") {
          bulkConfirmPayload = request.postDataJSON();
          return fulfill({
            operation_id: "bulk-personal-safe",
            status: "completed",
            execution_mode: "synchronous",
            submitted: 2,
            succeeded: 2,
            skipped: 0,
            failed: 0,
            items: (bulkConfirmPayload.items || []).map((item) => ({
              item_id: item.task_id,
              status: "succeeded",
              reason_code: null,
              message: null,
            })),
          });
        }
        return fulfill({ detail: { message: "UI QA route not configured" } }, 404);
      });

      const page = await context.newPage();
      page.on("request", (request) => {
        if (/bulk-category-classification|category_id|asset_type/.test(request.url()))
          retiredBusinessRequests.push(request.url());
      });
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
          scenario === "batch-naming-ready" ||
          scenario === "batch-personal-ready" ||
          scenario === "batch-company-directory-ready"
        ) {
          localFiles.push({
            name: "客户访谈纪要.txt",
            mimeType: "text/plain",
            buffer: Buffer.from("安全验收内容"),
          });
        }
        await page.locator('input[type="file"]').first().setInputFiles(localFiles);

        if (scenario === "canonical-processing") {
          await page.getByText("正在生成 Markdown", { exact: true }).waitFor();
        } else if (scenario === "local-upload-failure-retry") {
          await page.getByText("上传失败", { exact: true }).first().waitFor();
          await page.getByRole("button", { name: "重试处理" }).first().click();
          await page.getByText("上传失败", { exact: true }).first().waitFor({ state: "detached" });
        }
        if (scenario !== "canonical-processing") {
          await page.getByText("待确认入库", { exact: true }).first().waitFor();
          if (
            scenario === "local-queue" ||
            scenario === "local-upload-failure-retry" ||
            scenario === "batch-naming-ready" ||
            scenario === "batch-personal-ready" ||
            scenario === "batch-company-directory-ready"
          ) {
            const localPendingSection = page.locator(
              'section[aria-labelledby="local-pending-title"]',
            );
            await localPendingSection.getByRole("button", { name: "刷新" }).click();
            await localPendingSection.locator("tbody tr").first().waitFor();
          }
          if (
            !scenario.startsWith("local-") &&
            scenario !== "batch-naming-ready" &&
            scenario !== "batch-personal-ready" &&
            scenario !== "batch-company-directory-ready"
          ) {
            await page.getByRole("button", { name: longPendingFileName }).click();
            await page.getByRole("heading", { name: "内容建议预览" }).waitFor();
          }
        }
      }

      if (scenario === "batch-naming-ready") {
        await page.getByRole("checkbox", { name: "全选当前可处理的待确认项" }).check();
        await page.getByRole("button", { name: "批量确认入库（2）" }).click();
        await page.getByRole("combobox", { name: "批量入库目标知识库" }).selectOption("project");
        await page.getByRole("combobox", { name: "批量入库目标项目" }).selectOption(projectId);
        const batchDirectory = page.getByRole("combobox", { name: "本批正式目录" });
        await batchDirectory.waitFor();
        await batchDirectory.selectOption("project.deliverables");
        await page.getByRole("button", { name: "下一步：核对命名" }).click();
        await page.getByRole("heading", { name: "逐条核对 2 项规范命名" }).waitFor();
        const rowDirectories = page.getByRole("combobox", { name: /正式目录$/ });
        if ((await rowDirectories.count()) !== 2)
          throw new Error("batch review must expose one formal directory input per item");
      }
      if (scenario === "batch-personal-ready") {
        await page.getByRole("checkbox", { name: "全选当前可处理的待确认项" }).check();
        await page.getByRole("button", { name: "批量确认入库（2）" }).click();
        await page.getByRole("combobox", { name: "批量入库目标知识库" }).selectOption("personal");
        const defaultDirectory = page.getByRole("combobox", { name: "本批个人目录" });
        await defaultDirectory.waitFor();
        const optionsText = await defaultDirectory.locator("option").allTextContents();
        if (optionsText.some((label) => label.includes("待处理"))) {
          throw new Error("personal.pending must not be selectable for formal batch ingest");
        }
        await defaultDirectory.selectOption("personal.learning_notes");
        await page.getByRole("button", { name: "下一步：核对入库" }).click();
        await page.getByRole("heading", { name: "核对 2 项个人入库" }).waitFor();
        await page
          .getByRole("combobox", { name: /年度经营计划\.md 个人目录/ })
          .selectOption("personal.project_materials");
        const personalReview = page.getByRole("dialog", { name: "核对 2 项个人入库" });
        personalBatchReviewLayoutValid = await personalReview.evaluate(
          (element) =>
            element.scrollWidth <= element.clientWidth + 2 &&
            element.querySelectorAll(".upload77-personal-directory-row").length === 2 &&
            element.querySelectorAll(".upload77-personal-directory-row select").length === 2 &&
            Boolean(element.querySelector(".task-modal-footer")),
        );
        personalBatchScreenshot = path.join(outDir, `${scenario}-review-${viewport.name}.png`);
        await personalReview.screenshot({
          path: personalBatchScreenshot,
          animations: "disabled",
        });
        const bulkResponse = page.waitForResponse(
          (response) => new URL(response.url()).pathname === "/api/v1/ingest/bulk-confirm",
        );
        await page.getByRole("button", { name: "确认已选择的 2 项入库" }).click();
        await bulkResponse;
      }
      if (scenario === "batch-company-directory-ready") {
        await page.getByRole("checkbox", { name: "全选当前可处理的待确认项" }).check();
        await page.getByRole("button", { name: "批量确认入库（1）" }).click();
        await page.getByRole("combobox", { name: "批量入库目标知识库" }).selectOption("company");
        const batchDirectory = page.getByRole("combobox", { name: "本批正式目录" });
        await batchDirectory.waitFor();
        await batchDirectory.selectOption("company.methodology");
        await page.getByRole("button", { name: "下一步：核对命名" }).click();
        await page.getByLabel(`${longPendingFileName} 适用对象`).fill("公司咨询项目团队");
        await page
          .getByText(`【公司资产-方法论】${longPendingSubject}_20210307_V1_L3.md`)
          .waitFor();
        companyDirectoryScreenshot = path.join(outDir, `${scenario}-preview-${viewport.name}.png`);
        await page.getByRole("dialog").screenshot({
          path: companyDirectoryScreenshot,
          animations: "disabled",
        });
        const bulkResponse = page.waitForResponse(
          (response) => new URL(response.url()).pathname === "/api/v1/ingest/bulk-confirm",
        );
        await page.getByRole("button", { name: "确认已选择的 1 项入库" }).click();
        await bulkResponse;
      }
      if (scenario === "project-submitted") {
        await page.locator("#upload77-target-library").selectOption("project");
        await page.locator("#upload77-target-project").selectOption(projectId);
        await page.locator("#upload77-directory").selectOption("project.basic_information");
        await page.getByRole("button", { name: "确认入库" }).click();
        await page.getByRole("heading", { name: "已提交，等待项目经理确认" }).waitFor();
      }
      if (scenario === "project-naming-ready") {
        await page.locator("#upload77-target-library").selectOption("project");
        await page.locator("#upload77-target-project").selectOption(projectId);
        const directory = page.locator("#upload77-directory");
        await directory.waitFor();
        await directory.selectOption("project.deliverables");
        await page.waitForFunction(
          () => document.querySelector("#upload77-directory")?.value === "project.deliverables",
        );
        await page.getByText(/【PROJECT-2021-交付成果】/).waitFor();
      }
      if (scenario === "personal-submitted") {
        await page.locator("#upload77-target-library").selectOption("personal");
        await page.locator("#upload77-directory").selectOption("personal.learning_notes");
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
          const namingWorkspace = document.querySelector(".task-modal.naming-review-workspace");
          const namingScroll = document.querySelector(".upload77-batch-naming-scroll");
          const batchRowAligned = (row) => {
            const controls = [
              row.querySelector('input[aria-label$="主题"]'),
              row.querySelector('select[aria-label$="正式目录"]'),
              row.querySelector('input[aria-label$="文件形成日期"]'),
              row.querySelector('input[aria-label$="版本"]'),
              row.querySelector('select[aria-label$="密级"]'),
            ].filter(Boolean);
            const tops = controls.map((control) => control.getBoundingClientRect().top);
            const heights = controls.map((control) => control.getBoundingClientRect().height);
            const labelsAligned = [
              ...row.querySelectorAll(".upload77-batch-naming-grid label"),
            ].every((label) => getComputedStyle(label).alignContent === "start");
            return (
              controls.length === 5 &&
              Math.max(...tops) - Math.min(...tops) <= 2 &&
              heights.every((height) => Math.abs(height - 48) <= 1) &&
              controls.every((control) => getComputedStyle(control).boxSizing === "border-box") &&
              labelsAligned &&
              row.querySelector('select[aria-label$="正式目录"]')?.value === "project.deliverables"
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
            shellOverlap:
              window.innerWidth >= 1000 && rail && deck ? Math.max(0, rail.right - deck.left) : 0,
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
            canonicalGenerating: text.includes("正在生成 Markdown"),
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
              document.querySelector("#upload77-directory")?.value === "project.deliverables",
            batchNamingLayoutValid:
              batchRows.length === 2 &&
              batchRows.every((row) =>
                window.innerWidth <= 900
                  ? row.scrollWidth <= row.clientWidth + 2
                  : batchRowAligned(row),
              ) &&
              document.querySelectorAll(".upload77-batch-filter").length === 5 &&
              document.querySelectorAll(".upload77-batch-delete").length === 2 &&
              Boolean(namingWorkspace && namingScroll) &&
              namingWorkspace.scrollWidth <= namingWorkspace.clientWidth + 2 &&
              ["auto", "scroll"].includes(getComputedStyle(namingScroll).overflowY),
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
              /storage_ref|SECRET-LIKE|task-secret-77|project-secret-77|user-secret-77|review-secret-77|generation-ref-secret|csrf-secret-77|identity-hidden|api[_ -]?key|presigned|weknora[_ -]?(doc|kb)[_ -]?id/i.test(
                text,
              ),
            personalBatchReady: !text.includes("重试待分类项") && !text.includes("规范名预览"),
            retiredInputsAbsent:
              !/目录类别|资产类型|本批目录类别/.test(text) &&
              !document.querySelector('[name="category_id"], [name="asset_type"]'),
          };
        },
        { longPendingFileName, longPendingSubject },
      );

      const confirmPayloadValid = confirmPayload
        ? confirmPayload.title === "客户增长项目复盘方法论" &&
          confirmPayload.target_zone === "material" &&
          Array.isArray(confirmPayload.tags) &&
          !("asset_type" in confirmPayload) &&
          !("visibility" in confirmPayload) &&
          !("ai_access_level" in confirmPayload) &&
          !("lifecycle_phase_key" in confirmPayload) &&
          !("embedding_model_id" in confirmPayload) &&
          !("rerank_model_id" in confirmPayload) &&
          (scenario !== "project-submitted" ||
            (confirmPayload.target_scope === "project" &&
              confirmPayload.target_project_id === projectId))
        : false;
      const submittedDirectories = Object.fromEntries(
        (bulkConfirmPayload?.items || []).map((item) => [
          item.task_id,
          item.confirmation?.directory_key,
        ]),
      );
      const personalBatchPayloadValid = Boolean(
        bulkConfirmPayload &&
        bulkConfirmPayload.target_scope === "personal" &&
        bulkConfirmPayload.items?.length === 2 &&
        submittedDirectories[taskId] === "personal.learning_notes" &&
        submittedDirectories["task-safe-78"] === "personal.project_materials" &&
        bulkConfirmPayload.items.every((item) => !("naming" in item.confirmation)),
      );
      const companyDirectoryPayloadValid = Boolean(
        bulkConfirmPayload &&
        bulkConfirmPayload.target_scope === "company" &&
        bulkConfirmPayload.items?.length === 1 &&
        bulkConfirmPayload.items[0]?.confirmation?.naming?.directory_key ===
          "company.methodology" &&
        bulkConfirmPayload.items[0]?.confirmation?.naming?.subject === longPendingSubject &&
        bulkConfirmPayload.items[0]?.confirmation?.naming?.formed_on === "2021-03-07" &&
        bulkConfirmPayload.items[0]?.confirmation?.naming?.version === "V1" &&
        bulkConfirmPayload.items[0]?.confirmation?.naming?.applicable_to === "公司咨询项目团队" &&
        bulkConfirmPayload.items[0]?.confirmation?.confidentiality_level === "L3" &&
        !("category_id" in (bulkConfirmPayload.items[0]?.confirmation?.naming ?? {})) &&
        !("asset_type" in (bulkConfirmPayload.items[0]?.confirmation ?? {})),
      );
      const companyDirectoryPayloadProjection = bulkConfirmPayload?.items?.[0]?.confirmation
        ? {
            directory_key: bulkConfirmPayload.items[0].confirmation.directory_key,
            confidentiality_level: bulkConfirmPayload.items[0].confirmation.confidentiality_level,
            naming: bulkConfirmPayload.items[0].confirmation.naming,
          }
        : null;
      let pendingScreenshot = null;
      let canonicalScreenshot = null;
      if (scenario === "canonical-processing") {
        const queueSection = page.locator('section[aria-labelledby="local-upload-queue-title"]');
        await queueSection.scrollIntoViewIfNeeded();
        canonicalScreenshot = path.join(outDir, `${scenario}-queue-${viewport.name}.png`);
        await queueSection.screenshot({
          path: canonicalScreenshot,
          animations: "disabled",
        });
      }
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
        personalBatchPayloadValid,
        personalBatchReviewLayoutValid,
        personalBatchScreenshot,
        companyDirectoryPayloadValid,
        companyDirectoryPayloadProjection,
        companyDirectoryPreviewed,
        companyDirectoryScreenshot,
        classificationCalls: retiredBusinessRequests.length,
        batchNamingPreviewCalls,
        screenshot,
        pendingScreenshot,
        canonicalScreenshot,
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

const expectedScenarioCount =
  (scenarioFilter.size > 0
    ? scenarios.filter((scenario) => scenarioFilter.has(scenario)).length
    : scenarios.length) * viewports.length;
if (results.length !== expectedScenarioCount || results.some((item) => !assertResult(item))) {
  process.exit(1);
}
