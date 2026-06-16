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
    // 覆盖率基线（首阶段只观测、不设硬性阈值）。
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
      // 测试 / 类型声明 / 纯 DTO 类型 / 入口装配不计入业务覆盖率。
      // src/types/** 是纯 interface/type 声明（编译期擦除、无运行时语句），计入只会以 0%
      // 稀释基线，故排除。
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/test/**",
        "src/**/*.d.ts",
        "src/types/**",
        "src/main.tsx",
      ],
    },
  },
});
