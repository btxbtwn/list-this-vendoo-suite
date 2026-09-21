import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const ROOT = import.meta.dirname;

// The bundle carries the identity of the tree it was built from. The backend
// reads VERSION straight off disk, so without this the two can drift apart and
// the app serves a months-old UI under a current version number.
function buildStamp() {
  const version = readFileSync(resolve(ROOT, "VERSION"), "utf-8").trim();
  let sha = "";
  try {
    sha = execFileSync("git", ["rev-parse", "HEAD"], { cwd: ROOT, encoding: "utf-8" }).trim();
  } catch {
    // Source drops without git history still build; the version check covers them.
  }
  return { version, sha, short_sha: sha.slice(0, 7), built_at: new Date().toISOString() };
}

const stamp = buildStamp();

export default defineConfig({
  define: { __STUDIO_BUILD__: JSON.stringify(stamp) },
  plugins: [
    react(),
    {
      // Written beside index.html so the Python launcher can compare the built
      // bundle against the checkout before it opens a window.
      name: "studio-build-stamp",
      apply: "build",
      generateBundle() {
        this.emitFile({
          type: "asset",
          fileName: "build-stamp.json",
          source: JSON.stringify(stamp, null, 2) + "\n",
        });
      },
    },
  ],
  server: {
    port: 5173,
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
