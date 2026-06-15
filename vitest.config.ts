import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// 组件冒烟测试：jsdom 环境 + @testing-library/react。只验证 UI 组件渲染与
// 基本交互，不 mock 后端、不触达网络。
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
