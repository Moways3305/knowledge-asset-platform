// 视觉 QA：渲染核心页面，截图 + 横向溢出/重叠检测。
// 用法：node scripts/ui_qa.mjs <label>   （label 用于区分 baseline / after）
// 可选环境变量（默认值与原本地用法一致）：
//   UI_QA_BASE     前端基址（默认 http://localhost:5179）
//   UI_QA_OUT_DIR  输出根目录（默认 /tmp/ui_qa）
// 退出码：任一路由横向溢出（overflowX 超过检测阈值）时以非零退出，供 CI 判失败。
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.UI_QA_BASE || "http://localhost:5179";
const label = process.argv[2] || "run";
const outRoot = process.env.UI_QA_OUT_DIR || "/tmp/ui_qa";
const outDir = `${outRoot}/${label}`;
const mockAuth = process.env.UI_QA_MOCK_AUTH !== "0";
fs.mkdirSync(outDir, { recursive: true });

const ROUTES = [
  ["home", "/"],
  ["knowledge", "/knowledge"],
  ["detail", "/knowledge/00000000-0000-0000-0000-0000000000e0"],
  ["my-knowledge", "/my/knowledge"],
  ["upload", "/upload"],
  ["review", "/review"],
  ["original-access", "/original-access"],
  ["admin-ingest", "/admin/ingest"],
  ["admin-wecom", "/admin/wecom-scan"],
  ["admin-models", "/admin/weknora-models"],
  ["admin-audit", "/admin/audit"],
  ["admin-auth", "/admin/auth-security"],
  ["admin-permissions", "/admin/permissions"],
  ["admin-people", "/admin/people"],
  ["admin-alerts", "/admin/alert-settings"],
  ["project-knowledge", "/project/current/knowledge"],
  ["project-settings", "/project/current/settings"],
  ["help", "/help"],
];

const VIEWPORTS = [
  ["desktop-1440", 1440, 900],
  ["desktop-1920", 1920, 1080],
  ["mobile-390", 390, 844],
];

const results = [];

const browser = await chromium.launch();
// 默认仅拦截 /auth/me 注入兼具业务与管理能力的验收身份，让所有路由都能进入自身页面；
// 其余 API 仍走真实基址，因此本脚本不会伪造业务数据或绕过应用内的页面状态处理。
for (const [vpName, w, h] of VIEWPORTS) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  if (mockAuth) {
    await ctx.route("**/api/v1/auth/me", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          user_id: "00000000-0000-0000-0000-000000000047",
          name: "布局验收用户",
          email: "ui-qa@example.test",
          status: "active",
          company_roles: ["admin", "boss"],
          is_business_user: true,
          can_discover_l5: true,
          project_memberships: [
            {
              project_id: "current",
              project_name: "界面验收项目",
              project_role: "project_manager",
              status: "active",
            },
          ],
        }),
      }),
    );
  }
  for (const [name, route] of ROUTES) {
    // A fresh page per route prevents Chromium compositor tiles from leaking across repeated SPA
    // navigation, which otherwise can create black screenshot regions despite correct DOM colors.
    const page = await ctx.newPage();
    try {
      await page.goto(`${BASE}${route}`, { waitUntil: "networkidle", timeout: 15000 });
    } catch {
      await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded", timeout: 15000 });
    }
    await page.waitForTimeout(700);
    // 横向溢出检测：文档 / 内容区 scrollWidth 是否超过视口。
    const metrics = await page.evaluate(() => {
      const de = document.documentElement;
      const overflowX = de.scrollWidth - de.clientWidth;
      // 找出宽度超出视口的元素（可能撑破布局）。
      const offenders = [];
      const vw = de.clientWidth;
      document.querySelectorAll("*").forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.right > vw + 2) {
          const cls =
            el.className && el.className.toString ? el.className.toString().slice(0, 40) : "";
          offenders.push(`${el.tagName.toLowerCase()}.${cls}`.slice(0, 60));
        }
      });
      const rail = document.querySelector(".rail")?.getBoundingClientRect();
      const main = document.querySelector(".app-main")?.getBoundingClientRect();
      const deck = document.querySelector(".deck")?.getBoundingClientRect();
      const content = document.querySelector(".app-content")?.getBoundingClientRect();
      const desktopShell = vw >= 1024;
      const shellOverlap = Boolean(
        desktopShell &&
        rail &&
        main &&
        deck &&
        content &&
        (rail.right > main.left + 1 || deck.bottom > content.top + 1),
      );
      const visibleNavLinks = document.querySelectorAll(".rail-nav a").length;
      const brokenNavigation = visibleNavLinks === 0 || (main?.width ?? 0) <= 0;
      return {
        overflowX,
        offenders: [...new Set(offenders)].slice(0, 8),
        shellOverlap,
        brokenNavigation,
        visibleNavLinks,
      };
    });
    // The shell owns its internal scroll regions, so viewport screenshots represent the actual
    // desktop frame. Chromium fullPage capture can produce black compositor tiles after repeated
    // SPA navigation even when computed colors and a fresh-page screenshot are correct.
    await page.screenshot({ path: `${outDir}/${vpName}-${name}.png` });
    results.push({ vp: vpName, name, ...metrics });
    await page.close();
  }
  await ctx.close();
}
await browser.close();

let report = `# UI QA (${label})\n`;
for (const r of results) {
  const failed = r.overflowX > 2 || r.shellOverlap || r.brokenNavigation;
  const flag = failed ? "  <-- LAYOUT FAILURE" : "";
  report += `${r.vp.padEnd(8)} ${r.name.padEnd(20)} overflowX=${r.overflowX}px${flag}\n`;
  if (r.offenders.length) report += `         offenders: ${r.offenders.join(", ")}\n`;
  if (r.shellOverlap) report += "         shell overlap detected\n";
  if (r.brokenNavigation) report += `         broken navigation (${r.visibleNavLinks} links)\n`;
}
fs.writeFileSync(`${outDir}/report.txt`, report);
console.log(report);

// 与上方 HORIZONTAL OVERFLOW 标记同一阈值（>2px，容忍亚像素取整抖动）；
// 任一路由命中即非零退出，供 CI 判失败。
const failed = results.filter((r) => r.overflowX > 2 || r.shellOverlap || r.brokenNavigation);
if (failed.length) {
  console.error(
    `UI QA failed: ${failed.length} route/viewport combination(s) with layout failures.`,
  );
  process.exit(1);
}
