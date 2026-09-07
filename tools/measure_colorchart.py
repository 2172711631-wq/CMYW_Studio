"""量印好的全色域色卡：一张背光照片 → 一张 `配方 → 实测颜色` 的表（ColorDB）。

    py -3.11 tools/measure_colorchart.py 照片.jpg

拍法：装进灯箱背光点亮，正对拍一张。**锁定曝光和白平衡**，别开 HDR、别开闪光 ——
色卡里最亮和最暗差了几十倍，自动模式会边拍边改，拍出来的每一格都不在同一把尺上。
裁到只剩色卡本身（四边贴着色卡外缘）再跑。

两件事这个脚本会替你做：

  · **校平背光。** 每行第一格是光秃白底，背光不均匀会让它们亮度不一。
    按这些参照格拟合出一张平缓的亮度场，再把整张照片除掉它 ——
    不然测出来的"颜色"里混着灯的不均匀，而那正是我们要测的量级。
  · **对齐格子。** 按 make_colorchart 写出的版面 JSON 切格，每格只取中心 60%，
    避开边缘那一圈打印瑕疵。

输出 calibration/colordb.json：每条是 {c,m,y,w, rgb, lab}。
之后查表选配方就用它，不再需要密度常数 —— 也就没有模型误差。
"""

from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import cv2
import numpy as np

CAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "calibration")
META = os.path.join(CAL, "全色域色卡_版面.json")
SAMPLE = 0.6          # 每格只取中心这么大一块


def load_photo(path: str) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)          # 中文路径下 imread 会失败
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"读不出这张图：{path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0


def cell_rect(meta: dict, col: int, row: int, h: int, w: int):
    """按版面的**真实几何**把照片切成格，不是按列数平分。

    版面是「边距 + 格 + 缝 + 格 + …」，直接用宽度除以列数会把边距摊进每一格，
    跨过整张就漂掉大半个缝 —— 边上的格子会采到隔壁去。自检时这一处差了
    17/255，本该是 0。
    """
    gap = meta["gap_mm"]
    cell = meta["cell_mm"]
    pitch = cell + gap
    sx = w / meta["width_mm"]
    sy = h / meta["height_mm"]
    cx = (gap + col * pitch + cell / 2.0) * sx
    cy = (gap + row * pitch + cell / 2.0) * sy
    rx = cell * sx * SAMPLE * 0.5
    ry = cell * sy * SAMPLE * 0.5
    return (slice(max(0, int(cy - ry)), min(h, int(cy + ry))),
            slice(max(0, int(cx - rx)), min(w, int(cx + rx))))


def flat_field(img: np.ndarray, meta: dict) -> np.ndarray:
    """用每行的参照格拟合背光的亮度场（行方向线性，够用了）。"""
    h, w = img.shape[:2]
    ys, vals = [], []
    for row in range(meta["rows"]):
        sl = cell_rect(meta, meta["ref_col"], row, h, w)
        patch = img[sl]
        if patch.size == 0:
            continue
        ys.append((row + 0.5) / meta["rows"] * h)
        vals.append(np.median(patch.reshape(-1, 3), axis=0))
    if len(ys) < 2:
        raise SystemExit("参照格取不到，检查照片是不是裁到色卡外缘了")
    ys = np.array(ys)
    vals = np.array(vals)                              # (rows, 3)
    field = np.empty((h, 3), np.float32)
    yy = np.arange(h, dtype=np.float32)
    for ch in range(3):
        k, b = np.polyfit(ys, vals[:, ch], 1)
        field[:, ch] = k * yy + b
    spread = vals.max(axis=0) / np.maximum(vals.min(axis=0), 1e-6)
    print(f"  背光不均匀：最亮/最暗参照格 = {spread.mean():.2f}×"
          + ("（可以接受）" if spread.mean() < 1.25 else "  ← **偏大，换个更匀的灯板重拍会更准**"))
    return field


def to_lab(rgb: np.ndarray) -> np.ndarray:
    x = np.clip(rgb, 1e-6, 1.0)
    mx = np.array([[0.4124, 0.3576, 0.1805],
                   [0.2126, 0.7152, 0.0722],
                   [0.0193, 0.1192, 0.9505]], np.float32)
    xyz = x @ mx.T
    ref = np.array([0.9505, 1.0, 1.089], np.float32)
    t = xyz / ref
    d = 6.0 / 29.0
    ft = np.where(t > d ** 3, np.cbrt(t), t / (3 * d * d) + 4.0 / 29.0)
    return np.stack([116 * ft[..., 1] - 16,
                     500 * (ft[..., 0] - ft[..., 1]),
                     200 * (ft[..., 1] - ft[..., 2])], -1)


def main(path: str) -> int:
    if not os.path.exists(META):
        raise SystemExit(f"缺版面文件 {META}，先跑 tools/make_colorchart.py")
    meta = json.load(open(META, encoding="utf-8"))
    img = load_photo(path)
    h, w = img.shape[:2]
    print(f"  照片 {w} × {h}，版面 {meta['cols']} × {meta['rows']} 格")

    field = flat_field(img, meta)
    white = field.max(axis=0)                          # 最亮的参照 = 光秃白底 = 白点

    entries = []
    for p in meta["patches"]:
        sl = cell_rect(meta, p["col"], p["row"], h, w)
        patch = img[sl]
        if patch.size == 0:
            continue
        raw = np.median(patch.reshape(-1, 3), axis=0)
        # 除掉该行的背光亮度，再按白点归一 → 相对透射率
        corr = raw / np.maximum(field[int((p["row"] + 0.5) / meta["rows"] * h)], 1e-6)
        rel = np.clip(corr * (field.max(axis=0) / np.maximum(white, 1e-6)), 0, 1)
        entries.append({
            "c": p["c"], "m": p["m"], "y": p["y"], "w": meta["white"],
            "rgb": [round(float(v), 5) for v in rel],
            "lab": [round(float(v), 3) for v in to_lab(rel)],
        })

    out = os.path.join(CAL, "colordb.json")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"white_layers": meta["white"], "entries": entries}, fh,
                  ensure_ascii=False, separators=(",", ":"))
    labs = np.array([e["lab"] for e in entries])
    print(f"  测到 {len(entries)} 条配方")
    print(f"  L* 范围 {labs[:,0].min():.0f} – {labs[:,0].max():.0f}"
          f"   彩度 C* 最高 {np.sqrt((labs[:,1:]**2).sum(1)).max():.0f}")
    print(f"\n  {out}")
    print("\n  接下来我拿它跟模型对一遍，就知道四个常数偏在哪、偏多少。")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
