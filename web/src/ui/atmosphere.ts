/**
 * 夜色氛围层 —— 星、远处的灯、萤火虫。
 * The night layer: stars, a lamp somewhere, and fireflies.
 *
 * 之前每个区块自己挂一张 canvas，结果只有首屏和末屏有萤火虫，中间一大段是空的，
 * 滚下去像忽然走出了那个夜晚。现在整页只有一张 fixed 画布铺在内容后面，
 * 一次 rAF 管到底 —— 既连贯，也比原来两个循环更省。
 *
 * 三层各自负责一件事，合起来才有纵深：
 *   星   —— 最远，几乎不动，只随滚动挪一点点，负责"天还在那儿"
 *   灯   —— 中景，两团很大很淡的暖光缓慢漂移，负责"远处有人点着灯"
 *   萤火虫 —— 近景，会飘会呼吸，负责"这个夜晚是活的"
 *
 * 视差按层给：滚动时近的挪得多、远的挪得少，页面就有了前后关系，
 * 而不是一张贴在背景上的图。
 */

const prefersReduced = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** 画布外多留一圈，粒子在边界回绕时不会当着人的面凭空出现。 */
const PAD = 80;

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  phase: number;
  speed: number;
  /** 视差系数：0 = 完全不随滚动移动，1 = 跟着页面一起走 */
  par: number;
  alpha: number;
}

/**
 * 把一团发光预先画进离屏画布。
 *
 * 每帧给每个粒子 createRadialGradient 是这类效果最大的一笔开销，
 * 而且它随粒子数线性增长。预渲染一次之后每帧只剩 drawImage，
 * 数量翻一倍也感觉不到 —— 现在的密度正是靠这个换来的。
 */
function glowSprite(stops: Array<[number, string]>, size = 128): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = size;
  c.height = size;
  const g = c.getContext("2d");
  if (!g) return c;
  const half = size / 2;
  const grad = g.createRadialGradient(half, half, 0, half, half, half);
  for (const [at, colour] of stops) grad.addColorStop(at, colour);
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  return c;
}

/**
 * @param density 数量系数。制作台是干活的地方，压到一半就够了 ——
 *   氛围是背景，不该跟预览里的颜色抢注意力。
 */
export function initAtmosphere(canvas: HTMLCanvasElement, density = 1): void {
  const ctx = canvas.getContext("2d", { alpha: true });
  if (!ctx || prefersReduced()) return;

  const firefly = glowSprite([
    [0, "rgba(255, 240, 205, 1)"],
    [0.16, "rgba(255, 226, 172, 0.66)"],
    [0.42, "rgba(255, 190, 120, 0.20)"],
    [1, "rgba(255, 177, 107, 0)"],
  ]);
  // 星星偏冷：夏夜的天光是靛蓝的，暖白星会和萤火虫糊成一片，分不出远近
  const star = glowSprite([
    [0, "rgba(226, 236, 255, 1)"],
    [0.3, "rgba(190, 210, 255, 0.42)"],
    [1, "rgba(160, 190, 255, 0)"],
  ], 64);
  const lamp = glowSprite([
    [0, "rgba(255, 186, 120, 0.5)"],
    [0.45, "rgba(255, 160, 96, 0.16)"],
    [1, "rgba(255, 140, 80, 0)"],
  ], 256);

  let stars: Particle[] = [];
  let lamps: Particle[] = [];
  let flies: Particle[] = [];
  let width = 0;
  let height = 0;
  let raf = 0;
  let running = true;

  const rand = (lo: number, hi: number) => lo + Math.random() * (hi - lo);

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = window.innerWidth;
    const h = window.innerHeight;
    if (w === 0 || h === 0) return;

    // 手机上地址栏一收一放就触发 resize。每次都重撒粒子的话，
    // 一边滚一边有整片萤火虫在瞬移 —— 所以只有真的换了尺寸才重来。
    const reseed = stars.length === 0 || w !== width || Math.abs(h - height) > 140;
    width = w;
    height = h;
    canvas.width = Math.max(1, Math.floor(width * dpr));
    canvas.height = Math.max(1, Math.floor(height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!reseed) return;

    // 数量按面积走：大屏不至于稀疏，手机上不至于糊住字
    const area = ((width * height) / 90000) * density;

    stars = Array.from({ length: Math.round(Math.min(90, Math.max(24 * density, area * 9))) }, () => ({
      x: rand(0, width),
      y: rand(0, height),
      vx: 0,
      vy: 0,
      r: rand(0.5, 1.5),
      phase: rand(0, Math.PI * 2),
      speed: rand(0.12, 0.45),
      par: rand(0.02, 0.07),
      alpha: rand(0.22, 0.6),
    }));

    lamps = Array.from({ length: 2 }, (_, i) => ({
      x: rand(width * 0.12, width * 0.88),
      y: rand(height * 0.2, height * 0.8),
      vx: rand(-0.05, 0.05),
      vy: rand(-0.03, 0.03),
      r: rand(180, 320) * (i === 0 ? 1.25 : 1),
      phase: rand(0, Math.PI * 2),
      speed: rand(0.05, 0.12),
      par: rand(0.1, 0.18),
      alpha: rand(0.5, 0.85),
    }));

    flies = Array.from({ length: Math.round(Math.min(58, Math.max(14 * density, area * 16))) }, () => {
      // 三档景深：远 / 中 / 近。同样大小放一堆就只是一片点，不是夜晚。
      const d = Math.random();
      const tier = d > 0.82 ? 2 : d > 0.45 ? 1 : 0;
      const scale = [0.62, 1, 1.55][tier];
      return {
        x: rand(0, width),
        y: rand(0, height),
        vx: rand(-0.09, 0.09) * scale,
        vy: rand(-0.065, 0.065) * scale,
        r: rand(0.9, 2.2) * scale,
        phase: rand(0, Math.PI * 2),
        speed: rand(0.42, 1.22),
        par: [0.1, 0.24, 0.44][tier],
        alpha: [0.55, 0.8, 1][tier],
      };
    });
  };

  /** 把视差后的坐标绕回可视范围，滚多远都不会跑出画面。 */
  const wrap = (v: number, span: number) => {
    const total = span + PAD * 2;
    return ((((v + PAD) % total) + total) % total) - PAD;
  };

  const blit = (
    sprite: HTMLCanvasElement, x: number, y: number, radius: number, alpha: number,
  ) => {
    if (alpha <= 0.004) return;
    ctx.globalAlpha = alpha;
    ctx.drawImage(sprite, x - radius, y - radius, radius * 2, radius * 2);
  };

  const frame = (t: number) => {
    if (!running) return;
    const scroll = window.scrollY;
    ctx.clearRect(0, 0, width, height);
    ctx.globalCompositeOperation = "lighter";

    // ---- 远：星 ----
    for (const s of stars) {
      const twinkle = 0.55 + 0.45 * Math.sin(t * 0.001 * s.speed + s.phase);
      blit(star, s.x, wrap(s.y - scroll * s.par, height), s.r * 5, s.alpha * twinkle);
    }

    // ---- 中：远处的灯 ----
    for (const l of lamps) {
      l.x += l.vx;
      l.y += l.vy;
      if (l.x < -l.r) l.x = width + l.r;
      if (l.x > width + l.r) l.x = -l.r;
      const breath = 0.72 + 0.28 * Math.sin(t * 0.001 * l.speed + l.phase);
      blit(lamp, l.x, wrap(l.y - scroll * l.par, height), l.r, 0.1 * l.alpha * breath);
    }

    // ---- 近：萤火虫 ----
    for (const f of flies) {
      f.x += f.vx;
      f.y += f.vy;
      // 缓慢转向，不然就是一群沿直线飞的点，机械得很明显
      f.vx = Math.max(-0.14, Math.min(0.14, f.vx + (Math.random() - 0.5) * 0.005));
      f.vy = Math.max(-0.11, Math.min(0.11, f.vy + (Math.random() - 0.5) * 0.005));
      if (f.x < -PAD) f.x = width + PAD;
      if (f.x > width + PAD) f.x = -PAD;
      f.y = wrap(f.y, height);

      const pulse = 0.26 + 0.74 * (0.5 + 0.5 * Math.sin(t * 0.001 * f.speed + f.phase));
      const y = wrap(f.y - scroll * f.par, height);
      blit(firefly, f.x, y, f.r * 8, 0.62 * f.alpha * pulse);

      // 中心一点实心亮核：远看才像"一只虫"，而不是一团雾
      ctx.globalAlpha = 0.9 * f.alpha * pulse;
      ctx.fillStyle = "rgba(255, 244, 214, 1)";
      ctx.beginPath();
      ctx.arc(f.x, y, f.r * 0.5, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    raf = requestAnimationFrame(frame);
  };

  resize();
  window.addEventListener("resize", resize, { passive: true });

  // 标签页切走就停，别在后台空耗电池
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
