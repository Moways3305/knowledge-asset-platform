import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { chromium } from "playwright";

const base = process.env.UI_QA_BASE || "http://127.0.0.1:5188";
const output = path.join(os.tmpdir(), "kap-ui-qa", "knowledge-metadata");
fs.mkdirSync(output, { recursive: true });
const browser = await chromium.launch({ args: ["--disable-gpu"] });
try {
  for (const width of [1440, 390]) {
    let saved = null;
    const context = await browser.newContext({ viewport: { width, height: 1000 } });
    const detail = {
      id: "asset-1", title: "公司知识目录管理规范", scope: "company", zone: "asset",
      asset_type: "unclassified", confidentiality_level: "L2", ai_access_level: "A2",
      asset_status: "active", visibility: "public", tags: ["知识管理", "规范"],
      project_id: null, project_name: null, lifecycle_phase: null, maintainer: null,
      updated_at: "2026-09-29T01:00:00.123456Z", archived_at: null, archive_reason: null,
      summary: { one_liner: "公司知识归类与维护规范。", detailed: "规范公司知识的目录归属、保密等级与维护责任。", key_points: [] },
      current_version: { id: "version-1", version_no: "V1", version_status: "active" },
      directory_key: "company.methodology", directory_path: "公司库 / 方法论",
      canonical_markdown_status: "generated", index_status: "indexed",
      access_info: { discovery: true, summary: true, original: false, can_request_original: true,
        effective_source: "company_role", can_delete: false, can_manage_lifecycle: false, can_edit_metadata: true },
    };
    await context.route("**/api/v1/**", async route => {
      const url = new URL(route.request().url());
      const fulfill = body => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      if (url.pathname === "/api/v1/auth/me") return fulfill({ user_id: "user-1", name: "验收用户",
        status: "active", company_roles: ["consulting_director"], active_company_role: "consulting_director",
        is_business_user: true, can_discover_l5: true, project_memberships: [] });
      if (url.pathname.endsWith("/csrf")) return fulfill({ csrf_token: "local-test" });
      if (url.pathname.endsWith("/metadata")) {
        saved = route.request().postDataJSON(); detail.title = saved.title ?? detail.title;
        return fulfill({ asset_id: detail.id, updated_at: "2026-09-29T02:00:00Z" });
      }
      if (url.pathname === "/api/v1/knowledge/asset-1") return fulfill(detail);
      if (url.pathname.endsWith("/directories")) return fulfill({ items: [{ directory_key: "company.methodology",
        name: "方法论", scope: "company", display_path: "公司库 / 方法论", parent_key: null }] });
      return fulfill({ items: [], total: 0, unread_count: 0 });
    });
    const page = await context.newPage();
    await page.goto(`${base}/knowledge/asset-1`, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "编辑资料", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.waitFor();
    await page.getByLabel("资料标题", { exact: true }).fill("更正后的公司知识目录规范");
    await page.getByLabel("修改原因", { exact: true }).fill("核对原文件后纠正标题");
    await page.screenshot({ path: path.join(output, `${width}.png`), fullPage: true, animations: "disabled" });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    const bounds = await dialog.boundingBox();
    assert(bounds.x >= 0 && bounds.x + bounds.width <= width + 1);
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await dialog.waitFor({ state: "hidden" });
    assert.equal(saved.title, "更正后的公司知识目录规范");
    assert.equal(saved.expected_updated_at, detail.updated_at);
    await context.close();
  }
  console.log(`Metadata editor UI passed (1440 / 390): ${output}`);
} finally { await browser.close(); }
