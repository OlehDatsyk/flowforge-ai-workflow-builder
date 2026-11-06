import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/hooks": "http://localhost:8000",
    },
  },
  build: { chunkSizeWarningLimit: 900 },
  test: { include: ["src/**/*.test.ts"], environment: "node" },
});
