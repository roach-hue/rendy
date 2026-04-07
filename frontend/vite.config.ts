import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: "http://localhost:8001",
        timeout: 300000,  // 5분 — LLM 호출 + rate limit 대기 포함
      },
    },
  },
});
