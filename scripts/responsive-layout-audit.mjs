import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// CSS viewport widths include breakpoint neighbours and the effective layout
// widths of 1440px at 150% / 200% desktop zoom. No production data is used.
const widths = [
  320, 360, 390, 700, 701, 720, 768, 860, 861, 960, 1024, 1100, 1101, 1280, 1440, 1920,
];
const checked = new Set();
const results = [];

export async function auditResponsiveLayout(page, { suite, caseName = "normal" }) {
  const initial = page.viewportSize();
  const address = new URL(page.url());
  const dialog = await page.locator('[role="dialog"]').evaluateAll((nodes) =>
    nodes
      .filter((node) => node.getBoundingClientRect().width > 0)
      .map(
        (node) =>
          node.getAttribute("aria-label") ||
          node.querySelector("h1,h2,h3")?.textContent ||
          "dialog",
      )
      .join("|"),
  );
  const view = await page
    .locator('h1, h2, h3, [role="tab"][aria-selected="true"], button[aria-pressed="true"]')
    .evaluateAll((nodes) =>
      nodes
        .filter((node) => {
          const rect = node.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        })
        .map((node) => node.textContent?.trim())
        .join("|"),
    );
  const key = `${suite}:${caseName}:${address.pathname}${address.search}:${dialog}:${view}`;
  const expanded = process.env.UI_QA_RESPONSIVE_AUDIT === "1";
  if (expanded && checked.has(key)) return;
  checked.add(key);
  const cases = [];
  const output = path.join(
    process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
    "responsive-audit",
  );
  fs.mkdirSync(output, { recursive: true });
  try {
    for (const width of expanded ? widths : [initial.width]) {
      if (expanded) {
        await page.setViewportSize({ width, height: initial.height });
        await page.evaluate(() => document.fonts.ready);
        await page.waitForTimeout(80);
      }
      const issues = await page.evaluate(() => {
        const problems = [];
        const visible = (el) => {
          const s = getComputedStyle(el),
            r = el.getBoundingClientRect();
          return s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0;
        };
        const describe = (el) => `${el.tagName.toLowerCase()}.${el.className || ""}`.slice(0, 140);
        if (document.documentElement.scrollWidth > innerWidth + 2)
          problems.push({
            type: "page-overflow",
            pixels: document.documentElement.scrollWidth - innerWidth,
          });
        for (const row of document.querySelectorAll("table tbody > tr")) {
          if (!visible(row) || !["grid", "flex", "block"].includes(getComputedStyle(row).display))
            continue;
          const cells = [...row.children].filter((el) => el.tagName === "TD" && visible(el));
          for (const cell of cells) {
            // A table height becomes a fixed block height when reflowed; visible
            // overflow can overlap the next metadata row without page overflow.
            const s = getComputedStyle(cell);
            if (s.overflowY === "visible" && cell.scrollHeight > cell.clientHeight + 3)
              problems.push({
                type: "cell-content-overlap",
                element: describe(cell),
                pixels: cell.scrollHeight - cell.clientHeight,
              });
          }
          for (let i = 0; i < cells.length; i++)
            for (let j = i + 1; j < cells.length; j++) {
              const a = cells[i].getBoundingClientRect(),
                b = cells[j].getBoundingClientRect();
              if (
                Math.min(a.right, b.right) - Math.max(a.left, b.left) > 2 &&
                Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 2
              )
                problems.push({
                  type: "cell-box-overlap",
                  elements: [describe(cells[i]), describe(cells[j])],
                });
            }
        }
        return problems;
      });
      cases.push({ suite, caseName, route: new URL(page.url()).pathname, width, issues });
      if (issues.length)
        await page.screenshot({
          path: path.join(
            output,
            `${suite}-${caseName.replace(/[^a-z0-9_-]/gi, "_")}-${width}.png`,
          ),
          animations: "disabled",
        });
    }
  } finally {
    if (expanded) {
      await page.setViewportSize(initial);
      await page.waitForTimeout(100);
    }
    results.push(...cases);
    fs.writeFileSync(path.join(output, `${suite}.json`), JSON.stringify(results, null, 2));
  }
  const failures = cases.filter((item) => item.issues.length);
  if (failures.length) throw new Error(`Responsive layout failures: ${JSON.stringify(failures)}`);
}
