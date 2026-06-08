import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发态：把 /api 代理到 Docker 后端（当前宿主机映射 http://localhost:8001）。
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 后端 API。生产由 nginx 同源反代，这里在 dev 下对齐到 docker 后端宿主映射。
      "/api": { target: "http://127.0.0.1:8001", changeOrigin: true },
      // 运营端点挂在 /admin/ops（非 /api）；SPA 路由是 /admin/ingest 等，不会命中 /admin/ops。
      "/admin/ops": { target: "http://127.0.0.1:8001", changeOrigin: true },
      // 健康探针。
      "/health": { target: "http://127.0.0.1:8001", changeOrigin: true },
    },
  },
});
