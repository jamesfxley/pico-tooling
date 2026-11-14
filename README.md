# pico-tooling

pico-tooling provides configuration, checks and CMake helpers for the pico
family's independent libraries. Each library pins pico-tooling at `infra`;
pico-tooling pins House at `house`. House is the platform that runs commands
and generic checks. A pin fixes a dependency to a revision. A gate is a check
run by House. The generated bootstrap is the CMake file that selects the
pico-tooling checkout for a build.

pico-tooling also reports library pins and scaffolds new libraries.
[Usage](docs/usage-guide.md) describes these commands.

Run `python3 dev.py check --ci` after initialising recursive submodules.
Prepare declared tools explicitly with `python3 dev.py toolchain install
--profile tests`, then run `python3 dev.py toolchain run pytest -W error`. On
Windows use `python3` or the optional `py -3` launcher.

[Documentation](docs/README.md) explains the layer and its requirements. This
repository is developed with AI assistance; the maintainer owns design, review
and acceptance.
