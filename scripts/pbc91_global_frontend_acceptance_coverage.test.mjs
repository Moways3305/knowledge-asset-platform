import assert from "node:assert/strict";
import test from "node:test";
import { buildRouteCoverage } from "./pbc91_global_frontend_acceptance_coverage.mjs";

const definitions = [
  {
    route: "/admin/example",
    suite: "example",
    states: [
      { name: "normal", scenario: "normal", page: "example" },
      { name: "forbidden", scenario: "forbidden", page: "example" },
    ],
  },
];

function suite(overrides = {}) {
  const cases = ["normal", "forbidden"].flatMap((scenario) =>
    ["1440", "1280"].map((viewport) => ({
      page: "example",
      scenario,
      viewport,
      passed: true,
    })),
  );
  const screenshots = cases.map(
    (item) => `C:\\evidence\\example-${item.scenario}-${item.viewport}.png`,
  );
  return { name: "example", status: "passed", cases, screenshots, ...overrides };
}

test("passes only when every declared state has a concrete case and screenshot", () => {
  const [route] = buildRouteCoverage(definitions, [suite()]);

  assert.equal(route.status, "passed");
  assert.equal(route.checks.length, 4);
  assert.ok(route.checks.every((check) => check.status === "passed" && check.evidence));
});

test("fails instead of inheriting a suite pass when a declared case is missing", () => {
  const complete = suite();
  const cases = complete.cases.filter(
    (item) => !(item.scenario === "forbidden" && item.viewport === "1280"),
  );
  const [route] = buildRouteCoverage(definitions, [{ ...complete, cases }]);
  const missing = route.checks.find(
    (check) => check.state === "forbidden" && check.viewport === "1280",
  );

  assert.equal(route.status, "failed");
  assert.equal(missing?.status, "failed");
  assert.equal(missing?.reason, "missing-case");
});

test("fails concrete coverage for a failed case or missing screenshot", () => {
  const complete = suite();
  const cases = complete.cases.map((item) =>
    item.scenario === "normal" && item.viewport === "1440" ? { ...item, passed: false } : item,
  );
  const screenshots = complete.screenshots.filter(
    (screenshot) => !screenshot.endsWith("example-forbidden-1440.png"),
  );
  const [route] = buildRouteCoverage(definitions, [{ ...complete, cases, screenshots }]);

  assert.equal(
    route.checks.find((check) => check.state === "normal" && check.viewport === "1440")?.reason,
    "case-failed",
  );
  assert.equal(
    route.checks.find((check) => check.state === "forbidden" && check.viewport === "1440")?.reason,
    "missing-screenshot",
  );
});

test("fails a legacy child report case that uses pass=false", () => {
  const complete = suite();
  const cases = complete.cases.map(({ passed, ...item }) =>
    item.scenario === "forbidden" && item.viewport === "1280"
      ? { ...item, pass: false }
      : { ...item, pass: passed },
  );
  const [route] = buildRouteCoverage(definitions, [{ ...complete, cases }]);
  const failed = route.checks.find(
    (check) => check.state === "forbidden" && check.viewport === "1280",
  );

  assert.equal(route.status, "failed");
  assert.equal(failed?.reason, "case-failed");
});

test("uses the page discriminator when one suite covers multiple routes", () => {
  const complete = suite();
  const cases = complete.cases.map((item) => ({ ...item, page: "different-page" }));
  const [route] = buildRouteCoverage(definitions, [{ ...complete, cases }]);

  assert.equal(route.status, "failed");
  assert.ok(route.checks.every((check) => check.reason === "missing-case"));
});
