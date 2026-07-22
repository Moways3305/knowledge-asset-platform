import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5201);
const base = `http://127.0.0.1:${port}`;
const outDir = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "model-foundation",
);
fs.mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "1440", width: 1440, height: 1080 },
  { name: "1280", width: 1280, height: 960 },
];
const scenarios = [
  "normal",
  "weknora-unconfigured",
  "kb-empty",
  "external-empty",
  "test-failure",
  "forbidden",
];

const authMe = {
  user_id: "qa-admin-ref",
  name: "模型配置管理员",
  email: "qa-admin@example.test",
  status: "active",
  company_roles: ["admin"],
  active_company_role: "admin",
  is_business_user: false,
  can_discover_l5: false,
  project_memberships: [],
};

const connections = [
  {
    model_ref: "external-safe-ref",
    display_name: "生产对话模型",
    capability_type: "chat",
    provider: "deepseek",
    model_name: "deepseek-chat",
    enabled: true,
    health_status: "healthy",
    last_test_succeeded_at: "2026-07-18T08:20:00Z",
    last_test_failed_at: null,
    last_error_category: null,
    available_usages: ["content_generation", "project_qa"],
    legacy_adapter: false,
    api_key: "SECRET_API_KEY_86",
    base_url: "https://secret-provider.example.test/v1",
    model_id: "SECRET_INTERNAL_MODEL_ID_86",
  },
  {
    model_ref: "external-backup-ref",
    display_name: "备用对话模型",
    capability_type: "chat",
    provider: "qwen",
    model_name: "qwen-plus",
    enabled: false,
    health_status: "untested",
    last_test_succeeded_at: null,
    last_test_failed_at: null,
    last_error_category: null,
    available_usages: ["content_generation", "project_qa"],
    legacy_adapter: false,
  },
];

const models = [
  {
    model_ref: "embedding-safe-ref",
    name: "通用嵌入模型",
    type: "embedding",
    source: "remote",
    provider: "managed",
    enabled: true,
    is_builtin: false,
    description: null,
    model_id: "SECRET_WEKNORA_MODEL_ID_86",
  },
  {
    model_ref: "chat-safe-ref",
    name: "底座兼容模型",
    type: "chat",
    source: "remote",
    provider: "managed",
    enabled: true,
    is_builtin: false,
    description: null,
  },
  {
    model_ref: "rerank-safe-ref",
    name: "中文重排模型",
    type: "rerank",
    source: "remote",
    provider: "managed",
    enabled: true,
    is_builtin: false,
    description: null,
  },
];

const defaults = {
  embedding: {
    model_ref: "embedding-safe-ref",
    name: "通用嵌入模型",
    type: "embedding",
    provider: "managed",
  },
  chat: { model_ref: "chat-safe-ref", name: "底座兼容模型", type: "chat", provider: "managed" },
  rerank: {
    model_ref: "rerank-safe-ref",
    name: "中文重排模型",
    type: "rerank",
    provider: "managed",
  },
  multimodal: null,
  updated_at: "2026-07-18T08:00:00Z",
};

const kbConfigs = [
  {
    mapping_id: "SECRET_MAPPING_ID_86",
    scope: "company",
    kb_name: "公司知识底座",
    project_name: null,
    owner_name: null,
    mapping_status: "active",
    chat: defaults.chat,
    embedding: defaults.embedding,
    rerank: defaults.rerank,
    multimodal: null,
    config_error: null,
    weknora_kb_id: "SECRET_WEKNORA_KB_ID_86",
  },
  {
    mapping_id: "SECRET_FAILED_MAPPING_ID_86",
    scope: "project",
    kb_name: "交付方法知识库",
    project_name: "交付改进项目",
    owner_name: null,
    mapping_status: "init_failed",
    chat: defaults.chat,
    embedding: defaults.embedding,
    rerank: null,
    multimodal: null,
    config_error: "当前模型组合不兼容，请调整后重新保存。",
  },
];

let server;
let browser;
const results = [];
try {
  await build({ logLevel: "warn" });
  server = await preview({
    preview: { host: "127.0.0.1", port, strictPort: true },
    logLevel: "warn",
  });
  browser = await chromium.launch({ args: ["--disable-gpu"] });

  for (const scenario of scenarios) {
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport });
      const messages = [];
      await context.route("**/*", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
        if (!url.pathname.startsWith("/api/")) return route.continue();
        if (url.pathname === "/api/v1/auth/me") return fulfill(authMe);
        if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "qa-csrf-86" });

        if (scenario === "forbidden" && url.pathname.includes("/api/v1/admin/")) {
          return fulfill({ detail: { message: "SECRET_FORBIDDEN_BODY_86" } }, 403);
        }
        if (url.pathname === "/api/v1/admin/model-connections") {
          return fulfill({
            items: scenario === "external-empty" ? [] : connections,
            total: scenario === "external-empty" ? 0 : connections.length,
            warning: null,
          });
        }
        if (url.pathname === "/api/v1/admin/model-connections/usages/current") {
          return fulfill({
            external_llm_default:
              scenario === "external-empty"
                ? null
                : {
                    model_ref: "external-safe-ref",
                    display_name: "生产对话模型",
                    capability_type: "chat",
                  },
            dependency_status: scenario === "external-empty" ? "missing" : "configured",
            dependency_message:
              scenario === "external-empty"
                ? "未设置外部 LLM 默认连接。"
                : "内容生成和默认项目问答使用当前外部 LLM 连接。",
            remediation_hint:
              scenario === "external-empty" ? "新增并测试一条连接后再设置默认用途。" : "无需处理。",
          });
        }
        if (url.pathname === "/api/v1/admin/model-connections/items/external-safe-ref/test") {
          if (scenario === "test-failure") {
            return fulfill(
              {
                detail: {
                  message: "SECRET_UPSTREAM_ERROR_86",
                  remediation_hint: "请检查凭据是否有效后重试。",
                },
              },
              502,
            );
          }
          return fulfill({
            success: true,
            error_category: null,
            message: "外部 LLM 连接正常。",
            remediation_hint: "无需处理。",
            retryable: false,
            duration_ms: 36,
          });
        }
        if (url.pathname === "/api/v1/admin/weknora/models") {
          if (scenario === "weknora-unconfigured") {
            return fulfill({ detail: { message: "SECRET_WEKNORA_503_BODY_86" } }, 503);
          }
          return fulfill({ items: models });
        }
        if (url.pathname === "/api/v1/admin/weknora/default-models") return fulfill(defaults);
        if (url.pathname === "/api/v1/admin/weknora/kb-configs") {
          return fulfill({ items: scenario === "kb-empty" ? [] : kbConfigs });
        }
        return fulfill({ detail: { message: "UI QA route not configured" } }, 404);
      });

      const page = await context.newPage();
      page.on("console", (message) => messages.push(message.text()));
      page.on("pageerror", (error) => messages.push(error.message));
      await page.goto(`${base}/admin/weknora-models`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "模型与知识库底座" }).waitFor();

      if (scenario === "weknora-unconfigured") {
        await page.getByText("WeKnora 尚未配置").waitFor();
        await page.getByText("生产对话模型", { exact: true }).waitFor();
      } else if (scenario === "kb-empty") {
        await page.getByText("暂无知识库").waitFor();
        await page.getByLabel("默认嵌入模型").waitFor();
      } else if (scenario === "external-empty") {
        await page.getByText("尚未配置外部 LLM 连接").waitFor();
        await page.getByLabel("默认嵌入模型").waitFor();
      } else if (scenario === "test-failure") {
        await page.getByRole("button", { name: "测试连接" }).first().click();
        await page.getByText(/请检查凭据是否有效后重试/).waitFor();
      } else if (scenario === "forbidden") {
        await page.getByText("当前身份没有模型管理权限，此区域保持只读。").waitFor();
        await page.getByText("当前身份没有 WeKnora 管理权限，此区域保持只读。").waitFor();
      } else {
        await page.getByText("公司知识底座").waitFor();
      }

      const screenshot = path.join(outDir, `${scenario}-${viewport.name}.png`);
      await page.screenshot({ path: screenshot, animations: "disabled", fullPage: true });
      const metrics = await page.evaluate((scenarioName) => {
        const root = document.documentElement;
        const workspace = document.querySelector(".mf-workspace")?.getBoundingClientRect();
        const external = document.querySelector(".mf-external-panel")?.getBoundingClientRect();
        const foundation = document.querySelector(".mf-foundation-panel")?.getBoundingClientRect();
        const text = document.body.innerText;
        const secrets = [
          "SECRET_API_KEY_86",
          "secret-provider.example.test",
          "SECRET_INTERNAL_MODEL_ID_86",
          "SECRET_WEKNORA_MODEL_ID_86",
          "SECRET_MAPPING_ID_86",
          "SECRET_FAILED_MAPPING_ID_86",
          "SECRET_WEKNORA_KB_ID_86",
          "SECRET_UPSTREAM_ERROR_86",
          "SECRET_WEKNORA_503_BODY_86",
          "SECRET_FORBIDDEN_BODY_86",
        ];
        return {
          scenario: scenarioName,
          overflowX: root.scrollWidth - root.clientWidth,
          split:
            Boolean(workspace && external && foundation) &&
            Math.abs(external.y - foundation.y) <= 2 &&
            external.width / (external.width + foundation.width) >= 0.64 &&
            external.width / (external.width + foundation.width) <= 0.71,
          cardCount: document.querySelectorAll(".mf-connection-card").length,
          foundationVisible: Boolean(document.querySelector(".mf-foundation-panel")),
          kbSectionVisible: Boolean(document.querySelector(".mf-kb-section")),
          safe: secrets.every((secret) => !text.includes(secret)),
          formClipped: [...document.querySelectorAll("button, select, input")].some(
            (node) => node.scrollWidth > node.clientWidth + 3,
          ),
          externalAvailable: text.includes("生产对话模型"),
          foundationAvailable: text.includes("通用嵌入模型"),
          weknoraEmpty: text.includes("WeKnora 尚未配置"),
          externalEmpty: text.includes("尚未配置外部 LLM 连接"),
          kbEmpty: text.includes("暂无知识库"),
          testFailure: text.includes("请检查凭据是否有效后重试"),
          forbidden:
            text.includes("当前身份没有模型管理权限") &&
            text.includes("当前身份没有 WeKnora 管理权限") &&
            !text.includes("新增外部 LLM"),
        };
      }, scenario);
      metrics.consoleLeak = messages.some((message) =>
        /secret|api_key|weknora_kb_id/i.test(message),
      );
      const scenarioPass = {
        normal: metrics.externalAvailable && metrics.foundationAvailable && metrics.cardCount === 2,
        "weknora-unconfigured": metrics.externalAvailable && metrics.weknoraEmpty,
        "kb-empty": metrics.externalAvailable && metrics.foundationAvailable && metrics.kbEmpty,
        "external-empty":
          metrics.externalEmpty && metrics.foundationAvailable && metrics.cardCount === 0,
        "test-failure": metrics.testFailure && metrics.externalAvailable,
        forbidden: metrics.forbidden,
      }[scenario];
      metrics.pass = Boolean(
        metrics.overflowX <= 2 &&
        metrics.split &&
        metrics.foundationVisible &&
        metrics.kbSectionVisible &&
        metrics.safe &&
        !metrics.formClipped &&
        !metrics.consoleLeak &&
        scenarioPass,
      );
      results.push({ viewport: viewport.name, screenshot, ...metrics });
      await context.close();
    }
  }
} finally {
  await browser?.close();
  await server?.close();
}

const reportPath = path.join(outDir, "report.json");
fs.writeFileSync(reportPath, JSON.stringify(results, null, 2));
console.log(JSON.stringify({ outDir, reportPath, results }, null, 2));
if (results.some((result) => !result.pass)) process.exitCode = 1;
