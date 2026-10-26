# pico-tooling

Shared infrastructure for the pico family's independent libraries: the family
input and generated bootstrap, family gates, an infrastructure pin report,
library scaffolding and CMake entry points. Each library pins this repository
at `infra`; this repository pins House at `house`.

Run `python3 dev.py check --ci` after initializing recursive submodules.
Prepare declared tools explicitly with `python3 dev.py toolchain install
--profile tests`, then run `python3 dev.py toolchain run pytest -W error`.
On Windows use `python3` or the optional `py -3` launcher.

[Documentation](docs/README.md) explains the layer and its requirements.
This repository is developed with AI assistance; the maintainer owns design,
review and acceptance.
