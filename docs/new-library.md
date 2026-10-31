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

## Device tests

A library with code a host test cannot establish, such as a hardware layer or a
transport, adds a device-test image under `tests/device/`:

```text
tests/device/CMakeLists.txt
tests/device/main.cpp
```

The top-level CMakeLists.txt adds it beside `examples/`, in firmware builds of
the top-level project only, since the host `tests/` tree is not configured in a
firmware build:

```cmake
if(PROJECT_IS_TOP_LEVEL AND <PREFIX>_BUILD_FIRMWARE)
    add_subdirectory(tests/device)
endif()
```

`tests/device/CMakeLists.txt` adds the image:

```cmake
pico_family_add_device_test(<package>_device_tests
    PACKAGE <package>
    SOURCES main.cpp
    LIBRARIES <package>::<library>)
```

`main.cpp` records each case with `pico_family::device_test::Results`, named
`<requirement ID> <case-name>`, calls `wait_for_console()`, then
`report_forever(results)`. The top-level strict target takes
`VENDOR_SOURCES ${<PREFIX>_BUILD_FIRMWARE}` so the SDK's sources are not compiled
with `-Werror`. Run it with `device test`; see the
[device guide](../guides/device.md#device-tests) for the command, the TAP
subset and the run record.
