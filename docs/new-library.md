# New libraries

From a clean committed pico-tooling checkout, run:

```text
python3 -m pico_tooling scaffold ../pico-new --name pico-new --infra-repository https://github.com/jamesfxley/pico-tooling.git --lang cxx
```

The scaffold pins infra and its nested House, refers to `family = "infra"`, and
writes pico.toml and the generated CMake bootstrap. The single scaffold commit
records the distribution URL, without a local checkout URL in its history.
The name supplies the README title and CMake package/target identifiers:
`pico-drv8833` uses `pico_drv8833` and option prefix `PICO_DRV8833`. The generated
AGENTS.md describes a library and points to infra/agents/AGENTS.md. There is no adapter directory. Initialize recursive pins
before running `python3 dev.py check --ci`.

The library's choices are a short list:

- house.toml: family, packages, consumer_cases and repository overrides.
- pico.toml: name, infra release repository, footprint and symbols budgets.
- CMakeLists.txt: product dependency calls; declare all pins with
  pico_family_dependency before calling pico_family_make_available.

House renders root configuration and the devcontainer from the family overlay.
The bootstrap alone carries the infra revision and URL for source consumers
whose infra directory is absent. Run `python3 -m infra.pico_tooling sync` after
moving the infra pin, then `python3 dev.py sync` and review the resulting diff.
A library owns tests/.clang-tidy; a scope disable needs its approved deviation.
See [build.md](build.md) for build modes and [usage-guide.md](usage-guide.md) for
CMake helper signatures and gate budgets.

See [installed SDK links](usage-guide.md#installed-sdk-links) for exporting
SDK-linked targets and restoring their links in installed consumers.
