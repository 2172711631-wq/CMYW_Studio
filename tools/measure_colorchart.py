"""量印好的全色域色卡：一张背光照片 → 一张 `配方 → 实测颜色` 的表（ColorDB）。

    py -3.11 tools/measure_colorchart.py 照片.jpg

拍法：装进灯箱背光点亮，对着拍一张。**锁定曝光和白平衡**，别开 HDR、别开闪光 ——
色卡里最亮和最暗差了几十倍，自动模式会边拍边改，拍出来的每一格都不在同一把尺上。

不用裁，也不用拍得笔直：脚本自己找格子、自己纠正透视。以前要求"裁到只剩色卡"，
实际拿到的永远是手持斜拍的照片 —— 与其反复要求重拍，不如让脚本认得出来。

怎么找的：

  · **认色块，不认卡的边框。** 桌面上的键盘、纸、白墙都可能比卡还亮，按亮度找
    外框会框错（实测第一版就把键盘一起框进去了）。色块是画面里唯一"有彩度又方正"
    的一堆东西：按彩度筛一遍，再要求接近正方、填充率够高，剩下的就是它们。
  · **用全部色块反复配准。** 先按四个角的块猜一个透视矩阵，投影 → 就近配对 →
    重算，来回八轮。只用四个角会被卡片的微微弯曲带偏，用上三百个就稳了。
  · **再试整数错位。** 栅格是自相似的，整体错开一行一列照样能收敛得很漂亮，
    中位偏差 2px 却全错位 —— 肉眼一看才发现。所以把 Δ列/Δ行 在小范围里逐个试，
    取"格心落在彩色区上"比例最高的那个。版面本身不对称（第一行从第 1 列起、
    最后一行只有一格），这个分数能把真正的对位挑出来。

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
SAMPLE = 0.55         # 每格只取中心这么大一块，避开边缘那一圈打印瑕疵


def load_photo(path: str) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)          # 中文路径下 imread 会失败
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"读不出这张图：{path}")
    return img


def find_patches(img: np.ndarray):
    """画面里所有「有彩度又方正」的连通块的中心，以及那张彩度遮罩。"""
    hsv = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0), cv2.COLOR_BGR2HSV)
    mask = ((hsv[..., 1].astype(int) > 60) & (hsv[..., 2].astype(int) > 40)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    n, _, st, cen = cv2.connectedComponentsWithStats(mask, 8)
    areas = st[1:, cv2.CC_STAT_AREA]
    big = areas[areas > 500]
    if big.size < 20:
        raise SystemExit("认不出色块 —— 照片是不是没拍到色卡，或者太暗？")
    med = float(np.median(big))
    out = []
    for i in range(1, n):
        a = st[i, cv2.CC_STAT_AREA]
        bw, bh = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        if not med * 0.35 < a < med * 2.5:
            continue
        if not 0.6 < bw / max(1, bh) < 1.7:
            continue
        if a / float(bw * bh) < 0.6:
            continue
        out.append(cen[i])
    return np.array(out, np.float32), mask


def cell_centre_mm(meta: dict, col: int, row: int):
    pitch = meta["cell_mm"] + meta["gap_mm"]
    return (meta["gap_mm"] + col * pitch + meta["cell_mm"] / 2.0,
            meta["gap_mm"] + row * pitch + meta["cell_mm"] / 2.0)


def register(meta: dict, pts: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """算出「版面毫米坐标 → 照片像素」的透视矩阵。"""
    lay = np.array([cell_centre_mm(meta, p["col"], p["row"]) for p in meta["patches"]], np.float32)
    s, d = pts[:, 0] + pts[:, 1], pts[:, 0] - pts[:, 1]
    corners = np.array([pts[np.argmin(s)], pts[np.argmax(d)],
                        pts[np.argmin(d)], pts[np.argmax(s)]], np.float32)
    h, w = mask.shape[:2]
    c0, r0 = meta["patches"][0]["col"], meta["patches"][0]["row"]
    cN = max(p["col"] for p in meta["patches"])
    rN = meta["patches"][-1]["row"]

    def fit(dc: int, dr: int) -> np.ndarray:
        src = np.array([cell_centre_mm(meta, c0 + dc, r0 + dr),
                        cell_centre_mm(meta, cN + dc, r0 + dr),
                        cell_centre_mm(meta, c0 + dc, rN + dr),
                        cell_centre_mm(meta, cN + dc, rN - 1 + dr)], np.float32)
        mat = cv2.getPerspectiveTransform(src, corners)
        for _ in range(8):
            proj = cv2.perspectiveTransform(lay.reshape(-1, 1, 2), mat).reshape(-1, 2)
            dist = np.linalg.norm(pts[:, None, :] - proj[None, :, :], axis=2)
            j, dmin = dist.argmin(1), dist.min(1)
            ok = dmin < np.median(dmin) * 2.5 + 10
            if ok.sum() < 20:
                break
            nxt, _ = cv2.findHomography(lay[j[ok]], pts[ok], cv2.RANSAC, 8.0)
            if nxt is None:
                break
            mat = nxt
        return mat

    def hit_rate(mat: np.ndarray) -> float:
        proj = cv2.perspectiveTransform(lay.reshape(-1, 1, 2), mat).reshape(-1, 2).astype(int)
        inb = (proj[:, 0] >= 0) & (proj[:, 0] < w) & (proj[:, 1] >= 0) & (proj[:, 1] < h)
        if not inb.any():
            return 0.0
        q = proj[inb]
        return float(mask[q[:, 1], q[:, 0]].mean()) * float(inb.mean())

    best = None
    for dc in range(-2, 3):
        for dr in range(-3, 4):
            mat = fit(dc, dr)
            rate = hit_rate(mat)
            if best is None or rate > best[0]:
                best = (rate, dc, dr, mat)
    rate, dc, dr, mat = best
    print(f"  认出色块 {len(pts)} 个；对位偏移 Δ列={dc} Δ行={dr}，格心命中彩色区 {rate * 100:.1f}%")
    if rate < 0.75:
        print("  ← **对位可能不准**。多半是照片太暗、太糊，或者色卡被手指挡住了一角。")
    return mat


def sample(img: np.ndarray, mat: np.ndarray, meta: dict, col: int, row: int):
    """取一格的中位色（BGR，0..1）。按透视把格子的四角投过去，再取里面那块。"""
    cx, cy = cell_centre_mm(meta, col, row)
    r = meta["cell_mm"] * SAMPLE / 2.0
    box = np.array([[[cx - r, cy - r]], [[cx + r, cy - r]],
                    [[cx + r, cy + r]], [[cx - r, cy + r]]], np.float32)
    q = cv2.perspectiveTransform(box, mat).reshape(4, 2)
    h, w = img.shape[:2]
    x0, y0 = np.floor(q.min(0)).astype(int)
    x1, y1 = np.ceil(q.max(0)).astype(int)
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(w, int(x1)), min(h, int(y1))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    return np.median(img[y0:y1, x0:x1].reshape(-1, 3), axis=0) / 255.0


def to_lab(rgb: np.ndarray) -> np.ndarray:
    x = np.clip(rgb, 1e-6, 1.0).astype(np.float32).reshape(1, 1, 3)
    return cv2.cvtColor(x, cv2.COLOR_RGB2Lab).reshape(3)


def main(path: str) -> int:
    if not os.path.exists(META):
        raise SystemExit(f"缺版面文件 {META}，先跑 tools/make_colorchart.py")
    meta = json.load(open(META, encoding="utf-8"))
    img = load_photo(path)
    print(f"  照片 {img.shape[1]} × {img.shape[0]}，版面 {meta['cols']} × {meta['rows']} 格")

    pts, mask = find_patches(img)
    mat = register(meta, pts, mask)

    # 白点 = 参照列（光秃白底）。背光不匀就靠它逐行校平 ——
    # 不然测出来的「颜色」里混着灯的不均匀，而那正是我们要测的量级。
    ref = {}
    for row in range(meta["rows"]):
        v = sample(img, mat, meta, meta["ref_col"], row)
        if v is not None:
            ref[row] = v
    if len(ref) < 3:
        raise SystemExit("参照列取不到，检查对位是不是错了")
    vals = np.array(list(ref.values()))
    spread = float((vals.max(0) / np.maximum(vals.min(0), 1e-6)).mean())
    print(f"  背光不均匀：最亮/最暗参照格 = {spread:.2f}×"
          + ("（可以接受）" if spread < 1.25 else "  ← **偏大，测出来的会带上灯的不匀**"))
    rows = np.array(sorted(ref))
    field = np.stack([np.interp(np.arange(meta["rows"]), rows,
                                [ref[r][ch] for r in rows]) for ch in range(3)], 1)
    white = field.max(0)

    entries, missed = [], 0
    for p in meta["patches"]:
        v = sample(img, mat, meta, p["col"], p["row"])
        if v is None:
            missed += 1
            continue
        rel = np.clip(v / np.maximum(field[p["row"]], 1e-6)
                      * (field.max(0) / np.maximum(white, 1e-6)), 0, 1)[::-1]   # BGR → RGB
        entries.append({
            "c": p["c"], "m": p["m"], "y": p["y"], "w": meta["white"],
            "rgb": [round(float(x), 5) for x in rel],
            "lab": [round(float(x), 3) for x in to_lab(rel)],
        })

    out = os.path.join(CAL, "colordb.json")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"white_layers": meta["white"], "entries": entries}, fh,
                  ensure_ascii=False, separators=(",", ":"))
    labs = np.array([e["lab"] for e in entries])
    print(f"  测到 {len(entries)} 条配方" + (f"（{missed} 格没取到）" if missed else ""))
    print(f"  L* 范围 {labs[:, 0].min():.0f} – {labs[:, 0].max():.0f}"
          f"   彩度 C* 最高 {np.hypot(labs[:, 1], labs[:, 2]).max():.0f}")
    print(f"\n  {out}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
