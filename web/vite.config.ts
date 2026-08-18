import { defineConfig } from "vite";

export default defineConfig({
  // Cloudflare Pages 直接发布 dist/，无需服务端
  build: {
    target: "es2022",
    outDir: "dist",
    assetsInlineLimit: 4096,
  },
  worker: { format: "es" },
});
