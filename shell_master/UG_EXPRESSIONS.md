# 灯箱外壳参数约定（代码母本）

运行时母本：[`shell_cadquery.py`](shell_cadquery.py)  
改尺寸优先改文件开头**全局变量**，或由网站映射同名参数。

## 参数

| 变量 | 含义 | 默认 | 硬限制 |
|---|---|---|---|
| `ART_W` / `ART_H` | 画片宽高 | 120 / 90 | — |
| `ART_THICKNESS` | 画片厚度 = 卡槽深 | 2.5 | — |
| `WALL` | 底/左/右壁厚 | 3.0 | — |
| `TOP_THICKNESS` | 顶壁（触摸）厚度 | **2.0** | **≤ 3.0** |
| `DEPTH` | 外壳外深 Z | 18 | — |
| `CORNER` | 圆角 | 5 | — |
| `CLEARANCE` | 装配间隙 | 0.2 | — |
| `FDM_TOL` | 打印公差 | 0.2 | — |
| Type-C | 名义 9.0×3.2 R1.6 + FDM_TOL + 四周外扩 0.05；抬高 `USB_LIFT_Z=1.55` | — | 开在 **右壁中心** |

## 建模步骤（代码里同序）

1. 全局变量  
2. 外实体 − 内腔（顶壁单独用 `TOP_THICKNESS`）  
3. 布尔挖画片卡槽  
4. 并入 PCB 台 → 布尔挖 Type-C  
5. 导出 STL  

## 坐标系

开口 +Z，底板 Z=0；+X 右侧（USB）；+Y 顶部（触摸薄壁）。

## 自测

```bash
py -3.11 shell_master/shell_cadquery.py
```

生成 `shell_master/preview_shell.stl`，用 Bambu Studio 打开检查卡槽 / Type-C / 顶壁厚度。
