import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  // Cloudflare Pages 直接发布 dist/，全站静态，无服务端
  build: {
    target: "es2022",
    outDir: "dist",
    assetsInlineLimit: 4096,
    rollupOptions: {
      input: {
        index: resolve(__dirname, "index.html"),
        studio: resolve(__dirname, "studio.html"),
      },
    },
  },
  worker: { format: "es" },
});
