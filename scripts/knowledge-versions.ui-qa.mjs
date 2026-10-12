import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const assetId = "00000000-0000-0000-0000-000000000901";
const newId = "00000000-0000-0000-0000-000000000902";
const stamp = "2026-10-12T00:00:00Z";
const out = path.join(os.tmpdir(), "kap-ui-qa", "knowledge-versions");
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: "chrome" });
try {
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 } });
    await context.route("**/api/v1/**", async (route) => {
      const url = new URL(route.request().url());
      let body = { items: [], total: 0, unread_count: 0 };
      if (url.pathname === "/api/v1/auth/me")
        body = {
          user_id: "qa-reader",
          name: "验收用户",
          status: "active",
          company_roles: ["consultant"],
          active_company_role: "consultant",
          is_business_user: true,
          can_discover_l5: false,
          project_memberships: [],
        };
      else if (url.pathname.endsWith("/versions/compare"))
        body = {
          left: {
            version: "V1",
            directory: "personal.learning_notes",
            summary: "旧版只记录实施步骤。",
          },
          right: {
            version: "V2",
            directory: "personal.learning_notes",
            summary: "新版增加操作风险和复核步骤。",
          },
          changed_fields: ["version", "summary"],
          scope: "摘要与版本元信息，不包含原文件全文",
        };
      else if (url.pathname.endsWith("/versions"))
        body = {
          asset_id: assetId,
          updated_at: stamp,
          current_asset_id: assetId,
          can_update: true,
          suggested_version: "V2",
          truncated: false,
          updates: [
            {
              task_id: "qa-task",
              version: "V2",
              status: "completed",
              result_asset_id: newId,
              can_replace: true,
            },
          ],
          items: [
            {
              asset_id: assetId,
              version_id: "v1",
              title: "实施操作规范",
              version: "V1",
              status: "active",
              version_status: "active",
              created_at: stamp,
              is_current: true,
            },
            {
              asset_id: newId,
              version_id: "v2",
              title: "实施操作规范第二版",
              version: "V2",
              status: "active",
              version_status: "active",
              created_at: stamp,
              is_current: false,
            },
          ],
        };
      else if (url.pathname.endsWith("/trust"))
        body = {
          asset_id: assetId,
          updated_at: stamp,
          maintainer_user_id: null,
          maintainer_name: null,
          review_due_at: null,
          verified_at: stamp,
          freshness: "verified",
          replacement_asset_id: null,
          can_manage: true,
          corrections: [],
          maintainers: [],
        };
      else if (url.pathname === `/api/v1/knowledge/${assetId}`)
        body = {
          id: assetId,
          title: "实施操作规范",
          scope: "personal",
          zone: "material",
          asset_type: "material",
          confidentiality_level: "L2",
          ai_access_level: "A1",
          asset_status: "active",
          visibility: "project_only",
          tags: ["操作规范", "实施复盘"],
          project_id: null,
          project_name: null,
          lifecycle_phase: null,
          maintainer: null,
          last_called_at: null,
          updated_at: stamp,
          archived_at: null,
          archive_reason: null,
          summary: {
            one_liner: "记录实施过程中的操作步骤与复核要求。",
            detailed: "供资料维护人核查操作流程，更新时保留旧版并明确关联新版本。",
            key_points: [],
          },
          current_version: { id: "v1", version_no: "V1", version_status: "active" },
          access_info: {
            discovery: true,
            summary: true,
            original: true,
            effective_source: "owner",
            can_request_original: false,
            can_delete: false,
            can_manage_lifecycle: true,
            can_edit_metadata: true,
            can_retry_index: false,
          },
          index_status: "indexed",
          directory_key: "personal.learning_notes",
          directory_path: "个人库 / 学习笔记",
          canonical_markdown_status: "generated",
        };
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    const page = await context.newPage();
    page.on("pageerror", (error) => console.log("Page error:", error.message));
    await page.goto("http://127.0.0.1:5190/knowledge/" + assetId);
    await page
      .getByRole("button", { name: "更新这份资料", exact: true })
      .waitFor({ timeout: 10000 })
      .catch(async (error) => {
        await page.screenshot({ path: path.join(out, "debug.png"), fullPage: true });
        console.log((await page.locator("body").innerText()).slice(0, 1500));
        throw error;
      });
    await page.screenshot({ path: path.join(out, `detail-${width}.png`), fullPage: true });
    await page.getByRole("button", { name: "版本历史与差异", exact: true }).click();
    await page.getByLabel("原版本", { exact: true }).selectOption("v1");
    await page.getByLabel("新版本", { exact: true }).selectOption("v2");
    await page.getByRole("button", { name: "查看差异", exact: true }).click();
    await page.getByText("新版增加操作风险和复核步骤。", { exact: true }).waitFor();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.screenshot({ path: path.join(out, `history-${width}.png`), fullPage: true });
    await page.getByText("新版增加操作风险和复核步骤。", { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(out, `difference-${width}.png`), fullPage: true });
    await context.close();
  }
  console.log("Version workflow screenshots:", out);
} finally {
  await browser.close();
}
