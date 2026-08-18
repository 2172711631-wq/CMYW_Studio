/**
 * 站点通用交互：语言切换、导航状态、滚动淡入、夜色氛围。
 * Shared site behaviour — language toggle, nav state, scroll reveals, night ambience.
 *
 * 所有动效都尊重 prefers-reduced-motion：关掉后页面依然完整可用，
 * 只是不动。氛围是加分项，不能是阅读的前提。
 */

import { initAtmosphere } from "./atmosphere";

const LANG_KEY = "tl-lang";
type Lang = "zh-CN" | "en";

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
initNav();
initReveal();

const sky = document.querySelector<HTMLCanvasElement>("canvas.atmosphere");
if (sky) initAtmosphere(sky, Number(sky.dataset.density ?? 1));
