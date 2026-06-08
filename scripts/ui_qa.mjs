// 视觉 QA：渲染核心页面，截图 + 横向溢出/重叠检测。
// 用法：node scripts/ui_qa.mjs <label>   （label 用于区分 baseline / after）
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = "http://localhost:5179";
const label = process.argv[2] || "run";
const outDir = `/tmp/ui_qa/${label}`;
fs.mkdirSync(outDir, { recursive: true });

const ROUTES = [
  ["knowledge", "/knowledge"],
  ["detail", "/knowledge/00000000-0000-0000-0000-0000000000e0"],
  ["upload", "/upload"],
  ["review", "/review"],
  ["original-access", "/original-access"],
  ["admin-ingest", "/admin/ingest"],
  ["admin-wecom", "/admin/wecom-scan"],
  ["admin-audit", "/admin/audit"],
  ["admin-permissions", "/admin/permissions"],
  ["admin-people", "/admin/people"],
  ["admin-alerts", "/admin/alert-settings"],
  ["project-knowledge", "/project/current/knowledge"],
  ["project-settings", "/project/current/settings"],
  ["help", "/help"],
];

const VIEWPORTS = [
  ["desktop", 1366, 768],
  ["narrow", 390, 844],
];

const results = [];

const browser = await chromium.launch();
// 以 dev 用户身份渲染（X-Dev-User-Id 经 fetch header；页面用 cookie/dev header，
// 这里用 boss 身份让业务页有数据态/正常态可检）。注入到 localStorage 不适用——
// 前端 dev header 来自 VITE_DEV_USER_ID 构建期变量；这里仅做布局 QA，空/错误态同样能验证布局。
for (const [vpName, w, h] of VIEWPORTS) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  const page = await ctx.newPage();
  for (const [name, route] of ROUTES) {
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
          const cls = (el.className && el.className.toString) ? el.className.toString().slice(0, 40) : "";
          offenders.push(`${el.tagName.toLowerCase()}.${cls}`.slice(0, 60));
        }
      });
      return { overflowX, offenders: [...new Set(offenders)].slice(0, 8) };
    });
    await page.screenshot({ path: `${outDir}/${vpName}-${name}.png`, fullPage: true });
    results.push({ vp: vpName, name, overflowX: metrics.overflowX, offenders: metrics.offenders });
  }
  await ctx.close();
}
await browser.close();

let report = `# UI QA (${label})\n`;
for (const r of results) {
  const flag = r.overflowX > 2 ? "  <-- HORIZONTAL OVERFLOW" : "";
  report += `${r.vp.padEnd(8)} ${r.name.padEnd(20)} overflowX=${r.overflowX}px${flag}\n`;
  if (r.offenders.length) report += `         offenders: ${r.offenders.join(", ")}\n`;
}
fs.writeFileSync(`${outDir}/report.txt`, report);
console.log(report);

