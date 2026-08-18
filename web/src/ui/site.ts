/**
 * 站点通用交互：语言切换、导航状态、滚动淡入、萤火虫。
 * Shared site behaviour — language toggle, nav state, scroll reveals, fireflies.
 *
 * 所有动效都尊重 prefers-reduced-motion：关掉后页面依然完整可用，
 * 只是不动。氛围是加分项，不能是阅读的前提。
 */

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

/* ---------------- 萤火虫 ---------------- */

interface Fly {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  phase: number;
  speed: number;
}

/**
 * 夏夜的那几点光。
 *
 * 分三档大小：近处的大而亮、远处的小而暗，靠这个拉出景深，
 * 比同样大小放一堆更像真的。飘得依然很慢 —— 速度一快就成了雪花。
 */
function initFirefliesOn(canvas: HTMLCanvasElement, density: number): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  let flies: Fly[] = [];
  let raf = 0;
  let running = true;

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const { width, height } = canvas.getBoundingClientRect();
    if (width === 0 || height === 0) return;
    canvas.width = Math.max(1, Math.floor(width * dpr));
    canvas.height = Math.max(1, Math.floor(height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // 按面积算数量，大屏不至于显得稀疏，小屏不至于糊住内容
    const base = Math.sqrt((width * height) / 90000);
    const count = Math.round(Math.min(46, Math.max(9, base * density)));

    flies = Array.from({ length: count }, () => {
      // 三档景深：远 / 中 / 近
      const depth = Math.random();
      const near = depth > 0.82 ? 2 : depth > 0.45 ? 1 : 0;
      const scale = [0.62, 1, 1.55][near];
      return {
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.18 * scale,
        vy: (Math.random() - 0.5) * 0.13 * scale,
        r: (0.9 + Math.random() * 1.3) * scale,
        phase: Math.random() * Math.PI * 2,
        speed: 0.42 + Math.random() * 0.8,
      };
    });
  };

  const frame = (t: number) => {
    if (!running) return;
    const { width, height } = canvas.getBoundingClientRect();
    ctx.clearRect(0, 0, width, height);

    for (const f of flies) {
      f.x += f.vx;
      f.y += f.vy;
      // 缓慢转向，避免直线飞行的机械感
      f.vx += (Math.random() - 0.5) * 0.006;
      f.vy += (Math.random() - 0.5) * 0.006;
      f.vx = Math.max(-0.24, Math.min(0.24, f.vx));
      f.vy = Math.max(-0.2, Math.min(0.2, f.vy));

      if (f.x < -20) f.x = width + 20;
      if (f.x > width + 20) f.x = -20;
      if (f.y < -20) f.y = height + 20;
      if (f.y > height + 20) f.y = -20;

      const pulse = 0.3 + 0.7 * (0.5 + 0.5 * Math.sin(t * 0.001 * f.speed + f.phase));
      const rad = f.r * 8;
      const glow = ctx.createRadialGradient(f.x, f.y, 0, f.x, f.y, rad);
      glow.addColorStop(0, `rgba(255, 226, 172, ${0.72 * pulse})`);
      glow.addColorStop(0.28, `rgba(255, 190, 120, ${0.3 * pulse})`);
      glow.addColorStop(1, "rgba(255, 177, 107, 0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(f.x, f.y, rad, 0, Math.PI * 2);
      ctx.fill();

      // 中心一点实心亮核，远看才像"一只虫"而不是一团雾
      ctx.fillStyle = `rgba(255, 240, 205, ${0.85 * pulse})`;
      ctx.beginPath();
      ctx.arc(f.x, f.y, f.r * 0.55, 0, Math.PI * 2);
      ctx.fill();
    }
    raf = requestAnimationFrame(frame);
  };

  resize();
  window.addEventListener("resize", resize, { passive: true });

  // 页面不可见时停掉，别空耗电池
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      running = false;
      cancelAnimationFrame(raf);
    } else if (!running) {
      running = true;
      raf = requestAnimationFrame(frame);
    }
  });

  raf = requestAnimationFrame(frame);
}

function initFireflies(): void {
  if (prefersReduced()) return;
  document
    .querySelectorAll<HTMLCanvasElement>("canvas.fireflies")
    .forEach((c) => initFirefliesOn(c, Number(c.dataset.density ?? 14)));
}

initLang();
initNav();
initReveal();
initFireflies();
