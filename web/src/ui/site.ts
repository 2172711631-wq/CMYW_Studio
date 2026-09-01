/**
 * 站点通用交互：语言切换、昼夜切换、导航状态、滚动淡入、氛围层。
 * Shared site behaviour — language, day/night, nav state, scroll reveals, ambience.
 *
 * 所有动效都尊重 prefers-reduced-motion：关掉后页面依然完整可用，
 * 只是不动。氛围是加分项，不能是阅读的前提。
 */

import { initAtmosphere } from "./atmosphere";

const LANG_KEY = "tl-lang";
const THEME_KEY = "tl-theme";
type Lang = "zh-CN" | "en";
type Theme = "night" | "day";

const prefersReduced = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------------- 语言 ---------------- */

function detectLang(): Lang {
  const saved = localStorage.getItem(LANG_KEY);
  if (saved === "zh-CN" || saved === "en") return saved;
  return navigator.language.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
}

function applyLang(lang: Lang): void {
  document.documentElement.lang = lang;
  localStorage.setItem(LANG_KEY, lang);
  document.querySelectorAll<HTMLButtonElement>("[data-set-lang]").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.setLang === lang));
  });
  // 标题也跟着切，分享出去时才对得上
  const title = document.querySelector<HTMLElement>("[data-title-zh]");
  if (title) {
    const next = lang === "zh-CN" ? title.dataset.titleZh : title.dataset.titleEn;
    if (next) document.title = next;
  }
}

function initLang(): void {
  applyLang(detectLang());
  document.querySelectorAll<HTMLButtonElement>("[data-set-lang]").forEach((btn) => {
    btn.addEventListener("click", () => applyLang(btn.dataset.setLang as Lang));
  });
}

/* ---------------- 昼夜 ---------------- */

/**
 * 首屏用哪套主题是 HTML 里那一小段内联脚本定的，这里只接手之后的切换。
 * 分两处写是刻意的：属性必须在第一次绘制之前落到 <html> 上，而这个模块是
 * 模块脚本、天生 defer，等它跑起来页面已经按夜色画过一帧，会看见一次闪白。
 *
 * 夜色是 CSS 里的默认（:root 就是夜，只有白天需要一层覆盖），所以选中夜色时
 * 是删掉属性而不是写 data-theme="night"。这跟"默认跟随系统"不冲突：
 * 跟随发生在赋值那一步，不在样式表里。
 */
function applyTheme(theme: Theme, persist: boolean): void {
  const root = document.documentElement;
  if (theme === "day") root.dataset.theme = "day";
  else delete root.dataset.theme;

  if (persist) {
    // 无痕窗口里 localStorage 会直接抛错。存不下就只影响下次进来，这次照样切。
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
  }

  document.querySelectorAll<HTMLButtonElement>("[data-toggle-theme]").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(theme === "day"));
  });
  // 手机浏览器的地址栏颜色，不跟着换会在页面顶上留一条另一个时辰的边
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (meta) meta.content = theme === "day" ? "#F7F2E8" : "#161E36";
}

function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "day" ? "day" : "night";
}

/** 用户自己选过的那一套；没选过返回 null，此时一切听系统的。 */
function storedTheme(): Theme | null {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return v === "day" || v === "night" ? v : null;
  } catch {
    return null;
  }
}

function initTheme(): void {
  applyTheme(currentTheme(), false);
  document.querySelectorAll<HTMLButtonElement>("[data-toggle-theme]").forEach((btn) => {
    btn.addEventListener("click", () => {
      applyTheme(currentTheme() === "day" ? "night" : "day", true);
    });
  });

  // 系统在日落时自己切深色，开着的页面也跟着换 —— 但只在用户还没表过态的时候。
  // 一旦点过那个按钮，就以他点的为准，系统怎么变都不再抢方向盘。
  window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", (e) => {
    if (storedTheme() === null) applyTheme(e.matches ? "day" : "night", false);
  });
}

/* ---------------- 导航 ---------------- */

function initNav(): void {
  const nav = document.getElementById("nav");
  if (!nav) return;
  const update = () => nav.setAttribute("data-scrolled", String(window.scrollY > 12));
  update();
  window.addEventListener("scroll", update, { passive: true });
}

/* ---------------- 滚动淡入 ---------------- */

function initReveal(): void {
  const targets = document.querySelectorAll("[data-reveal]");
  if (targets.length === 0) return;

  if (prefersReduced() || !("IntersectionObserver" in window)) {
    targets.forEach((el) => el.classList.add("is-in"));
    return;
  }

  const io = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("is-in");
        io.unobserve(entry.target);
      }
    },
    { rootMargin: "0px 0px -12% 0px", threshold: 0.08 },
  );
  targets.forEach((el) => io.observe(el));
}

initLang();
initTheme();
initNav();
initReveal();

const sky = document.querySelector<HTMLCanvasElement>("canvas.atmosphere");
if (sky) initAtmosphere(sky, Number(sky.dataset.density ?? 1));
