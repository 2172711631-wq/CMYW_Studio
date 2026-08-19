# How it works

> [中文版见下半部分](#原理详解中文) · Chinese version in the second half

A walkthrough of what happens between dropping in a JPEG and getting a printable 3MF.
Every constant quoted here lives at the top of [`main.py`](../main.py) and can be
overridden with an environment variable.

---

## 1. The physical model

A backlit print is a **subtractive filter stack**. Light enters from behind, passes
through some layers of coloured plastic, and whatever survives is what your eye sees.

Absorption follows the Beer–Lambert law: each layer multiplies the transmitted light by
a constant factor, so *stacked layers multiply* and the maths is only pleasant in
logarithmic space. We call that space **optical density**:

```
density  e = −ln(T)          T = transmittance, 0…1
```

Densities add. Two layers of cyan absorb exactly twice the density of one. That single
property is why the whole pipeline works in density instead of in RGB.

Each filament gets one constant — the density it contributes *per 0.08 mm layer*,
in the channel it absorbs:

| Filament | Absorbs | Density per layer | Max layers |
|----------|---------|-------------------|------------|
| White | everything, weakly | `0.11` | 4 (fixed) |
| Cyan | red | `0.58` | 6 |
| Magenta | green | `0.50` | 6 |
| Yellow | blue | `0.68` | 6 |

These are working values for Bambu PLA Basic. They are **not instrument
measurements** — they are starting values that were kept because printed results
tracked the source closely across a wide range of images, including saturated
colour charts. If you use different filament,
[derive your own](#calibrating-for-your-own-filament).

## 2. Pixel → target density

The image is first resampled to the print grid (default `0.20 mm` per pixel, so a
135 mm print is 675 px wide), then each channel is converted to the density we want that
pixel to have:

```python
e = (−ln(rgb)) ** 0.72 * 1.78
```

The exponent `0.72` and multiplier `1.78` are not physics — they are the tone curve.
Raw `−ln(T)` maps mid-tones too dark, because a lightbox is viewed against a bright
surround and human brightness perception is non-linear. These two numbers were tuned by
eye against real prints until mid-tones sat right.

Input is clamped to a minimum of `0.004` first, since `ln(0)` is infinite and a pure
black pixel would ask for infinite plastic.

## 3. Density → layer counts

The white base is fixed at 4 layers, contributing `0.11 × 4 = 0.44` density in every
channel. Subtract that, divide by the per-layer density of the filament that absorbs
this channel, and you have a layer count:

```python
c = max(0, (e_r − 0.44) / 0.58)     # cyan absorbs red
m = max(0, (e_g − 0.44) / 0.50)     # magenta absorbs green
y = max(0, (e_b − 0.44) / 0.68)     # yellow absorbs blue
```

At this point the naive approach would round these and print. That produces the muddy
result everyone complains about, for a reason worth understanding.

## 4. The part that actually matters: adaptive UCR

Wherever all three of C, M and Y are present, the overlap is **grey**. Grey made from
three coloured filaments is the worst possible grey: it costs three times the material,
triples the filament changes, and any slight mis-calibration between the three shows up
as a colour cast across what should be a neutral.

Printing borrowed the fix decades ago — *under-colour removal*. Pull the common
component out:

```python
k = min(c, m, y)          # the grey hiding in this pixel
c_chr = c − k             # what is left is pure hue
m_chr = m − k
y_chr = y − k
```

But you cannot simply throw `k` away — there is no black filament in the stack, so the
shadows would go pale and flat. This is where the generator does something a little
unusual: it adds part of the grey back, weighted by **that pixel's own brightness**:

```python
lum    = (r + g + b) / 3
k_back = k * (1 − lum) * 0.45

c = c_chr + k_back
m = m_chr + k_back
y = y_chr + k_back
```

A dark pixel (`lum → 0`) gets most of its grey back and stays dense. A bright pixel
(`lum → 1`) gets almost none and stays clean. Because the weight is derived per pixel,
the behaviour adapts to the image automatically — there is no per-photo slider to
fiddle with. Swap a sunset for a snow scene and it rebalances itself.

## 5. Quantisation without banding

Layer counts are integers between 0 and 6. Seven levels per channel is very coarse, and
rounding directly produces visible contour lines across smooth gradients.

Two tricks keep it smooth:

**Ordered dithering.** A 4×4 Bayer matrix, scaled to `±0.22` layers, is added before
rounding. Adjacent pixels round in different directions and the eye blends them. Blue
noise would be marginally nicer but the tiled Bayer matrix costs nothing.

**A floor for faint colour.** Anything below half a layer rounds to zero, so the
faintest tints vanish entirely and skin tones go blotchy. Values above `0.32` are
lifted to `0.51` so they survive rounding — but *only* where the pixel has real
chromatic content (`c_chr + m_chr + y_chr ≥ 0.32`). Without that guard, neutral greys
and highlights get carpeted in a three-colour haze that looks like dirt.

## 6. Layers → geometry

Each colour becomes its own mesh, stacked in print order — white at Z=0, then yellow,
magenta, cyan:

```
z_white   = 0
z_yellow  = l_white
z_magenta = l_white + l_yellow
z_cyan    = l_white + l_yellow + l_magenta
```

One box per pixel would mean millions of triangles. Two passes cut that down:

1. **A 3×3 median filter** on the layer heights, which merges same-height pixels into
   contiguous patches without touching the colour decisions. Zeros are preserved so
   holes stay holes.
2. **Greedy rectangle merging** — scan for runs of pixels sharing the same height *and*
   the same Z start, extend them right, then extend that row-run downward as far as it
   stays uniform. Each surviving rectangle becomes a single box of 12 triangles.

On a typical photo this is a 10–50× reduction in triangle count, which is the difference
between a slicer that responds and one that hangs.

Finally, if a lightbox shell is requested, the picture's four corners are cut to match
the shell's corner radius. The test is whether the *whole pixel square* falls outside
the rounded rectangle, not just its centre — testing centres leaves a ragged, notched
arc. A morphological close repairs single-pixel gaps, and a soft outer boundary stops
that close from bulging past the shell.

## 7. The shell

The lightbox is real parametric CAD, not a mesh hack — [`shell_master/shell_cadquery.py`](../shell_master/shell_cadquery.py)
builds it with CadQuery from the values in [`params.json`](../shell_master/params.json).

Its rules, relative to the picture:

- side walls inset by `wall/2`, so the ledge that supports the picture is `wall/2` wide
- outer frame extends `wall` beyond the picture
- the top wall is thinner (`top_thickness`, hard-capped at 3 mm) because that is the
  face you touch to switch the light
- a slot cut to picture thickness + FDM tolerance grips the print
- a USB-C cutout on the +X side, lifted `1.55 mm` above the cavity floor

The same expressions are mirrored in [`UG_EXPRESSIONS.md`](../shell_master/UG_EXPRESSIONS.md)
if you would rather drive it from UG/NX.

## 8. Packing the 3MF

[`bambu_export.py`](../bambu_export.py) writes a Bambu Studio project, not a bare model:

- **Two plates.** The picture prints at 0.08 mm; the shell has no reason to and would
  waste hours. They are separate build items with separate recommended settings.
- **Pre-assigned AMS slots.** Extruders 1–4 carry C/M/Y/W, extruder 5 the shell colour,
  with the official Bambu PLA hex values filled in so the slicer shows the right colours.
- **A prime tower**, parked at a fixed corner. Four-colour printing means constant
  purging; the default tower position drifts off a 256 mm plate.
- **A solid-infill modifier** over the shell's top wall, so the touch surface prints
  dense.
- **Your source photo** embedded as the package thumbnail, so the file has a recognisable
  icon.

## Calibrating for your own filament

The four density constants are the only filament-specific values. To re-derive them:

There is a tool for this — you do not have to build the target yourself:

```bash
py -3.11 tools/make_wedge.py          # writes calibration/密度阶梯标定片.3mf
```

That plate is 120 × 160 mm and drops straight into the standard lightbox. Rows 1–2 are
white at 4/6/8/10/12/16/20/24 layers; rows 3–4 are the 4-layer white base plus 0–6
layers of C, M and Y together.

1. Print it at 0.08 mm, slots 1=Cyan 2=Magenta 3=Yellow 4=White.
2. Light it from behind with the panel you will actually use.
3. Photograph it flat — **flash off, HDR off, exposure locked**; raw is better. Crop to
   the plate edges and save as `calibration/wedge_photo.jpg`.
4. Run the fit:

```bash
py -3.11 tools/measure_wedge.py calibration/wedge_photo.jpg
```

It linearises the photo, samples each patch, fits `e = −ln(T)` against layer count, and
prints your four densities next to the current defaults. It also subtracts the known
channel cross-talk, so the numbers come out comparable. The script round-trips its own
synthetic render to within 0.008, so the method is sound — what it needs is your photo.

Then set it via environment variable — no code edit needed:

```bash
FDM_COLOR_PROFILE=v2 python cli.py photo.jpg
```

Density constants currently require editing `main.py` (and `web/src/engine/constants.ts`
for the browser build) directly; making them a configuration file is on the roadmap.
If you derive a good set for a common filament, please open an issue with your numbers
and a photo of the wedge — see [CONTRIBUTING.md](../CONTRIBUTING.md) for why issues
rather than pull requests.

## Tunable constants

| Variable | Default | Effect |
|---|---|---|
| `FDM_MM_PER_PX` | `0.20` | Grid density. Smaller = sharper, far more triangles |
| `FDM_COLOR_PROFILE` | `v2` | `v2` = CMY extraction + adaptive UCR; `v1` = legacy direct mapping |
| `FDM_MESH_MODE` | `voxel` | `voxel` = pixel boxes (stable); `region` = contour merging (experimental) |
| `FDM_DITHER_AMT` | `0.22` | Dither amplitude in layers. Higher = smoother gradients, more noise |
| `FDM_KEEP_FLOOR` | `0.32` | Threshold below which faint colour is dropped |
| `FDM_MESH_MERGE_FILTER` | `3` | Median filter size before meshing. Larger = fewer triangles, softer detail |

---

<a name="原理详解中文"></a>

# 原理详解（中文）

从丢进一张 JPEG 到拿到可打印的 3MF，中间发生了什么。下面提到的每个常数都在
[`main.py`](../main.py) 顶部，都能用环境变量覆盖。

## 1. 物理模型

背光打印件是一个**减色滤光叠层**。光从背后进来，穿过若干层有色塑料，活下来的那部分就是你看到的。

吸收遵循 Beer–Lambert 定律：每一层把透射光乘上一个固定系数，所以**层叠是相乘**，
只有在对数空间里算才舒服。这个空间叫**光密度**：

```
密度  e = −ln(T)          T = 透射率，0…1
```

密度可以相加。两层青正好是一层青的两倍密度。整条管线在密度里而不是在 RGB 里工作，就是因为这一条性质。

每种耗材有一个常数——**每 0.08mm 一层**在它所吸收的通道里贡献的密度：

| 耗材 | 吸收 | 每层密度 | 最大层数 |
|---|---|---|---|
| 白 | 全谱，弱 | `0.11` | 4（固定） |
| 青 | 红 | `0.58` | 6 |
| 品红 | 绿 | `0.50` | 6 |
| 黄 | 蓝 | `0.68` | 6 |

这些是拓竹 PLA Basic 上的工作值。**不是仪器测量结果**——它们是一组起始值，
因为在各类图片（包括高饱和色卡）上打印成品与原图的还原度都很高而被保留下来。
换耗材请[自己推一套](#给自己的耗材做标定)。

## 2. 像素 → 目标密度

图先重采样到打印网格（默认每像素 `0.20mm`，所以 135mm 的画幅是 675 像素宽），
然后每个通道换算成这个像素应该有的密度：

```python
e = (−ln(rgb)) ** 0.72 * 1.78
```

指数 `0.72` 和系数 `1.78` 不是物理，是**影调曲线**。原始的 `−ln(T)` 会把中间调压得太暗，
因为灯箱是在明亮环境里看的，而且人眼亮度感知是非线性的。这两个数同样是经验值，按成品观感定的，没有物理依据。

输入先钳到最小 `0.004`，因为 `ln(0)` 是无穷大，一个纯黑像素会要求无限多的塑料。

## 3. 密度 → 层数

白底固定 4 层，在每个通道贡献 `0.11 × 4 = 0.44` 的密度。减掉它，
再除以吸收该通道那种耗材的每层密度，就得到层数：

```python
c = max(0, (e_r − 0.44) / 0.58)     # 青吸红
m = max(0, (e_g − 0.44) / 0.50)     # 品红吸绿
y = max(0, (e_b − 0.44) / 0.68)     # 黄吸蓝
```

到这里，天真的做法就是四舍五入然后打印。那会得到人人抱怨的发闷结果，原因值得说清楚。

## 4. 真正关键的一步：自适应 UCR

只要 C、M、Y 三者同时存在，重叠部分就是**灰**。用三种彩色耗材做出来的灰是最糟的灰：
费三倍的料、换色次数翻三倍，而且三者之间任何一点标定偏差，都会在本该中性的地方显出色偏。

印刷业几十年前就有解法——**底色去除（UCR）**。把公共分量抽出来：

```python
k = min(c, m, y)          # 藏在这个像素里的灰
c_chr = c − k             # 剩下的是纯色相
m_chr = m − k
y_chr = y − k
```

但不能直接把 `k` 扔掉——叠层里没有黑色耗材，扔掉暗部就会发白发平。
这里生成器做了件不太常见的事：**按这个像素自己的亮度**把一部分灰加回去：

```python
lum    = (r + g + b) / 3
k_back = k * (1 − lum) * 0.45

c = c_chr + k_back
m = m_chr + k_back
y = y_chr + k_back
```

暗像素（`lum → 0`）几乎把灰全要回来，保持厚重；亮像素（`lum → 1`）几乎不要，保持干净。
因为权重是逐像素算的，行为会自动随图适应——**没有需要逐张照片调的滑块**。
把日落换成雪景，它自己会重新平衡。

## 5. 量化而不出色阶

层数是 0 到 6 的整数。每通道只有 7 级非常粗，直接取整会在平滑渐变上出现明显的等高线。

两个手段保住平滑：

**有序抖动。** 取整前加上一个 4×4 Bayer 矩阵，幅度缩放到 `±0.22` 层。
相邻像素朝不同方向取整，眼睛会把它们混合。蓝噪声会略好一点，但平铺 Bayer 不要钱。

**浅色保底。** 低于半层的都会被舍成 0，于是最淡的色调整片消失，肤色会花。
所以高于 `0.32` 的值被抬到 `0.51` 让它挺过取整——但**只在**该像素有真实彩色分量时
（`c_chr + m_chr + y_chr ≥ 0.32`）。没有这道闸，中性灰和高光会被铺上一层三色薄雾，看起来像脏。

## 6. 层 → 几何

每种颜色是独立网格，按打印顺序叠——白在 Z=0，然后黄、品红、青：

```
z_白   = 0
z_黄   = l_白
z_品红 = l_白 + l_黄
z_青   = l_白 + l_黄 + l_品红
```

一个像素一个盒子意味着几百万三角面。两道处理把它压下来：

1. **3×3 中值滤波**处理层高，把同高像素连成片，不动分色决策。0 会被保留，空洞仍是空洞。
2. **贪心矩形合并**——扫描高度和 Z 起点都相同的连续像素，向右扩展，
   再把这一行的段整体向下扩展到不再均匀为止。每个存活的矩形变成一个 12 面的盒子。

普通照片上这是 10–50 倍的面数削减，也就是切片软件「能响应」和「卡死」的区别。

最后，如果要灯箱外壳，画片四角会按外壳圆角切掉。判据是**整个像素方块**是否落在圆角矩形之外，
而不只是看中心点——只看中心会在圆弧上留下锯齿缺口。再用一次形态学闭运算补掉单像素豁口，
外侧留一道软边界防止闭运算糊出外壳。

## 7. 外壳

灯箱是真正的参数化 CAD，不是网格拼凑——[`shell_master/shell_cadquery.py`](../shell_master/shell_cadquery.py)
用 CadQuery 按 [`params.json`](../shell_master/params.json) 里的值生成。

相对画片的规则：

- 侧壁内缩 `wall/2`，于是托住画片的承台宽度就是 `wall/2`
- 外框比画片外扩 `wall`
- 顶壁更薄（`top_thickness`，硬上限 3mm），因为那是你按下去开灯的那一面
- 卡槽按画片厚度 + FDM 公差切出，正好夹住
- +X 侧有 Type-C 开孔，相对内腔底面抬高 `1.55mm`

如果你更想用 UG/NX 驱动，同样的表达式在 [`UG_EXPRESSIONS.md`](../shell_master/UG_EXPRESSIONS.md)。

## 8. 打包 3MF

[`bambu_export.py`](../bambu_export.py) 写的是一个 Bambu Studio **工程**，不是裸模型：

- **两个盘。** 画片要 0.08mm；外壳没必要，那样会白白多花几小时。
  它们是各自独立的 build item，带各自的推荐参数。
- **预分配 AMS 槽位。** 挤出机 1–4 是 C/M/Y/W，挤出机 5 是外壳色，
  填的是拓竹官方 PLA 色值，切片软件里显示的颜色就是对的。
- **擦料塔**固定停在一个角。四色打印要不停排废料；默认塔位会飘出 256mm 盘外。
- **顶壁实心 modifier**，让你手指常按的那一面打得密实。
- **你的原图**作为包缩略图嵌进去，文件在资源管理器里有个认得出的图标。

## 给自己的耗材做标定

四个密度常数是唯一和耗材相关的值。重新标定的方法：

有现成工具，标定片不用自己拼：

```bash
py -3.11 tools/make_wedge.py          # 生成 calibration/密度阶梯标定片.3mf
```

这片 120 × 160 mm，直接进标准灯箱。第 1–2 行是纯白 4/6/8/10/12/16/20/24 层，
第 3–4 行是 4 层白底加 C/M/Y 各 0–6 层。

1. 0.08mm 层高打印，槽位 1=青 2=品红 3=黄 4=白。
2. 用你实际要用的灯板从背后打光。
3. 正面平拍——**关闪光、关 HDR、锁定曝光**，能拍 RAW 更好。
   裁到只剩画片，存成 `calibration/wedge_photo.jpg`。
4. 跑拟合：

```bash
py -3.11 tools/measure_wedge.py calibration/wedge_photo.jpg
```

脚本会把照片转成线性光、采样每一格、对层数拟合 `e = −ln(T)`，
把你的四个密度和当前默认值并排打出来，并扣掉已知的通道串扰让数值可比。
它用自己的合成渲染自检过，误差在 0.008 以内——方法是通的，缺的只是你那张照片。

密度常数目前需要直接改 `main.py`（网页版还要改 `web/src/engine/constants.ts`）；
做成配置文件在路线图里。如果你为某种常见耗材推出了好用的一组，
**欢迎开 issue 附上数值和标定片照片** —— 为什么是 issue 而不是 PR，见
[CONTRIBUTING.md](../CONTRIBUTING.md)。

## 可调常数

| 变量 | 默认 | 作用 |
|---|---|---|
| `FDM_MM_PER_PX` | `0.20` | 网格密度。越小越清晰，面数暴涨 |
| `FDM_COLOR_PROFILE` | `v2` | `v2` = CMY 提取 + 自适应 UCR；`v1` = 旧的直接映射 |
| `FDM_MESH_MODE` | `voxel` | `voxel` = 像素方块（稳）；`region` = 轮廓合并（实验性） |
| `FDM_DITHER_AMT` | `0.22` | 抖动幅度（层）。越大渐变越平滑，噪点越多 |
| `FDM_KEEP_FLOOR` | `0.32` | 低于此值的浅色被舍弃 |
| `FDM_MESH_MERGE_FILTER` | `3` | 网格化前的中值滤波尺寸。越大面数越少，细节越软 |
