// ESLint 扁平配置（flat config）。规则集：JS recommended + typescript-eslint
// recommended + React Hooks 经典两条规则（rules-of-hooks 报错、exhaustive-deps 警告）。
// 目标是在不改写既有可用代码、不大面积关闭规则的前提下，捕获真实问题
// （未用变量、违反 Hooks 调用规则、明显的类型隐患）。
//
// 说明：未采用 eslint-plugin-react-hooks@7 的完整 recommended 集，因为其新增的
// set-state-in-effect / 多条 react-compiler 风格规则仍属激进/争议，会对受控输入
// 同步、挂载即加载等惯用写法大量误报；这里只启用业界长期稳定的两条 Hooks 规则。
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default tseslint.config(
  // 不纳入 lint 的产物 / 配置目录。
  {
    ignores: ["dist", "node_modules", ".claude", "coverage", "scripts"],
  },
  // 应用源码（浏览器环境）。
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      // 未使用变量：允许以下划线开头的占位参数（与既有写法兼容）。
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  // 测试文件：放开 jsdom + node 全局（断言/钩子仍从 vitest 显式 import）。
  {
    files: ["src/**/*.test.{ts,tsx}", "src/test/**/*.{ts,tsx}"],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
  },
);
