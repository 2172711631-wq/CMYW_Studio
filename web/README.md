# 触光工坊 Touch & Light — 网页版

浏览器里的彩色透光灯箱生成器。**整条解算链路都在访客自己的设备上跑**：
照片不上传、不经过任何服务器，断网也能用。

因此这是一个**纯静态站点**——没有后端、没有数据库、没有需要一直开着的机器。

The browser build of CMYW Studio. The entire pipeline runs on the visitor's own
device: photos are never uploaded, and the tool works offline. That makes this a
purely static site — no backend, no database, no machine to keep running.

---

## 本地开发

需要 Node 18+。

```bash
cd web
npm install
npm run dev        # http://localhost:5173
```

其它命令：

| 命令 | 作用 |
|---|---|
| `npm run verify` | 类型检查 + 全部测试（提交前跑这个） |
| `npm run build` | 产出 `dist/`，可直接发布 |
| `npm run preview` | 预览构建产物 |
| `npm test` | 只跑测试 |

## 结构

```
index.html            首页
studio.html           制作台（上传 → 预览 → 下载 3MF）
src/engine/           解算引擎，与 Python 版逐像素对齐
  constants.ts          光学常数，与 main.py 严格同步
  separate.ts           RGB → CMYW 层数
  voxel.ts              中值滤波 + 矩形合并
  corner.ts             圆角遮罩
  shell.ts              参数化外壳网格
  simulate.ts           透光模拟（预览用）
  preview3d.ts          立体预览（原生 WebGL2，无第三方库）
  zip.ts / threemf.ts   3MF 打包
src/worker/           解算工作线程
src/ui/               页面交互
src/styles/           样式
public/               静态资源，原样复制到 dist/
photos/               实拍原图（tools/prepare_photos.py 的输入）
public/               图标、分享卡、_headers（tools/make_brand_assets.py 生成前两样）
test/                 与 Python 基准的一致性测试
```

## 引擎为什么要测

`src/engine/` 是 `main.py` 的移植，两边**必须**得到相同结果，否则同一张图在
桌面版和网页版会打出不同的东西。`test/` 里的基准数据由 Python 侧生成，
逐像素比对。

改动引擎后：

```bash
py -3.11 tools/make_fixtures.py   # 在仓库根目录，重新生成基准
cd web && npm run verify          # 确认两边仍然一致
```

测试变红说明两边逻辑已经分叉，要么同步移植，要么 Python 侧的改动是非预期的。

移植时有两个坑值得记住，都会导致大面积偏差而不是崩溃：

- **NumPy 的 `round` 是银行家舍入**（0.5→0），JS 的 `Math.round` 不是
- **Python 全程 float32**，JS 数字是 float64，每步都要 `Math.fround` 收回来

## 部署

见 [`deploy/cloudflare-pages.md`](deploy/cloudflare-pages.md)。

一句话版本：Cloudflare Pages 连上这个仓库，构建目录 `web`，命令 `npm run build`，
输出 `dist`。免费、全球 CDN、自动 HTTPS，你的电脑不用开机。
