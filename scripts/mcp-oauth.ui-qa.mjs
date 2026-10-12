import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const out = path.join(os.tmpdir(), "kap-ui-qa", "mcp-oauth");
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
      else if (url.pathname.includes("/mcp-oauth/requests/"))
        body = {
          client_name: "智能体工作平台",
          redirect_origin: "assistant.example",
          operations_requested: true,
        };
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    const page = await context.newPage();
    await page.goto("http://127.0.0.1:5192/mcp-authorize?request=ui-fixture");
    await page.getByRole("heading", { name: "授权智能体访问 KAP" }).waitFor();
    assert.equal(await page.getByRole("checkbox").isChecked(), false);
    assert.equal(await page.getByRole("button", { name: "同意并连接" }).isDisabled(), true);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.screenshot({ path: path.join(out, "consent-" + width + ".png"), fullPage: true });
    await context.close();
  }
  console.log(out);
} finally {
  await browser.close();
}
