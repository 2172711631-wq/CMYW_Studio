# 第三方组件与许可 / Third-Party Notices

> 本项目自身的许可说明见 [`NOTICE`](NOTICE) 与 [`LICENSE`](LICENSE)。
> 本文件只讲**桌面版打包时引入的第三方组件**及其强制义务。

CMYW Studio 本体版权归 CMYW Studio 所有，以 PolyForm Noncommercial 1.0.0 发布。
本文件列出桌面版所依赖的第三方组件及其许可证 —— **分发打包好的 .exe 时必须
随附本文件**，这是下列 LGPL 组件的强制要求。

This file lists third-party components bundled with the **desktop build**.
It MUST be distributed alongside any packaged `.exe`.

---

## 桌面版依赖

| 组件 | 许可证 | 备注 |
|---|---|---|
| NumPy | BSD-3-Clause | 宽松，署名即可 |
| OpenCV (`opencv-python`) | Apache-2.0（wrapper） | **随附的 FFmpeg 二进制为 LGPL-2.1**，见下 |
| Open3D | MIT | 宽松 |
| trimesh | MIT | 宽松 |
| Shapely | BSD-3-Clause | 宽松 |
| CadQuery | Apache-2.0 | 但其底层 **OCP / OpenCASCADE 为 LGPL-2.1**，见下 |
| PyInstaller | GPL-2.0 **with bootloader exception** | 该例外明确允许打包产物使用任意许可证，**不会传染** |

## ⚠️ LGPL 组件的实际义务

**OpenCASCADE**（经 CadQuery/OCP 引入）与 **FFmpeg**（经 opencv-python 引入）
均为 **LGPL-2.1**。把它们打进单文件 .exe 属于静态/捆绑分发，LGPL 要求你：

1. **声明**用到了这些库及其版本与许可证（本文件即为此）；
2. **提供其源码获取途径**（给官方下载链接即可，不必自己托管）；
3. 允许使用者**替换该库并重新链接**——实践中的通行做法是提供
   `--onedir` 形式的打包（依赖以独立 `.dll` / `.pyd` 存在，可被替换），
   而不是 `--onefile` 全部塞进一个可执行文件。

源码获取：
- OpenCASCADE — https://dev.opencascade.org/
- FFmpeg — https://ffmpeg.org/download.html

> **给商业授权买方的说明**：以上义务只涉及**桌面版**。
> 网页版引擎为纯 TypeScript 实现，不引入上述任何 LGPL 组件，
> 分发义务显著更轻。若买方计划集成进自有产品，建议以网页版引擎为准。

---

## 素材与商标

- **拓竹 / Bambu Lab** 为拓竹科技的商标。本项目与拓竹科技**无隶属、无合作、
  未获其背书**，仅在描述兼容性与官方耗材色号时按指名合理使用的方式提及。
- 本项目**不随附**任何第三方图片素材。示例图与实拍图的版权状态见
  项目维护者自行留存的清单。
