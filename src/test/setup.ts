// Vitest 全局测试初始化：注册 jest-dom 断言（toBeInTheDocument 等），
// 每个用例后清理已挂载的 React 树，避免测试间相互污染。
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});
