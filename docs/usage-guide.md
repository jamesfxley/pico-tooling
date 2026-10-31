# Usage

Run these from a library root whose `infra` pins this repository:

```text
python3 -m infra.pico_tooling sync            # write family-owned output (AR-2)
python3 -m infra.pico_tooling sync --check    # compare only
```

From this repository, report pins across explicitly named libraries (AR-5) or
scaffold a new library (AR-7):

```text
python3 -m pico_tooling report util=../pico-util logging=../pico-logging@HEAD
python3 -m pico_tooling scaffold ../pico-new --name pico-new \
    --infra-repository https://github.com/jamesfxley/pico-tooling.git --lang cxx
```

The report names local repository paths only; a URL is refused.

## Tree profiles and the dev container

`family = "infra"` in house.toml imports the firmware tree directly from
`pico_tooling.profiles:firmware`. It is enabled when PICO_SDK_PATH names an SDK,
uses Release, and selects HOUSE_MATRIX_BOARD, PICO_BOARD or pico2_w, in that
order.

The family accepts any board the Pico SDK defines: a board header shipped with
the SDK or one found through `PICO_BOARD_HEADER_DIRS`. The SDK refuses a board
it cannot find. A library refuses a board it cannot run on through the
`PLATFORM` and `CYW43` arguments of `pico_family_bootstrap`. A library adds a
firmware leg for a board to the `board` matrix of its `firmware` entry in
`[[ci.require]]` in house.toml; the family default is `pico2_w`.

| Board | `PICO_PLATFORM` | CYW43 radio | clang-tidy system includes |
|---|---|---|---|
| `pico` | `rp2040` | no | recorded |
| `pico_w` | `rp2040` | yes | recorded |
| `pico2` | `rp2350-arm-s` | no | recorded |
| `pico2_w` (default) | `rp2350-arm-s` | yes | recorded |
| RP2350B or other SDK board | from its header | from its header | none |
| Custom header in `PICO_BOARD_HEADER_DIRS` | from its header | from its header | none |

A board with recorded system includes gives clang-tidy the cross compiler's
include directories for its platform. For any other board the firmware tree
passes none.

House owns sanitize: declare `house_cxx_enable_sanitizers(PREFIX)` and set
HOUSE_MATRIX_SANITIZE=ON. The build stays Debug with leak detection enabled.

House renders `.devcontainer/devcontainer.json` from its editor base plus the
family's build and seccomp overlay. `tests/.clang-tidy` is library-owned and
requires a registered approved deviation for any scope disable.

## Device commands

Run `python3 -m infra.pico_tooling device` from the dev container. The only
transport is the Windows host proxy for Docker Engine in WSL NAT mode. See the
[device guide's firewall scope](../guides/device.md#one-time-setup)
for host setup and network access.
The installed launcher runs before the
container opens and the proxy ends with the container.
The host owns its allow-list; the container only receives a workspace token.
An unavailable proxy exits 2 with its host:port and instructions to run the
installed `start-device-proxy.ps1` on Windows before using device commands.
It prints no token and does not retry. Commands never build.

See the [device guide](../guides/device.md) for setup, `device list`,
`device flash --serial S`, `device console`, agent capture with
`--until RE --timeout S --log FILE`, the blank-board BOOTSEL requirement,
protocol and exit statuses. Every real board action needs explicit user
authorization naming the serial and intended image.

## Embedded gates

A library with a firmware image declares it in `pico.toml` (AR-11):

```toml
[[footprint]]
name = "bench"
elf = "build-firmware/examples/bench/app.elf"
ram_kib = 20
flash_kib = 128
owned_prefix = "src"   # optional, given together with owned_kib
owned_kib = 48

[[symbols]]
name = "log probe"
mode = "objects"       # or "image"
path = "build-firmware/tests/firmware/CMakeFiles/probe.dir"
sets = ["c-heap-alloc"]

[[symbols]]
name = "log probe refuses its fixture"
mode = "objects"
path = "build-firmware/tests/firmware/CMakeFiles/allocating_fixture.dir"
sets = ["c-heap-alloc"]
expect = "refused"     # a control: this fixture must trip the set
```

A table with `expect = "refused"` is a negative control for the declaration
above
it: it points at a fixture that must be refused. It passes only when one of its
own
sets finds a symbol, so a mistyped path, a renamed target or a set that no
longer
matches fails the gate instead of passing for ever. A fixture that is clean, or
is
refused only by another set, fails naming the table; a missing input is still
reported as cannot run.

The family declares both gates in the firmware group; absent tables are not
applicable. Build the firmware first, with arm-none-eabi-objdump and -nm on
PATH.
`python3 -m infra.pico_tooling sync` writes only the bootstrap; House sync owns
its configuration copies and workflow.

Footprint uses `arm-none-eabi-objdump -h`. Flash sums every `LOAD` section.
Static RAM is the sum of every
`ALLOC` section except a `LOAD, READONLY` section with equal VMA and LMA,
`.heap`, and section names starting with `.stack`. An image with no loaded
bytes is unavailable, not a passing zero.
Owned flash still uses source-attributed `arm-none-eabi-nm` symbols. Findings
outrank unavailable rows, whose names remain in the result message; without
findings, an unavailable row makes the gate CANNOT_RUN. Symbol reports remain
in the result in either case.

A footprint row may include `when = { profile = "p8-rp2350" }`. Each key is a
matrix axis name matching `[a-z][a-z0-9_]*`; each value is a non-empty string.
The row is measured only when every `HOUSE_MATRIX_<UPPERCASE_AXIS>` environment
variable equals its declared value. Unset or different values leave the row
unmeasured and reported as `not applicable`, not as a passed measurement.
An omitted or empty `when` table applies always. This selector is available
only on footprint rows; it does not change symbol checks or measurement rules.

## CMake entry points

A library includes its generated `cmake/pico_family_bootstrap.cmake` before
`project()`. The bootstrap includes `cmake/pico_family.cmake` (AR-6) and calls
the private selector `_pico_family_context`, which records the selected root,
its actual revision and working-tree state, and its release version from
`pyproject.toml`, and reports
an infrastructure root that differs from the pinned revision, or is dirty, as an
override. The bootstrap records the pinned metadata's requested version.
The selected version must be at least that request and share its major, or its
minor too below 1.0. Refusals name both versions and pins. Compatible requests
reuse the context and report their own pin. The selector is private.
An entry point with keywords refuses
unrecognised arguments, and a keyword given no value, with a `FATAL_ERROR`
naming the call. A family library declares `cmake_minimum_required(VERSION
3.26)`:
`pico_family_bootstrap` refuses an older CMake and names the reason, which is
that `$<BUILD_LOCAL_INTERFACE:>` was added in 3.26. House's generic C++ template
declares 3.24, so a library written from it raises its own minimum.

| Entry point | Behaviour and contract |
|---|---|
| `pico_family_bootstrap(<PREFIX> [PLATFORM <p>] [CYW43])` | A macro, before `project()`. Defines `<PREFIX>_BUILD_FIRMWARE`, defaulting ON only when the `PICO_SDK_PATH` CMake variable names an SDK; the environment alone never turns it on. A top-level firmware build validates the SDK, accepts any board the SDK defines (an environment `PICO_BOARD` other than `pico2_w`, with no variable, is refused) and includes the SDK once. A dependency requires the parent to have imported the SDK. `PLATFORM` refuses a board whose `PICO_PLATFORM` does not start with `<p>`, and `CYW43` refuses a board without the radio |
| `pico_family_init_sdk(<firmware>)` | A macro, after `project()`. On a firmware build the top-level project calls `pico_sdk_init()` once; a dependency checks that its parent did and is refused otherwise. A no-op on host |
| `pico_family_dependency(<name> REPOSITORY <url> REVISION <id>)` | Declares one pinned product dependency with no submodules and requires a full commit ID. The first declaration of a name wins; a different later pin is reported as not used. `FETCHCONTENT_SOURCE_DIR_<NAME>` overrides it and is reported with its revision and uncommitted state. It populates nothing |
| `pico_family_make_available(<name>...)` | A macro that populates the named declared dependencies. The library declares every pin in CMakeLists.txt, then calls this once |
| `pico_family_sdk_link_libraries(<target> [PUBLIC <lib>...] [PRIVATE <lib>...])` | Links SDK libraries to an exported target through `$<BUILD_LOCAL_INTERFACE:>`, which keeps them out of both exports. It records the links in the target properties `PICO_FAMILY_SDK_LINKS_PUBLIC` and `..._PRIVATE`. Every library must be under `PUBLIC` or `PRIVATE`, and at least one is required. Pass the generated SDK snippet to the package exporter for installed consumers |
| `pico_family_sdk_config_snippet(<out-var> TARGETS <target>...)` | Writes the recorded SDK links beneath the current build directory and returns its path. Package and imported namespace are `PROJECT_NAME`. Pass the path as House’s `CONFIG_SNIPPET`; the consumer initializes the SDK before `find_package`. With no recorded links the snippet is empty |
| `pico_family_require_lwipopts_target(<library> [FALLBACK <target>])` | A macro that requires the application to name the one target carrying `lwipopts.h` in the cache variable `PICO_LWIPOPTS_TARGET`. The refusal names the library and, with `FALLBACK`, the standalone command |
| `pico_family_declare_profile(<PREFIX> NAME <name> DEFAULT <value> VALUES <value>... [DOC <text>])` | Declares the whole-build sizing profile `<PREFIX>_<NAME>` as a cached string restricted to the listed values; a value outside the set, including an empty one, is refused naming the set. A second declaration of the same variable with a different default or value set, from another library, is fatal and names both directories; an identical one is a no-op |
| `pico_family_declare_probe_option(<PREFIX>)` | A macro. Declares `<PREFIX>_ENABLE_FIRMWARE_PROBE`, on only for a top-level cross-compiling configure, so the probe is built exactly when its question is meaningful |
| `pico_family_add_cross_probe(<target> PACKAGE <package> SOURCE <file> [LIBRARIES <target>...])` | A freestanding cross-compiled executable with the suffix `.elf`, built from `SOURCE` and the shared stub, linked to `<package>_strict` and `LIBRARIES`, with C++20, no exceptions, no RTTI and `--specs=nosys.specs`. The 21 libnosys syscall names are bound to the stub as described below. It needs the context's `PICO_FAMILY_ROOT`, so a library calls it after its bootstrap. `PACKAGE` and `SOURCE` are required |
| `pico_family_propagate_install(<PREFIX> <dependency prefix>...)` | A macro. When `<PREFIX>_ENABLE_INSTALL` is on it forces each `<dependency prefix>_ENABLE_INSTALL` on, so installing a library installs the dependencies its export names. At least one dependency is required |

A cross probe links no SDK library, so the C library's system calls have nothing
behind them and libnosys's stubs for them warn at link time. The probe binds
each
of the 21 names to the one stub in `cmake/cross_probe_stub.cpp` with
`LINKER:--defsym=<name>=pico_family_probe_unsupported`, so no source spells a
name
the C library fixes and no suppression is needed. `_sbrk` and `_exit` stay with
nosys. The GNU ld manual, "Command-line Options", `--defsym=symbol=expression`
(<https://sourceware.org/binutils/docs-2.45/ld/Options.html>), says the option
creates "a global symbol in the output file, containing the absolute address
given
by expression" and that the expression may be the name of an existing symbol.
The
image's `arm-none-eabi-ld` is GNU ld 2.45.50.20251209, a development snapshot
after
2.45, so the 2.45 manual is the nearest published one. The manual does not say
what
a call through a name bound to a function does at run time. That is UNCONFIRMED,
and a probe is never run.

### Installed SDK links

For exported targets that call `pico_family_sdk_link_libraries`, call
`pico_family_sdk_config_snippet(sdk_config TARGETS <exported targets...>)`
and pass `CONFIG_SNIPPET "${sdk_config}"` to `house_cxx_install_package`.
The package and namespace are the library's `PROJECT_NAME`. The snippet restores
recorded public and private SDK links after importing the package targets; the
consumer must initialize its SDK before `find_package`. No snippet content is
emitted when the targets have no recorded SDK links.

## Tests

`python3 dev.py toolchain run pytest -W error` runs every test that needs only
CMake, Git and a host compiler. One test, marked `real_sdk`, configures firmware
against a real Pico SDK. It reads the SDK from `PICO_FAMILY_TEST_SDK`, never
from
`PICO_SDK_PATH`, and skips with its reason when the variable, the SDK or
`arm-none-eabi-gcc` is absent. A scaffolded fixture exercises family loading
against the real local layers.

## Infrastructure freshness

`python3 dev.py gate family-freshness` compares the pin with the current
release.
A stale or unreleased pin passes with "infra pin <pin> is behind the current
release <tag>; adopt it". With `GITHUB_ACTIONS=true`, a column-zero
`::warning title=family-freshness::` annotation precedes the same plain message.
Missing or unreadable release tags are CANNOT_RUN. pico.toml accepts only
`repository` under `[infra]`.

## Distro removal

The Windows distro is provisioned by `host/setup-dev-distro.ps1`, with the
in-distro `host/in-dev-distro.sh`. Start with the
[device guide](../guides/device.md#one-time-setup) before proxy setup.

The setup script has no removal mode. WSL's `wsl --unregister <name>`
permanently deletes that distro's entire filesystem, including workspaces,
images and settings. Preserve needed data and confirm the target name before
using that command.
