# Printing guide

> [中文版见下半部分](#打印指南中文) · Chinese version in the second half

The 3MF arrives with almost everything configured. This covers what the file cannot
decide for you, and the mistakes that cost the most filament.

---

## What you need

| | |
|---|---|
| **Printer** | Multi-material. Developed on a Bambu Lab X1C + AMS; any AMS-class machine works |
| **Filament** | PLA in Cyan, Magenta, Yellow and White, plus one colour for the shell |
| **Light** | A flat, even, diffuse USB-C LED panel sized to the picture |
| **Slicer** | Bambu Studio (the 3MF is a Bambu project file) |

**Use PLA.** PETG and ABS are more translucent than PLA and wash the colours out; the
density constants assume PLA. Silk and matte variants change transmission noticeably —
Basic is what the numbers were measured on.

## Loading the AMS

Slot order is baked into the file. Get it wrong and the image inverts in strange ways:

| Slot | Filament |
|------|----------|
| 1 | **Cyan** |
| 2 | **Magenta** |
| 3 | **Yellow** |
| 4 | **White** |
| 5 | Shell colour (any) |

If your AMS has four slots, print the two plates in separate jobs — the shell only needs
slot 5, and the picture never uses it.

## Slicing

**Plate 1 — the picture**

| Setting | Value | Why |
|---|---|---|
| Layer height | **0.08 mm** | Not negotiable. Every density constant is per-0.08 mm layer. At 0.12 the image comes out ~50% too dark |
| Infill | **100%** | Anything less and light leaks through the gaps as visible mottling |
| Supports | Off | The picture is a flat slab |
| Prime tower | On | Already positioned in the file — leave it |

Print it **flat on the plate, image side down**. The bottom surface is the one against
the build plate, and a textured plate leaves its texture on it, which diffuses the light
pleasantly. A smooth plate gives a glossier, more mirror-like face — both look fine,
pick what you prefer.

**Plate 2 — the shell**

0.2 mm layers, 15–20% infill, supports off. It is a box; do not spend hours on it.

## Expect a lot of filament changes

Four colours interleaved across every layer means the printer swaps constantly and purges
each time. A 135 mm picture typically spends **more filament on purge than on the model
itself**. This is inherent to multi-colour printing, not a bug in the generator.

Ways to reduce it:

- Print several pictures at once — the purge cost is per *layer*, not per object, so
  four pictures on one plate cost barely more purge than one
- Keep `--mm-per-px` at the default; a finer grid does not add colour changes, but it
  does add hours
- Reuse the purge — set "flush into infill" on the shell plate if you print both together

## Assembly

The picture drops into the slot in the shell front. Default clearance is 0.2 mm, which
is snug on a well-tuned machine.

If it will not go in, your printer is running wide — either scale the clearance up:

```bash
python cli.py photo.jpg --clearance 0.35
```

or tune your X/Y compensation, which is worth doing anyway.

Then slide the LED panel into the cavity, feed the cable out through the USB-C cutout,
and close it up. The top wall is intentionally thin (≤3 mm) so a touch-sensitive panel
can be triggered through it.

## Getting a good result

**Choose the right photo.** High local contrast and saturated colour work best. A
backlit print has roughly 7 levels per channel — subtle tonal photography loses most of
its subtlety. Portraits with clean lighting, graphic illustrations, and saturated
landscapes all do well. Dark, low-contrast, or heavily textured images do not.

**Crop before you convert.** The generator fits the image to your requested frame; it
does not know what the subject is. Crop tight first.

**Size affects perceived sharpness more than grid density.** A 240 mm print at default
density looks sharper than a 120 mm print at double density, because you view it from
further away. Reach for `--mm-per-px 0.15` only when the print is small and the subject
is detailed — and be ready for a much slower slice.

**Check the light panel first.** More disappointing prints come from bad backlights than
from bad separation. If you can see individual LEDs through a sheet of paper held over
the panel, you will see them through the print.

---

<a name="打印指南中文"></a>

# 打印指南（中文）

3MF 里几乎所有参数都配好了。这里讲文件替你决定不了的部分，以及最费料的那些坑。

## 需要什么

| | |
|---|---|
| **打印机** | 多材料。在 Bambu Lab X1C + AMS 上开发，同级别机器都可以 |
| **耗材** | 青、品红、黄、白四色 PLA，外加一卷做外壳的颜色 |
| **灯板** | 平整、均匀、漫射的 Type-C LED 灯板，尺寸配合画片 |
| **切片** | Bambu Studio（3MF 是 Bambu 工程文件） |

**必须用 PLA。** PETG 和 ABS 比 PLA 更透，颜色会被冲淡；密度常数是按 PLA 标的。
丝绸和哑光系列透射差别明显——那组数字是在 Basic 上测的。

## AMS 装料

槽位顺序写死在文件里。装错了图像会以很奇怪的方式反相：

| 槽位 | 耗材 |
|---|---|
| 1 | **青** |
| 2 | **品红** |
| 3 | **黄** |
| 4 | **白** |
| 5 | 外壳颜色（随意） |

如果你的 AMS 只有四槽，把两个盘分成两次打——外壳只用 5 号槽，画片完全不用它。

## 切片

**盘 1 — 画片**

| 参数 | 值 | 原因 |
|---|---|---|
| 层高 | **0.08mm** | 没得商量。所有密度常数都是「每 0.08mm 一层」。用 0.12 打出来会暗大约 50% |
| 填充 | **100%** | 低于这个，光会从缝隙漏出来，形成肉眼可见的斑驳 |
| 支撑 | 关 | 画片就是一块平板 |
| 擦料塔 | 开 | 文件里已经摆好位置了，别动 |

**平铺打印，图案面朝下。** 贴着热床的那面就是正面，纹理板会把纹理压在上面，
起到很好的漫射作用。光面板则得到更亮、更像镜面的表面——两种都好看，看你喜欢。

**盘 2 — 外壳**

0.2mm 层高，15–20% 填充，关支撑。它就是个盒子，别在上面耗几个小时。

## 换料会非常频繁

四种颜色在每一层里交错，打印机会不停换料，每次都要排废。
一张 135mm 的画片，**排废耗材通常比模型本身还多**。这是多色打印的固有代价，不是生成器的问题。

减少的办法：

- 一次多打几张——排废成本是按**层**算的，不是按物件，
  所以一盘四张画片的排废量比一张多不了多少
- `--mm-per-px` 保持默认；网格更密不会增加换色次数，但会增加好几个小时
- 复用废料——如果两盘一起打，给外壳盘开「排入填充」

## 组装

画片从正面卡槽推进去。默认间隙 0.2mm，在调校好的机器上是刚好偏紧的手感。

如果推不进去，说明你的机器在放大——要么把间隙调大：

```bash
python cli.py photo.jpg --clearance 0.35
```

要么去调 X/Y 尺寸补偿，那件事本来也值得做。

然后把 LED 灯板塞进内腔，线从 Type-C 孔穿出来，合上。
顶壁是刻意做薄的（≤3mm），好让触摸式灯板能隔着它被触发。

## 怎么打得好看

**选对照片。** 局部对比强、颜色饱和的效果最好。背光打印每通道大约只有 7 级，
细腻的影调摄影会丢掉大部分细腻。光线干净的人像、图形化插画、饱和的风景都很出彩。
暗的、低对比的、满是杂乱纹理的则不行。

**先裁剪再转换。** 生成器只会把图铺满你要的画幅，它不知道主体是什么。先裁紧。

**尺寸对清晰度的影响比网格密度大。** 240mm 的画在默认密度下，看起来比 120mm 的画用双倍密度还清晰，
因为你站得更远。只有在成品小、主体又很细的时候才上 `--mm-per-px 0.15`，并且做好切片变慢很多的准备。

**先检查灯板。** 让人失望的成品里，坏背光的比例远高于坏分色。
如果你隔着一张纸都能看见灯板上一颗颗的 LED，那你隔着画片也会看见。
