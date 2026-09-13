import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:4318",
        changeOrigin: true,
        timeout: 0,
        configure(proxy) {
          proxy.on("proxyRes", (proxyRes, _req, res) => {
            if (String(proxyRes.headers["content-type"] || "").includes("text/event-stream")) {
              res.setHeader("Cache-Control", "no-cache, no-transform");
              res.setHeader("X-Accel-Buffering", "no");
            }
          });
        },
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
