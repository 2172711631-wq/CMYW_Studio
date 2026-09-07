import { execSync } from "node:child_process";
import { resolve } from "node:path";
import { defineConfig } from "vite";

/** 构建代号：提交号 + 构建时刻。
 *
 * 页面上看得见，也写进 <meta name="build">，所以"线上到底是不是最新的"
 * 不用再靠肉眼比画面 —— 刷新一下看代号变没变就行。
 *
 * Cloudflare Pages 在构建时给 CF_PAGES_COMMIT_SHA；本地没有就问 git。
 * 两个都拿不到（比如从压缩包构建）就写 dev，不让构建因为这个失败。
 */
function buildId(): string {
  let sha = process.env.CF_PAGES_COMMIT_SHA ?? "";
  if (!sha) {
    try {
      sha = execSync("git rev-parse HEAD", { encoding: "utf8" }).trim();
    } catch {
      sha = "";
    }
  }
  const short = sha ? sha.slice(0, 7) : "dev";
  const now = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  const stamp = `${p(now.getUTCMonth() + 1)}-${p(now.getUTCDate())} `
    + `${p(now.getUTCHours())}:${p(now.getUTCMinutes())}Z`;
  return `${short} · ${stamp}`;
}

/** 把构建代号写进每个页面的 <meta name="build">。
 *
 * 写在 HTML 里而不是 JS 里，是为了 curl 一下就能读到 —— 要判断"线上更新了没"，
 * 不该需要先把整个页面跑起来。界面上那行字也从这个 meta 读，一处来源。 */
function stampBuild(id: string) {
  return {
    name: "stamp-build",
    transformIndexHtml(html: string) {
      return html.replace(
        "<head>",
        `<head>
<meta name="build" content="${id}" />`,
      );
    },
  };
}

export default defineConfig({
  plugins: [stampBuild(buildId())],
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
