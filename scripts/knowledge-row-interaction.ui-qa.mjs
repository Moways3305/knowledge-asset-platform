import assert from "node:assert/strict";
import path from "node:path";

// Exercise actual pointer and keyboard states; a resting screenshot cannot catch
// cell backgrounds breaking apart when a table row becomes a grid card.
export async function auditKnowledgeRowInteraction(page, { table, outDir, name }) {
  const row = page
    .locator(`${table} tbody > tr`)
    .filter({ hasNot: page.locator("td[colspan]") })
    .first();
  const firstCell = row.locator("td").first();
  await row.scrollIntoViewIfNeeded();
  await firstCell.hover();
  const readBackgrounds = () =>
    row.evaluate((element) => ({
      display: getComputedStyle(element).display,
      hovered: element.matches(":hover"),
      background: getComputedStyle(element).backgroundColor,
      expected: getComputedStyle(element).getPropertyValue("--color-bg-hover").trim(),
      cells: [...element.children].map((cell) => getComputedStyle(cell).backgroundColor),
    }));
  const hovered = await readBackgrounds();
  await row.screenshot({ path: path.join(outDir, `${name}-hover.png`), animations: "disabled" });
  assert(
    hovered.cells.every((color) => color === "rgba(0, 0, 0, 0)"),
    `${name}: cell backgrounds fragment the row highlight: ${JSON.stringify(hovered)}`,
  );
  assert.equal(
    await row.evaluate((element) => {
      const sample = document.createElement("span");
      sample.style.backgroundColor = getComputedStyle(element).getPropertyValue("--color-bg-hover");
      element.append(sample);
      const expected = getComputedStyle(sample).backgroundColor;
      sample.remove();
      return getComputedStyle(element).backgroundColor === expected;
    }),
    true,
    `${name}: hover must highlight the whole record: ${JSON.stringify(hovered)}; after screenshot: ${JSON.stringify(await readBackgrounds())}`,
  );

  // A card's gaps belong to the record too, rather than interrupting its hover.
  if (hovered.display === "grid") {
    const gap = await row.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      for (let y = Math.max(0, rect.top + 2); y < Math.min(innerHeight, rect.bottom - 2); y += 2) {
        const x = rect.left + rect.width / 2;
        if (document.elementFromPoint(x, y) === element) return { x, y };
      }
      return null;
    });
    assert(gap, `${name}: expected an exposed card gap`);
    await page.mouse.move(gap.x, gap.y);
    assert.equal(
      (await readBackgrounds()).background,
      hovered.background,
      `${name}: moving into a card gap must keep its highlight`,
    );
  }

  await page.mouse.move(0, 0);
  assert.notEqual(
    (await readBackgrounds()).background,
    hovered.background,
    `${name}: highlight must clear when the pointer leaves`,
  );
  await page.keyboard.press("Tab");
  const action = row.locator("button:not(:disabled), a[href]").first();
  const restingShadow = await action.evaluate((element) => {
    element.blur();
    return getComputedStyle(element).boxShadow;
  });
  await action.focus();
  assert.equal(
    await action.evaluate((element, restingShadow) => {
      const style = getComputedStyle(element);
      return (
        element.matches(":focus-visible") &&
        ((style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0) ||
          (style.boxShadow !== "none" && style.boxShadow !== restingShadow))
      );
    }, restingShadow),
    true,
    `${name}: keyboard focus must remain visible`,
  );
  await row.screenshot({ path: path.join(outDir, `${name}-focus.png`), animations: "disabled" });
  await action.evaluate((element) => element.blur());
  return {
    hover: "passed",
    gap: hovered.display === "grid" ? "passed" : "not-applicable",
    focus: "passed",
  };
}
