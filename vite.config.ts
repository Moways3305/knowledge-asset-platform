import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发态：把 /api 代理到 Docker 后端（当前宿主机映射 http://localhost:8001）。
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
      },
    },
  },
});
