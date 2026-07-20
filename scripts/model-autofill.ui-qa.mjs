import { chromium } from "playwright";
import fs from "node:fs";

const base = process.env.UI_QA_BASE || "http://127.0.0.1:5180";
const outDir =
  process.env.UI_QA_OUT_DIR || `${process.env.TEMP || "/tmp"}/kap-ui-qa/model-autofill`;
fs.mkdirSync(outDir, { recursive: true });

const assert = (condition, message) => {
  if (!condition) throw new Error(message);
};

const emptyUsages = {
  external_llm_default: null,
};

const browser = await chromium.launch();
let postCount = 0;
let postedPayload = null;
let connections = [];

async function prepareContext(viewport) {
  const context = await browser.newContext({ viewport });
  const json = (route, body) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

  await context.route("**/api/v1/auth/me", (route) =>
    json(route, {
      user_id: "00000000-0000-0000-0000-000000000052",
      name: "Autofill QA",
      email: "autofill-qa@example.test",
      status: "active",
      company_roles: ["admin", "boss"],
      is_business_user: true,
      can_discover_l5: true,
      project_memberships: [],
    }),
  );
  await context.route("**/api/v1/auth/csrf", (route) => json(route, { csrf_token: "qa-token" }));
  await context.route("**/api/v1/admin/model-connections/usages/current", (route) =>
    json(route, emptyUsages),
  );
  await context.route("**/api/v1/admin/model-connections", async (route) => {
    if (route.request().method() === "POST") {
      postCount += 1;
      postedPayload = route.request().postDataJSON();
      const created = {
        model_ref: "safe-created-ref",
        display_name: postedPayload.display_name,
        capability_type: postedPayload.capability_type,
        provider: postedPayload.provider,
        model_name: postedPayload.model_name,
        enabled: postedPayload.enabled,
        health_status: "configured",
        available_usages: ["content_generation", "project_qa"],
        legacy_adapter: false,
      };
      connections = [created];
      return json(route, created);
    }
    return json(route, { items: connections, total: connections.length, warning: null });
  });
  return context;
}

async function openCreateForm(page) {
  await page.getByRole("button", { name: "新增外部 LLM", exact: true }).first().click();
  await page.locator('[data-model-field="display_name"]').waitFor();
}

const desktop = await prepareContext({ width: 1440, height: 900 });
const page = await desktop.newPage();
await page.goto(`${base}/admin/weknora-models`, { waitUntil: "networkidle" });
await openCreateForm(page);

await page.evaluate(() => {
  const values = {
    display_name: "Injected display",
    capability_type: "embedding",
    provider: "openai",
    model_name: "injected-model",
    base_url: "https://injected.example/v1",
    api_key: "injected-secret",
    enabled: "disabled",
  };
  for (const [field, value] of Object.entries(values)) {
    document.querySelector(`[data-model-field="${field}"]`).value = value;
  }
});
await page.waitForTimeout(350);

const reconciled = await page.evaluate(() =>
  Object.fromEntries(
    [...document.querySelectorAll("[data-model-field]")].map((control) => [
      control.dataset.modelField,
      control.value,
    ]),
  ),
);
assert(reconciled.display_name === "", "externally injected display name remained visible");
assert(reconciled.model_name === "", "externally injected model name remained visible");
assert(reconciled.base_url === "", "externally injected endpoint remained visible");
assert(reconciled.api_key === "", "externally injected API key remained visible");
assert(reconciled.capability_type === "chat", "capability did not return to controlled state");
assert(reconciled.provider === "deepseek", "Provider did not return to controlled state");
assert(reconciled.enabled === "enabled", "enabled state did not return to controlled state");
assert(postCount === 0, "external autofill caused a POST");
await page.screenshot({ path: `${outDir}/desktop-new-reconciled.png`, fullPage: true });

await page.getByLabel("显示名称").fill("Reviewed connection");
await page.getByLabel("Provider").selectOption("deepseek");
await page.getByLabel("模型名称").fill("deepseek-chat");
await page.getByLabel("API 地址").fill("https://api.example.com/v1");
await page.getByLabel("API key").fill("reviewed-secret");
await page.getByLabel("启用状态").selectOption("enabled");
await page
  .locator(".mf-connection-editor")
  .getByRole("button", { name: /^保存外部 LLM/ })
  .click();
await page.waitForTimeout(250);
assert(postCount === 1, `manual create sent ${postCount} POST requests`);
assert(
  JSON.stringify(postedPayload) ===
    JSON.stringify({
      display_name: "Reviewed connection",
      capability_type: "chat",
      provider: "deepseek",
      model_name: "deepseek-chat",
      base_url: "https://api.example.com/v1",
      api_key: "reviewed-secret",
      enabled: true,
    }),
  "manual create payload did not match reviewed state",
);

await page.getByRole("button", { name: "编辑", exact: true }).click();
await page.locator('[data-model-field="display_name"]').waitFor();
assert((await page.getByLabel("API 地址").inputValue()) === "", "edit form exposed endpoint");
assert((await page.getByLabel("API key").inputValue()) === "", "edit form exposed API key");
await page.screenshot({ path: `${outDir}/desktop-edit-secure.png`, fullPage: true });

await page.getByRole("button", { name: "关闭" }).last().click();
await openCreateForm(page);
assert((await page.getByLabel("显示名称").inputValue()) === "", "new form retained display name");
assert((await page.getByLabel("模型名称").inputValue()) === "", "new form retained model name");
assert((await page.getByLabel("API 地址").inputValue()) === "", "new form retained endpoint");
assert((await page.getByLabel("API key").inputValue()) === "", "new form retained API key");
await desktop.close();

connections = [];
const mobile = await prepareContext({ width: 390, height: 844 });
const mobilePage = await mobile.newPage();
await mobilePage.goto(`${base}/admin/weknora-models`, { waitUntil: "networkidle" });
await openCreateForm(mobilePage);
const mobileMetrics = await mobilePage.evaluate(() => ({
  overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  decoys: document.querySelectorAll(".form-decoy").length,
  fields: document.querySelectorAll(".ws-form-field").length,
}));
assert(mobileMetrics.overflowX === 0, "mobile form has horizontal overflow");
assert(mobileMetrics.decoys === 0, "mobile form still contains autofill decoys");
assert(mobileMetrics.fields === 7, "mobile form does not contain seven business fields");
await mobilePage.screenshot({ path: `${outDir}/mobile-new.png`, fullPage: true });
await mobile.close();
await browser.close();

console.log(
  JSON.stringify(
    { postCount, postedPayload, reconciled, mobileMetrics, screenshots: outDir },
    null,
    2,
  ),
);
