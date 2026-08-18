/**
 * 立体预览 —— 原生 WebGL2，不引任何 3D 库。
 * 3D preview, written straight against WebGL2 — no third-party renderer.
 *
 * 旧站的做法是「服务器用 trimesh 拼一个 GLB → 浏览器加载 935KB 的 model-viewer」。
 * 那条路两头都贵：我的机器要算，访客要下近 1MB 的库。
 *
 * 这里换成：外壳网格直接复用打印用的 buildShellMesh（所以看到的就是会打出来的
 * 形状），画片是一块圆角薄板，**贴图直接用全分辨率的透光模拟图** ——
 * 清晰度一格都没降，只是把它放进了三维里。着色器自己写，压缩后不到 6KB。
 *
 * 性能上刻意做了三件事：
 *   1. WebGL 上下文**按需创建** —— 不点「立体」就一点开销都没有
 *   2. 只在需要时渲染（拖动中 / 自转中 / 场景变了），不挂常驻 rAF
 *   3. 几何一次上传，改视角只更新一个矩阵
 */

import { SHELL_DEFAULTS, buildShellMesh, type ShellParams } from "./shell";

/** 画片圆角的细分段数。比打印网格更密，纯粹为了看着圆。 */
const PANEL_ARC_SEGMENTS = 24;

/** 外壳按 0.2mm 层高打，画片才是 0.08 —— 层纹要按外壳自己的层高画。 */
const SHELL_LAYER_MM = 0.2;

export interface Preview3DShell {
  wall: number;
  depth: number;
  corner: number;
  clearance: number;
  colorHex: string;
}

export interface Preview3DScene {
  /** 点亮后的模拟图，原分辨率，不缩放 */
  image: ImageData;
  artW: number;
  artH: number;
  /** 画片实际厚度（层数 × 层高） */
  artThicknessMm: number;
  shell: Preview3DShell | null;
}

/* ============================ 矩阵 ============================ */
/* 列主序，与 uniformMatrix4fv(transpose = false) 一致 */

type Mat4 = Float32Array;
type Vec3 = [number, number, number];

function perspective(fovY: number, aspect: number, near: number, far: number): Mat4 {
  const f = 1 / Math.tan(fovY / 2);
  const nf = 1 / (near - far);
  return new Float32Array([
    f / aspect, 0, 0, 0,
    0, f, 0, 0,
    0, 0, (far + near) * nf, -1,
    0, 0, 2 * far * near * nf, 0,
  ]);
}

function lookAt(eye: Vec3, target: Vec3, up: Vec3): Mat4 {
  const z: Vec3 = [eye[0] - target[0], eye[1] - target[1], eye[2] - target[2]];
  let len = Math.hypot(z[0], z[1], z[2]) || 1;
  z[0] /= len; z[1] /= len; z[2] /= len;

  const x: Vec3 = [
    up[1] * z[2] - up[2] * z[1],
    up[2] * z[0] - up[0] * z[2],
    up[0] * z[1] - up[1] * z[0],
  ];
  len = Math.hypot(x[0], x[1], x[2]) || 1;
  x[0] /= len; x[1] /= len; x[2] /= len;

  const y: Vec3 = [
    z[1] * x[2] - z[2] * x[1],
    z[2] * x[0] - z[0] * x[2],
    z[0] * x[1] - z[1] * x[0],
  ];

  return new Float32Array([
    x[0], y[0], z[0], 0,
    x[1], y[1], z[1], 0,
    x[2], y[2], z[2], 0,
    -(x[0] * eye[0] + x[1] * eye[1] + x[2] * eye[2]),
    -(y[0] * eye[0] + y[1] * eye[1] + y[2] * eye[2]),
    -(z[0] * eye[0] + z[1] * eye[1] + z[2] * eye[2]),
    1,
  ]);
}

function multiply(a: Mat4, b: Mat4): Mat4 {
  const out = new Float32Array(16);
  for (let c = 0; c < 4; c += 1) {
    for (let r = 0; r < 4; r += 1) {
      out[c * 4 + r] =
        a[r] * b[c * 4] +
        a[4 + r] * b[c * 4 + 1] +
        a[8 + r] * b[c * 4 + 2] +
        a[12 + r] * b[c * 4 + 3];
    }
  }
  return out;
}

/* ============================ 几何 ============================ */

/**
 * 展开成不共享顶点的三角形，每个面自带面法线。
 *
 * FDM 件本来就是一层层平面堆出来的，平面着色比插值法线更像实物；
 * 顺带省掉了「按夹角决定要不要合并法线」那套判断。外壳才几百个三角形，
 * 顶点翻三倍也无所谓。
 */
function flatShade(vertices: Float64Array, indices: Uint32Array) {
  const triCount = indices.length / 3;
  const pos = new Float32Array(triCount * 9);
  const nrm = new Float32Array(triCount * 9);

  for (let t = 0; t < triCount; t += 1) {
    const ia = indices[t * 3] * 3;
    const ib = indices[t * 3 + 1] * 3;
    const ic = indices[t * 3 + 2] * 3;

    const ax = vertices[ia], ay = vertices[ia + 1], az = vertices[ia + 2];
    const bx = vertices[ib], by = vertices[ib + 1], bz = vertices[ib + 2];
    const cx = vertices[ic], cy = vertices[ic + 1], cz = vertices[ic + 2];

    const ux = bx - ax, uy = by - ay, uz = bz - az;
    const vx = cx - ax, vy = cy - ay, vz = cz - az;
    let nx = uy * vz - uz * vy;
    let ny = uz * vx - ux * vz;
    let nz = ux * vy - uy * vx;
    const len = Math.hypot(nx, ny, nz) || 1;
    nx /= len; ny /= len; nz /= len;

    const o = t * 9;
    pos[o] = ax; pos[o + 1] = ay; pos[o + 2] = az;
    pos[o + 3] = bx; pos[o + 4] = by; pos[o + 5] = bz;
    pos[o + 6] = cx; pos[o + 7] = cy; pos[o + 8] = cz;
    for (let k = 0; k < 3; k += 1) {
      nrm[o + k * 3] = nx;
      nrm[o + k * 3 + 1] = ny;
      nrm[o + k * 3 + 2] = nz;
    }
  }
  return { pos, nrm, count: triCount * 3 };
}

/** 圆角矩形折线，逆时针。与 shell.ts 同形，只是段数更密。 */
export function roundedRectPoly(
  x0: number, y0: number, x1: number, y1: number, r: number,
): Array<[number, number]> {
  const w = x1 - x0;
  const h = y1 - y0;
  const rr = Math.max(0, Math.min(r, w * 0.5 - 0.01, h * 0.5 - 0.01));
  const pts: Array<[number, number]> = [];
  const corners: Array<[number, number, number]> = [
    [x1 - rr, y0 + rr, -Math.PI / 2],
    [x1 - rr, y1 - rr, 0],
    [x0 + rr, y1 - rr, Math.PI / 2],
    [x0 + rr, y0 + rr, Math.PI],
  ];
  for (const [ccx, ccy, start] of corners) {
    if (rr <= 1e-9) {
      pts.push([ccx, ccy]);
      continue;
    }
    for (let i = 0; i <= PANEL_ARC_SEGMENTS; i += 1) {
      const a = start + (Math.PI / 2) * (i / PANEL_ARC_SEGMENTS);
      pts.push([ccx + rr * Math.cos(a), ccy + rr * Math.sin(a)]);
    }
  }
  return pts;
}

interface PanelGeometry {
  pos: Float32Array;
  nrm: Float32Array;
  uv: Float32Array;
  count: number;
}

/**
 * 画片薄板：正面贴图，侧面与背面用同一张图的模糊层级上色。
 *
 * UV 按包围盒线性映射；几何本身已经是圆角轮廓，贴图四角那点暗像素
 * 根本采不到，不需要再加一层 alpha 遮罩。
 */
export function buildPanel(
  x0: number, y0: number, x1: number, y1: number,
  frontZ: number, backZ: number, corner: number,
): PanelGeometry {
  const poly = roundedRectPoly(x0, y0, x1, y1, corner);
  const n = poly.length;
  const w = x1 - x0;
  const h = y1 - y0;
  // v 轴要翻过来：ImageData 第 0 行是图的顶边，而模型里 +Y 朝上
  const uvOf = (x: number, y: number): [number, number] => [(x - x0) / w, (y1 - y) / h];

  const pos: number[] = [];
  const nrm: number[] = [];
  const uv: number[] = [];

  const push = (
    p: readonly [number, number, number],
    nv: readonly [number, number, number],
    t: readonly [number, number],
  ) => {
    pos.push(p[0], p[1], p[2]);
    nrm.push(nv[0], nv[1], nv[2]);
    uv.push(t[0], t[1]);
  };

  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;

  // 正面（+Z）与背面（−Z），都用扇形三角化
  for (const front of [true, false] as const) {
    const z = front ? frontZ : backZ;
    const nz: [number, number, number] = [0, 0, front ? 1 : -1];
    const cUv = uvOf(cx, cy);
    for (let i = 0; i < n; i += 1) {
      const a = poly[i];
      const b = poly[(i + 1) % n];
      push([cx, cy, z], nz, cUv);
      if (front) {
        push([a[0], a[1], z], nz, uvOf(a[0], a[1]));
        push([b[0], b[1], z], nz, uvOf(b[0], b[1]));
      } else {
        push([b[0], b[1], z], nz, uvOf(b[0], b[1]));
        push([a[0], a[1], z], nz, uvOf(a[0], a[1]));
      }
    }
  }

  // 侧壁
  for (let i = 0; i < n; i += 1) {
    const a = poly[i];
    const b = poly[(i + 1) % n];
    let ex = b[1] - a[1];
    let ey = -(b[0] - a[0]);
    const len = Math.hypot(ex, ey);
    if (len < 1e-9) continue;
    ex /= len; ey /= len;
    const sn: [number, number, number] = [ex, ey, 0];
    const ua = uvOf(a[0], a[1]);
    const ub = uvOf(b[0], b[1]);
    push([a[0], a[1], backZ], sn, ua);
    push([b[0], b[1], backZ], sn, ub);
    push([b[0], b[1], frontZ], sn, ub);
    push([a[0], a[1], backZ], sn, ua);
    push([b[0], b[1], frontZ], sn, ub);
    push([a[0], a[1], frontZ], sn, ua);
  }

  return {
    pos: new Float32Array(pos),
    nrm: new Float32Array(nrm),
    uv: new Float32Array(uv),
    count: pos.length / 3,
  };
}

/* ============================ 着色器 ============================ */

const VERT_SHELL = `#version 300 es
in vec3 aPos;
in vec3 aNormal;
uniform mat4 uViewProj;
out vec3 vNormal;
out vec3 vWorld;
void main() {
  vNormal = aNormal;
  vWorld = aPos;
  gl_Position = uViewProj * vec4(aPos, 1.0);
}`;

const FRAG_SHELL = `#version 300 es
precision highp float;

in vec3 vNormal;
in vec3 vWorld;
out vec4 fragColor;

uniform vec3 uEye;
uniform vec3 uBase;        // 外壳颜色，线性空间
uniform float uLayerH;     // 外壳层高，用来画层纹
uniform sampler2D uPanelTex;
uniform vec4 uPanelRect;   // x0, y0, x1, y1
uniform float uPanelZ;
uniform float uPanelOn;

// 夏夜：冷月做主光，暖色补光，环境色取站点底色 #161E36
const vec3 KEY_DIR  = vec3(-0.4544, 0.7876, 0.4155);
const vec3 KEY_COL  = vec3(0.70, 0.76, 0.94);
const vec3 FILL_DIR = vec3(0.8018, -0.4677, 0.3741);
const vec3 FILL_COL = vec3(0.21, 0.16, 0.13);
const vec3 AMBIENT  = vec3(0.075, 0.092, 0.15);

void main() {
  vec3 N = normalize(vNormal);
  if (!gl_FrontFacing) N = -N;

  // 层纹：外壳开口朝 +Z 打印，层线沿 Z 一圈圈堆上去，所以只出现在侧面；
  // 顶面（法线 ±Z）本身就是一整层，没有横纹，(1 - |N.z|) 正好把它排除掉。
  float lz = vWorld.z / uLayerH;
  float fade = 1.0 - smoothstep(0.30, 0.85, fwidth(lz));   // 细过一个像素就淡出，免得摩尔纹
  float ridge = sin(lz * 6.2831853) * fade;
  N = normalize(N + vec3(0.0, 0.0, ridge * 0.13 * (1.0 - abs(N.z))));

  vec3 V = normalize(uEye - vWorld);
  vec3 col = uBase * AMBIENT;

  col += uBase * KEY_COL * max(dot(N, KEY_DIR), 0.0);
  col += uBase * FILL_COL * (max(dot(N, FILL_DIR), 0.0) * 0.5 + 0.5);

  // 画片是一整片发光面。把着色点投到画片矩形上取一个模糊色，
  // 内壁就会被画面本身的颜色染上 —— 比挂一盏固定暖光真实得多。
  if (uPanelOn > 0.5) {
    vec2 q = clamp(vWorld.xy, uPanelRect.xy, uPanelRect.zw);
    vec2 uv = (q - uPanelRect.xy) / max(uPanelRect.zw - uPanelRect.xy, vec2(1e-4));
    vec3 panelCol = textureLod(uPanelTex, vec2(uv.x, 1.0 - uv.y), 5.0).rgb;
    vec3 toPanel = vec3(q, uPanelZ) - vWorld;
    float d = length(toPanel);
    vec3 L = toPanel / max(d, 1e-4);
    float atten = 1.0 / (1.0 + d * d * 0.018);
    col += uBase * panelCol * max(dot(N, L), 0.0) * atten * 1.6;
  }

  vec3 H = normalize(KEY_DIR + V);
  col += KEY_COL * pow(max(dot(N, H), 0.0), 44.0) * 0.16;

  // 边缘光：深色外壳放在深色背景上，不勾一下会糊成一团
  col += vec3(0.34, 0.40, 0.60) * pow(1.0 - max(dot(N, V), 0.0), 3.5) * 0.34;

  fragColor = vec4(pow(max(col, 0.0), vec3(1.0 / 2.2)), 1.0);
}`;

const VERT_PANEL = `#version 300 es
in vec3 aPos;
in vec3 aNormal;
in vec2 aUv;
uniform mat4 uViewProj;
out vec3 vNormal;
out vec3 vWorld;
out vec2 vUv;
void main() {
  vNormal = aNormal;
  vWorld = aPos;
  vUv = aUv;
  gl_Position = uViewProj * vec4(aPos, 1.0);
}`;

const FRAG_PANEL = `#version 300 es
precision highp float;

in vec3 vNormal;
in vec3 vWorld;
in vec2 vUv;
out vec4 fragColor;

uniform vec3 uEye;
uniform sampler2D uTex;

void main() {
  vec3 N = normalize(vNormal);
  if (!gl_FrontFacing) N = -N;
  vec3 V = normalize(uEye - vWorld);
  float fres = 1.0 - max(dot(N, V), 0.0);

  vec3 col;
  if (N.z > 0.5) {
    // 正面：模拟图原样出，一个像素都不动 —— 这就是要给人看的那张画面。
    // 斜看时靠各向异性过滤保住细节，而不是靠降分辨率换性能。
    col = texture(uTex, vUv).rgb;
    col += pow(fres, 4.0) * 0.10 * vec3(1.0, 0.94, 0.86);   // PLA 表面那层薄反光
  } else if (N.z < -0.5) {
    // 背面朝着灯板，白色打底几乎被打透
    col = mix(textureLod(uTex, vUv, 3.0).rgb, vec3(1.0), 0.58) * 0.86;
  } else {
    // 侧壁只有一两毫米厚，光从料里透出来，取局部平均色最像
    col = textureLod(uTex, vUv, 4.0).rgb * (0.52 + 0.5 * pow(fres, 2.0));
  }
  fragColor = vec4(col, 1.0);
}`;

/* ============================ 渲染器 ============================ */

function compile(gl: WebGL2RenderingContext, type: number, src: string): WebGLShader {
  const sh = gl.createShader(type);
  if (!sh) throw new Error("createShader failed");
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(sh);
    gl.deleteShader(sh);
    throw new Error(`shader compile failed: ${log}`);
  }
  return sh;
}

function link(gl: WebGL2RenderingContext, vsSrc: string, fsSrc: string): WebGLProgram {
  const vs = compile(gl, gl.VERTEX_SHADER, vsSrc);
  const fs = compile(gl, gl.FRAGMENT_SHADER, fsSrc);
  const prog = gl.createProgram();
  if (!prog) throw new Error("createProgram failed");
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.linkProgram(prog);
  gl.deleteShader(vs);
  gl.deleteShader(fs);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    const log = gl.getProgramInfoLog(prog);
    gl.deleteProgram(prog);
    throw new Error(`program link failed: ${log}`);
  }
  return prog;
}

/** #RRGGBB → 线性空间 RGB。着色在线性空间做，最后再 gamma 回去。 */
function hexToLinear(hex: string): Vec3 {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  const v = m ? parseInt(m[1], 16) : 0xffffff;
  const srgb = [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
  const lin = srgb.map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return [lin[0], lin[1], lin[2]];
}

interface Buffers {
  vao: WebGLVertexArrayObject;
  buffers: WebGLBuffer[];
  count: number;
}

export class Preview3D {
  /** 没有 WebGL2 就别显示切换按钮，免得点了一片黑。 */
  static isSupported(): boolean {
    try {
      return !!document.createElement("canvas").getContext("webgl2");
    } catch {
      return false;
    }
  }

  private readonly canvas: HTMLCanvasElement;
  private readonly gl: WebGL2RenderingContext;
  private readonly shellProgram: WebGLProgram;
  private readonly panelProgram: WebGLProgram;
  private texture: WebGLTexture | null = null;
  private shellGeom: Buffers | null = null;
  private panelGeom: Buffers | null = null;

  private baseColor: Vec3 = [1, 1, 1];
  private panelRect: [number, number, number, number] = [0, 0, 1, 1];
  private panelZ = 0;
  private radius = 60;
  private centre: Vec3 = [0, 0, 0];

  private yaw = 0.38;
  private pitch = 0.18;
  private distanceScale = 1;
  private spin: boolean;
  private lastTime = 0;
  private frame = 0;
  private disposed = false;
  private readonly pointers = new Map<number, { x: number; y: number }>();
  private pinchGap = 0;

  private readonly observer: ResizeObserver;
  private readonly onVisibility = () => this.invalidate();

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    const gl = canvas.getContext("webgl2", {
      alpha: true,
      antialias: true,
      premultipliedAlpha: false,
      depth: true,
      powerPreference: "high-performance",
    });
    if (!gl) throw new Error("WebGL2 unavailable");
    this.gl = gl;

    this.shellProgram = link(gl, VERT_SHELL, FRAG_SHELL);
    this.panelProgram = link(gl, VERT_PANEL, FRAG_PANEL);

    gl.enable(gl.DEPTH_TEST);
    gl.clearColor(0, 0, 0, 0);

    this.spin = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    this.observer = new ResizeObserver(() => this.invalidate());
    this.observer.observe(canvas);
    document.addEventListener("visibilitychange", this.onVisibility);
    canvas.addEventListener("webglcontextlost", this.onContextLost, false);
    this.bindPointer();
  }

  /* -------- 场景 -------- */

  setScene(scene: Preview3DScene): void {
    const { artW, artH, shell } = scene;

    // 坐标沿用 shell.ts 的约定：画片原点在 (clearance, clearance)，外底面在 Z = 0
    const clearance = shell ? shell.clearance : 0;
    const artX0 = clearance;
    const artY0 = clearance;
    const artX1 = clearance + artW;
    const artY1 = clearance + artH;

    let minX = artX0, minY = artY0, maxX = artX1, maxY = artY1;
    let minZ = 0, maxZ = Math.max(0.6, scene.artThicknessMm);
    let frontZ = maxZ;

    this.disposeGeometry();

    if (shell) {
      const params: ShellParams = {
        ...SHELL_DEFAULTS,
        artW,
        artH,
        wall: shell.wall,
        depth: shell.depth,
        corner: shell.corner,
        clearance: shell.clearance,
      };
      const mesh = buildShellMesh(params);
      const flat = flatShade(mesh.vertices, mesh.indices);
      this.shellGeom = this.upload(
        this.shellProgram,
        [
          { name: "aPos", data: flat.pos, size: 3 },
          { name: "aNormal", data: flat.nrm, size: 3 },
        ],
        flat.count,
      );

      // buildShellMesh 会把过浅的 depth 顶上去，这里要跟着算，否则画片会浮在壳外
      const depth = Math.max(params.wall + params.artThickness + 4, params.depth);
      frontZ = depth;
      minX = clearance - params.wall;
      minY = clearance - params.wall;
      maxX = artX1 + params.wall;
      maxY = artY1 + params.topThickness;
      minZ = 0;
      maxZ = depth;
      this.baseColor = hexToLinear(shell.colorHex);
    }

    const backZ = frontZ - Math.max(0.6, scene.artThicknessMm);
    const panel = buildPanel(
      artX0, artY0, artX1, artY1, frontZ, backZ, shell ? shell.corner : 0,
    );
    this.panelGeom = this.upload(
      this.panelProgram,
      [
        { name: "aPos", data: panel.pos, size: 3 },
        { name: "aNormal", data: panel.nrm, size: 3 },
        { name: "aUv", data: panel.uv, size: 2 },
      ],
      panel.count,
    );

    this.panelRect = [artX0, artY0, artX1, artY1];
    this.panelZ = frontZ;
    this.centre = [(minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2];
    this.radius = Math.max(1, 0.5 * Math.hypot(maxX - minX, maxY - minY, maxZ - minZ));

    this.uploadTexture(scene.image);
    this.invalidate();
  }

  /** 只换外壳颜色，几何和贴图都不用重建。 */
  setShellColor(hex: string): void {
    this.baseColor = hexToLinear(hex);
    this.invalidate();
  }

  resetView(): void {
    this.yaw = 0.38;
    this.pitch = 0.18;
    this.distanceScale = 1;
    this.invalidate();
  }

  dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    this.observer.disconnect();
    document.removeEventListener("visibilitychange", this.onVisibility);
    this.canvas.removeEventListener("webglcontextlost", this.onContextLost);
    this.disposeGeometry();
    const gl = this.gl;
    if (this.texture) gl.deleteTexture(this.texture);
    gl.deleteProgram(this.shellProgram);
    gl.deleteProgram(this.panelProgram);
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  }

  /* -------- GPU 资源 -------- */

  private upload(
    program: WebGLProgram,
    attribs: Array<{ name: string; data: Float32Array; size: number }>,
    count: number,
  ): Buffers {
    const gl = this.gl;
    const vao = gl.createVertexArray();
    if (!vao) throw new Error("createVertexArray failed");
    gl.bindVertexArray(vao);
    const buffers: WebGLBuffer[] = [];
    for (const a of attribs) {
      const loc = gl.getAttribLocation(program, a.name);
      const buf = gl.createBuffer();
      if (!buf) throw new Error("createBuffer failed");
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, a.data, gl.STATIC_DRAW);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, a.size, gl.FLOAT, false, 0, 0);
      buffers.push(buf);
    }
    gl.bindVertexArray(null);
    return { vao, buffers, count };
  }

  private disposeGeometry(): void {
    const gl = this.gl;
    for (const g of [this.shellGeom, this.panelGeom]) {
      if (!g) continue;
      gl.deleteVertexArray(g.vao);
      for (const b of g.buffers) gl.deleteBuffer(b);
    }
    this.shellGeom = null;
    this.panelGeom = null;
  }

  /**
   * 贴图按原分辨率上传，另开 mipmap 与各向异性过滤。
   *
   * 这两样正是「不降清晰度」的关键：正视时采第 0 级，就是原图本身；
   * 只有斜视或缩小时才走 mip 链 —— 否则打印网格的抖动点会糊成一片摩尔纹。
   */
  private uploadTexture(image: ImageData): void {
    const gl = this.gl;
    if (!this.texture) this.texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(
      gl.TEXTURE_2D, 0, gl.RGBA,
      image.width, image.height, 0,
      gl.RGBA, gl.UNSIGNED_BYTE, image.data,
    );
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    const aniso =
      gl.getExtension("EXT_texture_filter_anisotropic") ??
      gl.getExtension("WEBKIT_EXT_texture_filter_anisotropic");
    if (aniso) {
      const max = gl.getParameter(aniso.MAX_TEXTURE_MAX_ANISOTROPY_EXT) as number;
      gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, Math.min(16, max));
    }
  }

  private readonly onContextLost = (e: Event) => {
    e.preventDefault();
    cancelAnimationFrame(this.frame);
    this.frame = 0;
  };

  /* -------- 交互 -------- */

  private bindPointer(): void {
    const c = this.canvas;

    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      this.spin = false; // 用户接手了就别再自己转
      if (this.pointers.size === 2) this.pinchGap = this.pointerGap();
    });

    c.addEventListener("pointermove", (e) => {
      const prev = this.pointers.get(e.pointerId);
      if (!prev) return;
      this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

      if (this.pointers.size === 1) {
        this.yaw += (e.clientX - prev.x) * 0.008;
        this.pitch = Math.max(-1.35, Math.min(1.35, this.pitch + (e.clientY - prev.y) * 0.008));
        this.invalidate();
      } else if (this.pointers.size === 2) {
        const gap = this.pointerGap();
        if (this.pinchGap > 0 && gap > 0) this.zoom(this.pinchGap / gap);
        this.pinchGap = gap;
      }
    });

    const release = (e: PointerEvent) => {
      this.pointers.delete(e.pointerId);
      this.pinchGap = 0;
    };
    c.addEventListener("pointerup", release);
    c.addEventListener("pointercancel", release);
    c.addEventListener("lostpointercapture", release);

    c.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        this.zoom(Math.exp(e.deltaY * 0.0012));
      },
      { passive: false },
    );

    c.addEventListener("dblclick", () => this.resetView());
  }

  private pointerGap(): number {
    const [a, b] = [...this.pointers.values()];
    return a && b ? Math.hypot(a.x - b.x, a.y - b.y) : 0;
  }

  private zoom(factor: number): void {
    this.distanceScale = Math.max(0.55, Math.min(2.6, this.distanceScale * factor));
    this.invalidate();
  }

  /* -------- 渲染 -------- */

  /**
   * 请求一帧。
   * 自转开着就接着排下一帧，否则画完即停 —— 不空转，不烤电池。
   */
  invalidate(): void {
    if (this.disposed || this.frame) return;
    this.frame = requestAnimationFrame((t) => {
      this.frame = 0;
      this.draw(t);
      if (this.spin && !document.hidden) this.invalidate();
    });
  }

  private resize(): boolean {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = Math.max(1, Math.round(this.canvas.clientWidth * dpr));
    const h = Math.max(1, Math.round(this.canvas.clientHeight * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this.gl.viewport(0, 0, w, h);
    return w > 1 && h > 1;
  }

  private draw(now: number): void {
    if (this.disposed) return;
    const gl = this.gl;
    if (!this.resize()) return;

    if (this.spin && !document.hidden) {
      const dt = this.lastTime ? Math.min(0.05, (now - this.lastTime) / 1000) : 0;
      this.yaw += dt * 0.2;
    }
    this.lastTime = now;

    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!this.panelGeom) return;

    const fov = (38 * Math.PI) / 180;
    const dist = (this.radius / Math.sin(fov / 2)) * 1.18 * this.distanceScale;
    const cp = Math.cos(this.pitch);
    const eye: Vec3 = [
      this.centre[0] + dist * cp * Math.sin(this.yaw),
      this.centre[1] + dist * Math.sin(this.pitch),
      this.centre[2] + dist * cp * Math.cos(this.yaw),
    ];

    const aspect = this.canvas.width / this.canvas.height;
    const viewProj = multiply(
      perspective(fov, aspect, Math.max(1, dist - this.radius * 2), dist + this.radius * 4),
      lookAt(eye, this.centre, [0, 1, 0]),
    );

    if (this.texture) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.texture);
    }

    if (this.shellGeom) {
      gl.useProgram(this.shellProgram);
      const u = (n: string) => gl.getUniformLocation(this.shellProgram, n);
      gl.uniformMatrix4fv(u("uViewProj"), false, viewProj);
      gl.uniform3fv(u("uEye"), eye);
      gl.uniform3fv(u("uBase"), this.baseColor);
      gl.uniform1f(u("uLayerH"), SHELL_LAYER_MM);
      gl.uniform1i(u("uPanelTex"), 0);
      gl.uniform4fv(u("uPanelRect"), this.panelRect);
      gl.uniform1f(u("uPanelZ"), this.panelZ);
      gl.uniform1f(u("uPanelOn"), this.texture ? 1 : 0);
      gl.bindVertexArray(this.shellGeom.vao);
      gl.drawArrays(gl.TRIANGLES, 0, this.shellGeom.count);
    }

    gl.useProgram(this.panelProgram);
    const p = (n: string) => gl.getUniformLocation(this.panelProgram, n);
    gl.uniformMatrix4fv(p("uViewProj"), false, viewProj);
    gl.uniform3fv(p("uEye"), eye);
    gl.uniform1i(p("uTex"), 0);
    gl.bindVertexArray(this.panelGeom.vao);
    gl.drawArrays(gl.TRIANGLES, 0, this.panelGeom.count);

    gl.bindVertexArray(null);
  }
}
