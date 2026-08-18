# 基准数据 / Reference fixtures

这些 JSON 由 Python 侧生成，用来保证 TypeScript 引擎与 Python 引擎的结果
**逐像素一致**。层数是整数，不存在「接近就行」。

These fixtures are generated from the Python engine so the TypeScript port can be
checked for pixel-exact parity. Layer counts are integers — "close enough" is not
a passing result.

| 文件 | 内容 |
|------|------|
| `separation-reference.json` | 重采样后的 RGB 输入 + 四通道层数（分色阶段） |
| `mesh-reference.json` | 中值滤波、圆角遮罩、矩形合并的结果（网格化阶段） |

## 重新生成

改动 Python 侧的分色或网格化逻辑后，必须重新生成基准并确认 TS 侧仍然通过：

```bash
# 在仓库根目录
py -3.11 tools/make_fixtures.py
cd web && npx vitest run
```

如果 TS 测试因此变红，说明两边逻辑已经分叉 —— 要么同步移植改动，
要么说明 Python 侧的改动是非预期的。
