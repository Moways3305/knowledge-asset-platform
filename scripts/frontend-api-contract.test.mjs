import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { coverageReport, scanRequests, operations } from "./frontend-api-contract.mjs";
const calls = scanRequests();
describe("frontend API coverage guard", () => {
  it("accounts for the current backend contract", () => {
    assert.ok(coverageReport(calls).includes(`共 ${operations.length} 个 HTTP 操作`));
  });
  it("rejects a request to an unknown backend path", () => {
    assert.throws(
      () =>
        coverageReport([
          ...calls,
          {
            file: "src/api/example.ts",
            owner: "unknownRequest",
            method: "get",
            path: "/api/v1/unknown",
            operations: [],
            consumers: ["src/pages/Example.tsx"],
          },
        ]),
      /Unmatched request/,
    );
  });
  it("rejects losing the consumer of an unexcepted endpoint", () => {
    const removed = calls.map((call) =>
      call.operations.includes("GET /api/v1/reviews/{review_id}")
        ? { ...call, consumers: [] }
        : call,
    );
    assert.throws(
      () => coverageReport(removed),
      /API has no frontend consumer or review: GET \/api\/v1\/reviews\/\{review_id\}/,
    );
  });
});
