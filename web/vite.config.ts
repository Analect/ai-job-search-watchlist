import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // See insurance-support-agent/web/vite.config.ts for why this reads
  // process.env directly rather than relying on Vite's own .env
  // auto-loading — the same OpenChoreo shared-hostname/basePath
  // convention applies here.
  base: process.env.VITE_BASE_PATH || "/",
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: { port: 5174, host: true },
});
