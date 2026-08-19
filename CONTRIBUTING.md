# Contributing

Thanks for looking. This project is small and practical — issues and pull requests are
both welcome, and you do not need to ask permission before opening either.

感谢关注。这个项目不大，issue 和 PR 都欢迎，不用先问再提。

## Good first contributions

- **Filament calibration data.** The density constants are working values for Bambu PLA
  Basic — they are not instrument measurements, just numbers that hold up well in print.
  If you derive a set for another filament, that is the single most useful thing you can
  contribute. Run `py -3.11 tools/make_wedge.py`, print the plate, photograph it backlit
  and run `tools/measure_wedge.py` — full procedure in
  [docs/how-it-works.md](docs/how-it-works.md#calibrating-for-your-own-filament).
  Include your numbers and a photo of the wedge.
- **Printer support.** Output is currently a Bambu project 3MF. A plain 3MF or
  per-colour STL exporter would open this up to Prusa MMU, ERCF and others.
- **Sample prints.** Photos of what you made, especially of failures, help everyone
  calibrate expectations.

## Reporting a problem

Include:

1. The command or GUI settings you used
2. Your Python version and OS
3. The source image, if you can share it — colour problems are almost impossible to
   diagnose without it
4. A photo of the printed result if the issue is about appearance rather than a crash

## Code

- Python 3.11 (CadQuery does not support 3.12+ yet)
- Match the surrounding style; the codebase uses type hints and short Chinese comments
  for the domain-specific parts
- Keep the optical constants in `main.py` — they are the tuned core, and scattering them
  makes results irreproducible
- If you change anything in the separation path, say what you compared against. "Looks
  better" needs a before/after on the same source image

The browser engine has a test suite (`cd web && npm run verify` — type-check plus
vitest). It pins the Python and TypeScript separation to pixel-for-pixel parity against
fixtures, so **if you touch the separation path, regenerate them with
`py -3.11 tools/make_fixtures.py` and re-run `npm run verify`**. Two porting traps that
cause silent drift rather than a crash: NumPy rounds half-to-even, and the Python side
is float32 throughout. The Python CLI has no tests yet; adding them is on the roadmap.

## Licence and contributor terms

CMYW Studio is available under the [PolyForm Noncommercial 1.0.0](LICENSE) licence, and
commercial licences are sold separately to fund the work. For that to be possible, the
maintainer has to be able to license the whole codebase — including your contribution —
under those commercial terms.

So by opening a pull request you confirm that:

1. You wrote the contribution, or you have the right to submit it.
2. You license it to the project under PolyForm Noncommercial 1.0.0, **and** you grant
   the maintainer permission to also distribute it under other licence terms, including
   commercial ones.
3. You keep your own copyright. This is a licence grant, not an assignment — you can
   still use your own code anywhere you like.

This is the standard arrangement for dual-licensed projects. If you are not comfortable
with point 2, open an issue and describe the change instead of sending code — a good
description is still a real contribution.

CMYW Studio 采用 [PolyForm Noncommercial 1.0.0](LICENSE) 发布，商业授权单独出售以支持
项目继续做下去。要让这件事成立，维护者必须能对整个代码库（包括你的贡献）按商业条款授权。

因此，当你提交 PR 时，即表示确认：

1. 这是你写的，或者你有权提交它。
2. 你按 PolyForm Noncommercial 1.0.0 授权给本项目，**并且**允许维护者同时以其它条款
   （包括商业条款）分发它。
3. 版权仍归你。这是授权，不是转让——你自己的代码你想用在哪都可以。

这是双轨授权项目的标准做法。如果你不接受第 2 条，可以改为开 issue 描述你的方案而不提交
代码——一个好的方案描述同样是实实在在的贡献。
