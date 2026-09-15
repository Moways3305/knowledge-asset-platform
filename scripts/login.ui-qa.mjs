import { chromium } from "playwright";
import { createServer } from "vite";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";

const out = path.resolve(".tmp-ui-qa/login");
fs.mkdirSync(out, { recursive: true });
const server = await createServer({ server: { port: 5187, strictPort: true } });
await server.listen();
const browser = await chromium.launch({ headless: true });
try {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    const page = await browser.newPage({ viewport });
    const errors = [];
    const requests = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/api/v1/**", (route) => {
      requests.push(new URL(route.request().url()).pathname);
      return route.fulfill({
        status: 401,
        contentType: "application/json",
        body: '{"detail":"unauthorized"}',
      });
    });
    await page.goto("http://localhost:5187/upload?page=3");
    try {
      await page.getByLabel("邮箱", { exact: true }).waitFor({ timeout: 15000 });
    } catch (error) {
      console.log({ errors, requests, body: await page.locator("body").innerText() });
      await page.screenshot({ path: path.join(out, "failure.png") });
      throw error;
    }
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(out, `${viewport.width}.png`), fullPage: true });
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
      false,
      "horizontal overflow",
    );
    await page.getByLabel("邮箱", { exact: true }).fill("test@example.com");
    await page.getByLabel("密码", { exact: true }).fill("test-password");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "邮箱或密码错误" }).waitFor();
    assert.equal(new URL(page.url()).pathname, "/upload");
    assert.equal(
      requests.some((p) => !["/api/v1/auth/me", "/api/v1/auth/login"].includes(p)),
      false,
      "anonymous business request",
    );
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log(
    `Login UI verified: desktop/mobile, no overflow, safe failure, no anonymous business requests. Screenshots: ${out}`,
  );
} finally {
  await browser.close();
  await server.close();
}
