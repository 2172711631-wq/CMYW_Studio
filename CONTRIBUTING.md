# Contributing

Thanks for looking. This project is small and practical — issues and pull requests are
both welcome, and you do not need to ask permission before opening either.

感谢关注。这个项目不大，issue 和 PR 都欢迎，不用先问再提。

## Good first contributions

- **Filament calibration data.** The density constants are measured for Bambu PLA Basic
  only. If you measure a set for another filament, that is the single most useful thing
  you can contribute — see [docs/how-it-works.md](docs/how-it-works.md#calibrating-for-your-own-filament)
  for the procedure. Include your measurements and photos of the test wedge.
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
- Keep the optical constants in `main.py` — they are the calibrated core, and scattering
  them makes results irreproducible
- If you change anything in the separation path, say what you compared against. "Looks
  better" needs a before/after on the same source image

There is no test suite yet. Adding one is on the roadmap and would be very welcome —
sensible starting points are the layer histogram for a fixed test image, and the shell's
outer dimensions and watertightness.

## Licence

Contributions are accepted under the AGPL-3.0, the same licence as the project.
