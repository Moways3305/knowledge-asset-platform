import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const verbs = ["get", "post", "put", "patch", "delete", "head", "options"];
const contract = JSON.parse(fs.readFileSync(path.join(root, "docs/api/openapi.json"), "utf8"));
export const operations = Object.entries(contract.paths).flatMap(([route, item]) =>
  verbs
    .filter((verb) => item[verb])
    .map((verb) => ({
      key: `${verb.toUpperCase()} ${route}`,
      method: verb,
      path: route,
      summary: item[verb].summary ?? "",
      operationId: item[verb].operationId,
    })),
);

function filesIn(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const name = path.join(directory, entry.name);
    return entry.isDirectory()
      ? filesIn(name)
      : /\.tsx?$/.test(name) && !/\.test\./.test(name)
        ? [name]
        : [];
  });
}

const methodNames = {
  apiGet: "get",
  apiPost: "post",
  apiPostNoBody: "post",
  apiPatch: "patch",
  apiPut: "put",
  apiDelete: "delete",
  apiUpload: "post",
};

export function scanRequests() {
  const config = ts.readConfigFile(path.join(root, "tsconfig.json"), ts.sys.readFile);
  const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, root);
  const program = ts.createProgram(parsed.fileNames, parsed.options);
  const checker = program.getTypeChecker();
  function typePaths(type) {
    if (type.isUnion()) return type.types.flatMap(typePaths);
    if (type.isStringLiteral()) return [type.value];
    if (type.flags & ts.TypeFlags.TemplateLiteral) return [type.texts.join("{*}")];
    return [];
  }
  const calls = [];
  const imports = [];
  for (const file of filesIn(path.join(root, "src"))) {
    const source = program.getSourceFile(file);
    if (file.includes(`${path.sep}generated${path.sep}`)) continue;
    const constants = new Map();
    const visitConstants = (node) => {
      if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer)
        constants.set(node.name.text, node.initializer);
      ts.forEachChild(node, visitConstants);
    };
    visitConstants(source);
    function resolve(node, seen = new Set()) {
      if (!node) return "{*}";
      if (ts.isStringLiteralLike(node)) return node.text;
      if (ts.isIdentifier(node)) {
        if (node.text === "BASE_URL") return "";
        if (seen.has(node.text)) return "{*}";
        if (constants.has(node.text))
          return resolve(constants.get(node.text), new Set([...seen, node.text]));
      }
      if (ts.isTemplateExpression(node))
        return (
          node.head.text +
          node.templateSpans
            .map((span) => resolve(span.expression, seen) + span.literal.text)
            .join("")
        );
      if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken)
        return resolve(node.left, seen) + resolve(node.right, seen);
      return "{*}";
    }
    function owner(node) {
      let name = "module";
      for (let parent = node.parent; parent && parent !== source; parent = parent.parent) {
        if (ts.isFunctionDeclaration(parent) && parent.name) name = parent.name.text;
        else if (
          ts.isVariableDeclaration(parent) &&
          ts.isIdentifier(parent.name) &&
          parent.initializer &&
          (ts.isArrowFunction(parent.initializer) || ts.isFunctionExpression(parent.initializer))
        )
          name = parent.name.text;
      }
      return name;
    }
    function visit(node) {
      if (
        ts.isExportDeclaration(node) &&
        node.moduleSpecifier &&
        ts.isStringLiteral(node.moduleSpecifier) &&
        node.exportClause &&
        ts.isNamedExports(node.exportClause)
      ) {
        for (const element of node.exportClause.elements)
          imports.push({
            file: path.relative(root, file).replaceAll("\\", "/"),
            name: element.propertyName?.text ?? element.name.text,
            from: path.resolve(path.dirname(file), node.moduleSpecifier.text).replaceAll("\\", "/"),
          });
      }
      if (
        ts.isImportDeclaration(node) &&
        ts.isStringLiteral(node.moduleSpecifier) &&
        node.moduleSpecifier.text.startsWith(".")
      ) {
        const bindings = node.importClause?.namedBindings;
        if (bindings && ts.isNamedImports(bindings))
          for (const element of bindings.elements) {
            if (!element.isTypeOnly && !node.importClause.isTypeOnly)
              imports.push({
                file: path.relative(root, file).replaceAll("\\", "/"),
                name: element.propertyName?.text ?? element.name.text,
                from: path
                  .resolve(path.dirname(file), node.moduleSpecifier.text)
                  .replaceAll("\\", "/"),
              });
          }
      }
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
        const callee = node.expression.text;
        let method = methodNames[callee];
        if (callee === "fetch") {
          method = "get";
          const options = node.arguments[1];
          if (options && ts.isObjectLiteralExpression(options)) {
            const prop = options.properties.find(
              (p) => ts.isPropertyAssignment(p) && p.name.getText(source) === "method",
            );
            if (prop) method = resolve(prop.initializer).toLowerCase();
          }
        }
        if (method) {
          let candidates = typePaths(checker.getTypeAtLocation(node.arguments[0])).filter((route) =>
            route.startsWith("/"),
          );
          if (!candidates.length) candidates = [resolve(node.arguments[0])];
          for (let route of candidates) {
            route = route.split("?")[0];
            // A trailing interpolation without a slash is a query suffix in our adapters.
            // Leave fully dynamic paths unresolved for explicit review.
            if (route.endsWith("{*}") && !route.endsWith("/{*}") && route !== "{*}")
              route = route.slice(0, -3);
            calls.push({
              file: path.relative(root, file).replaceAll("\\", "/"),
              owner: owner(node),
              line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
              method,
              path: route,
            });
          }
        }
      }
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
  const canonical = (route) => route.replace(/\{[^}]*\}/g, "{}");
  return calls.map((call) => ({
    ...call,
    operations: operations
      .filter(
        (operation) =>
          operation.method === call.method && canonical(operation.path) === canonical(call.path),
      )
      .map((operation) => operation.key),
    consumers: [
      ...new Set(
        imports
          .filter(
            (entry) =>
              entry.name === call.owner &&
              entry.from ===
                path
                  .join(root, call.file)
                  .replace(/\.tsx?$/, "")
                  .replaceAll("\\", "/"),
          )
          .map((entry) => entry.file),
      ),
    ],
  }));
}

export function routeTypes() {
  const lines = [
    "// Generated from docs/api/openapi.json. Run npm run api:frontend:generate.",
    "// This checks HTTP methods and paths; DTO mappings remain in domain adapters.",
    "export interface ApiRoutes {",
  ];
  for (const method of verbs) {
    const routes = operations
      .filter((operation) => operation.method === method)
      .map((operation) => {
        const literal = operation.path.replace(/\{[^}]+\}/g, "${string}");
        return `    | \`${literal}\``;
      });
    lines.push(`  ${method}:`, ...(routes.length ? routes : ["    never"]), "  ;");
  }
  lines.push(
    "}",
    "",
    "export type ApiPath<M extends keyof ApiRoutes> = ApiRoutes[M] | `${ApiRoutes[M]}?${string}`;",
    "",
  );
  return lines.join("\n");
}

export function coverageReport(calls) {
  const review = JSON.parse(
    fs.readFileSync(path.join(root, "docs/api/frontend-api-review.json"), "utf8"),
  );
  const infrastructure = new Set([
    "apiGet",
    "apiPost",
    "apiPatch",
    "apiPut",
    "apiDelete",
    "apiUpload",
    "apiPostNoBody",
  ]);
  for (const key of Object.keys(review.operations)) {
    if (!operations.some((op) => op.key === key)) throw new Error(`Stale API review: ${key}`);
  }
  for (const call of calls.filter((item) => !item.operations.length)) {
    if (call.file === "src/api/http.ts" && infrastructure.has(call.owner)) continue;
    const key = review.dynamicCalls[`${call.file}#${call.owner}`];
    if (
      !key ||
      call.path !== "{*}" ||
      !operations.some((op) => op.key === key && op.method === call.method)
    )
      throw new Error(`Unmatched request: ${call.file}#${call.owner} ${call.method} ${call.path}`);
  }
  for (const [owner, key] of Object.entries(review.dynamicCalls)) {
    if (!calls.some((call) => `${call.file}#${call.owner}` === owner))
      throw new Error(`Stale dynamic binding: ${owner}`);
    if (!operations.some((op) => op.key === key))
      throw new Error(`Unknown dynamic operation: ${key}`);
  }
  const rows = operations.map((op) => {
    const adapters = calls.filter((call) => call.operations.includes(op.key));
    const reviewed = review.operations[op.key];
    if (!reviewed && !adapters.some((call) => call.consumers.length))
      throw new Error(`API has no frontend consumer or review: ${op.key}`);
    return {
      ...op,
      status: reviewed?.status ?? "静态调用已接入",
      note: reviewed?.note ?? "已找到请求封装及直接引用；实际按钮、权限和响应行为由页面测试验证。",
      adapters,
    };
  });
  const counts = rows.reduce(
    (result, row) => ({ ...result, [row.status]: (result[row.status] ?? 0) + 1 }),
    {},
  );
  const lines = [
    "# 前端与后端接口对照",
    "",
    "由 `npm run api:frontend:generate` 生成，契约来源 `docs/api/openapi.json`，人工复核来源 `frontend-api-review.json`。",
    "",
    `共 ${rows.length} 个 HTTP 操作；` +
      Object.entries(counts)
        .map(([status, count]) => `${status} ${count}`)
        .join("，") +
      "。",
    "",
    "静态调用仅表示找到了封装及直接导入/转导出，不代表每个接口都有独立按钮，也不证明真实环境全流程通过。动态资源单列；请求/响应 DTO 仍由领域适配器和测试校验。",
    "",
    "## 需要补充或评估的入口",
    "",
    "以下保持现有功能与权限，不在重构时自动新增高影响操作。",
    "",
    "| 接口 | 状态 | 缺口及建议位置 |",
    "| --- | --- | --- |",
  ];
  for (const row of rows.filter((row) => ["未接入", "部分覆盖"].includes(row.status)))
    lines.push(`| \`${row.key}\` | ${row.status} | ${row.note} |`);
  lines.push(
    "",
    "## 全部接口",
    "",
    "| 接口 | 状态 | 请求位置 → 直接调用方 | 说明 |",
    "| --- | --- | --- | --- |",
  );
  for (const row of rows) {
    const locations = row.adapters.map(
      (call) =>
        `\`${call.file}#${call.owner}\` → ${call.consumers.map((file) => `\`${file}\``).join("、") || "模块内部 / 暂无直接引用"}`,
    );
    lines.push(
      `| \`${row.key}\` | ${row.status} | ${[...new Set(locations)].join("<br>") || "见说明"} | ${row.note} |`,
    );
  }
  return lines.join("\n") + "\n";
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const calls = scanRequests();
  if (process.argv.includes("--inspect")) {
    console.log(
      JSON.stringify(
        {
          total: operations.length,
          calls: calls.length,
          unmatched: calls.filter((call) => !call.operations.length),
          withoutAdapter: operations.filter(
            (op) => !calls.some((call) => call.operations.includes(op.key)),
          ),
          unusedAdapters: calls.filter((call) => call.operations.length && !call.consumers.length),
        },
        null,
        2,
      ),
    );
  } else {
    const target = path.join(root, "src/api/generated/routes.ts");
    const prettier = await import("prettier");
    const text = await prettier.format(routeTypes(), {
      ...(await prettier.resolveConfig(target)),
      parser: "typescript",
    });
    const outputs = [
      [target, text],
      [path.join(root, "docs/api/FRONTEND_API_COVERAGE.md"), coverageReport(calls)],
    ];
    for (const [file, content] of outputs) {
      if (process.argv.includes("--check")) {
        if (
          !fs.existsSync(file) ||
          fs.readFileSync(file, "utf8").replaceAll("\r\n", "\n") !== content
        )
          throw new Error(
            `Frontend API contract drifted: ${path.relative(root, file)}; run npm run api:frontend:generate`,
          );
      } else {
        fs.mkdirSync(path.dirname(file), { recursive: true });
        fs.writeFileSync(file, content);
      }
    }
    console.log(
      `Frontend API contract: ${operations.length} operations, all calls matched or explicitly reviewed.`,
    );
  }
}
