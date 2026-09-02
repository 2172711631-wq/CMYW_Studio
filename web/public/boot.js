/**
 * 首屏引导：主题 + 可选的访问统计。
 *
 * 必须在第一次绘制之前跑完，所以它是 <head> 里的同步脚本，不能 defer。
 *
 * 为什么是独立文件而不是内联：站点的 CSP 是 script-src 'self'，
 * 内联脚本会被浏览器直接拒掉 —— 内联版本本地开发时看着正常（vite dev 不发这条头），
 * 一上线就静悄悄失效，页面会先按夜色画一帧再跳成白天。
 */
(function () {
  /* ---------------- 主题 ---------------- */
  // 没自己选过就跟着系统深浅色走；选过就以选的为准。
  var saved = null;
  try {
    saved = localStorage.getItem("tl-theme");
  } catch (e) {
    /* 无痕窗口里读不到，按系统来 */
  }
  var day = saved
    ? saved === "day"
    : window.matchMedia("(prefers-color-scheme: light)").matches;
  if (day) document.documentElement.dataset.theme = "day";
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = day ? "#F7F2E8" : "#161E36";

  /* ---------------- 访问统计 ---------------- */
  // 把 Cloudflare Web Analytics 的 token 填进下面这行就生效。
  // 留空时一个第三方请求都不会发出 —— 这样"不填"是真的什么都不加载，
  // 而不是加载了一个没用的脚本。
  //
  // token 在 Cloudflare 控制台 → Web Analytics → 选站点 → JS snippet 里，
  // 形如 data-cf-beacon='{"token": "xxxxxxxx"}' 里的那串。
  //
  // 它无 Cookie、不做跨站跟踪、只出聚合数字，和 PRIVACY.zh-CN.md
  // 第二节里写的"如启用了统计工具 / 聚合数据，不含个人身份"是一致的。
  var CF_ANALYTICS_TOKEN = "";

  if (CF_ANALYTICS_TOKEN) {
    var s = document.createElement("script");
    s.defer = true;
    s.src = "https://static.cloudflareinsights.com/beacon.min.js";
    s.setAttribute("data-cf-beacon", JSON.stringify({ token: CF_ANALYTICS_TOKEN }));
    document.head.appendChild(s);
  }
})();
