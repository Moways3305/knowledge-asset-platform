import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.UI_QA_BASE || "http://127.0.0.1:5192";
const output = path.join(process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"), "company-directory-children");
fs.mkdirSync(output, { recursive: true });
const browser = await chromium.launch();
const root = { directory_key: "company.methodology", scope: "company", display_name: "02 方法论", naming_code: "方法论", default_confidentiality: "L2", sort_order: 20, enabled: true };
const child = { ...root, directory_key: "company.custom_00000000000000000000000000000001", parent_key: root.directory_key, display_name: "战略模板", naming_code: "战略模板" };
try {
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 } });
    let saved = null;
    await context.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      let body = { items: [], total: 0, page: 1, page_size: 20, has_next: false };
      if (url.pathname === "/api/v1/auth/me") body = { user_id: "governance", name: "治理用户", status: "active", company_roles: ["boss"], active_company_role: "boss", is_business_user: true, can_discover_l5: true, project_memberships: [] };
      if (url.pathname === "/api/v1/admin/naming-rules") {
        const config = { schema_version: 2, enforced: true, project_codes: [], categories: [], directories: [root] };
        body = { published: { version: 1, config }, draft: { version: 2, config }, projects: [] };
      }
      if (url.pathname.endsWith("/naming-rules/draft")) {
        saved = route.request().postDataJSON();
        body = { version: 2, config: { schema_version: 2, categories: [], project_codes: [], directories: saved.directories } };
      }
      if (url.pathname === "/api/v1/knowledge/directories") body = { items: [root, child].map((item) => ({ ...item, name: item.display_name, parent_key: item.parent_key ?? null, display_path: `公司库 / ${item.parent_key ? "02 方法论 / " : ""}${item.display_name}`, project_id: null, project_name: null })) };
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    const page = await context.newPage();
    await page.goto(`${base}/admin/naming-rules?parent=company.methodology`);
    await page.getByLabel("三级目录名称").fill("战略模板");
    await page.getByRole("button", { name: "添加到草稿" }).click();
    await page.getByRole("button", { name: /保存草稿/ }).click();
    await page.getByText("草稿已保存", { exact: false }).waitFor();
    assert.equal(saved.directories[1].parent_key, root.directory_key);
    assert.equal(saved.directories[1].default_confidentiality, "L2");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
    await page.getByRole("button", { name: "添加到草稿" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, `create-${width}.png`), fullPage: true });
    await page.goto(`${base}/knowledge?scope=company&directory_key=company.methodology`);
    await page.getByRole("button", { name: /战略模板/ }).click();
    await page.getByRole("link", { name: "返回上级分类" }).waitFor();
    assert.equal(await page.getByRole("link", { name: "新建三级目录" }).count(), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
    await page.screenshot({ path: path.join(output, `browse-${width}.png`), fullPage: true });
    await context.close();
  }
} finally { await browser.close(); }
console.log("Company directory creation and browsing: 4 viewport cases passed");
