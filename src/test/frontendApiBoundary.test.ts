import { describe, expect, it } from "vitest";
import * as ts from "typescript";
import type { ApiPath } from "../api/generated/routes";

const sources = import.meta.glob(
  ["../{pages,components,hooks,layouts}/**/*.{ts,tsx}", "!../**/*.test.*"],
  { eager: true, query: "?raw", import: "default" },
) as Record<string, string>;

describe("frontend request boundaries", () => {
  it("keeps network transport inside domain API modules", () => {
    const violations: string[] = [];
    for (const [file, text] of Object.entries(sources)) {
      const source = ts.createSourceFile(
        file,
        text,
        ts.ScriptTarget.Latest,
        true,
        ts.ScriptKind.TSX,
      );
      function visit(node: ts.Node) {
        if (
          ts.isCallExpression(node) &&
          ts.isIdentifier(node.expression) &&
          /^(fetch|apiGet|apiPost|apiPostNoBody|apiPatch|apiPut|apiDelete|apiUpload)$/.test(
            node.expression.text,
          )
        )
          violations.push(`${file}: ${node.expression.text}`);
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
    expect(violations).toEqual([]);
  });

  it("keeps method and path typing coupled to the exported backend contract", () => {
    const valid: ApiPath<"get"> = "/api/v1/reviews?queue=open";
    // @ts-expect-error A misspelled endpoint must fail compilation.
    const missing: ApiPath<"get"> = "/api/v1/not-a-real-endpoint";
    // @ts-expect-error This route is POST-only.
    const wrongMethod: ApiPath<"get"> = "/api/v1/auth/logout";
    expect([valid, missing, wrongMethod]).toHaveLength(3);
  });
});
