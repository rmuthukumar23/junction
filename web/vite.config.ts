import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// `npm run dev` serves the site on :5173 and forwards /api to the Python server
// (scripts/pixel/server.py, default :8800; override with PIXEL_API=http://127.0.0.1:8812).
const api = process.env.PIXEL_API || "http://127.0.0.1:8800";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: { proxy: { "/api": api } },
  build: { outDir: "dist", assetsInlineLimit: 0 },
  test: { environment: "node" },
});
