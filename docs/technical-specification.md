# Requirements

**AR-1** — `pico.toml` declares the library name, infrastructure repository,
footprint and symbols budgets. Unknown keys, including infra.deferral, and
option-shaped repository locations are unavailable input.

**AR-2** — Sync generates only `cmake/pico_family_bootstrap.cmake` from the
indexed infra revision and repository URL. family-files reports missing, edited
and unindexed bootstraps with the repair command; unreadable inputs are
unavailable. Only the infrastructure repository, with neither pico.toml nor an
infra pin, reports the library gates not applicable. A family reference imports
gates, the firmware tree, CI preparation and devcontainer overlay from
family.toml. family.toml names the CI job image: the published family image,
pinned by registry manifest digest. Every library job container runs as root
(`--user 0`), placed after any container options that the repository's own
require rows declare.

**AR-3** — The freshness gate compares the infra pin with the highest `vX.Y.Z`
release tag, comparing the numbers of the version and not their text. A release
is an annotated tag whose peeled commit is the release; lightweight and other
tags are ignored. A current pin passes. A stale or unreleased pin passes with
"infra pin <pin> is behind the current release <tag>; adopt it". When
`GITHUB_ACTIONS=true`, a column-zero `::warning title=family-freshness::`
annotation with that message precedes the plain message. Unreadable or absent
release tags are unavailable.

**AR-4** — Withdrawn: dependency fetching belongs to the consuming CMake build,
not a separate preparation cache.

**AR-5** — The report reads committed pico.toml and infra pins from explicitly
named local repositories. It refuses remote sources and lists infra pins.

**AR-6** — The CMake entry points select one family context per build. The
context reports the selected root's actual revision and working-tree state, and
labels it an override when either differs from the library's pin, whether the
root is a library's `infra/` checkout or a
`FETCHCONTENT_SOURCE_DIR_PICO_TOOLING` source. The selected release version is
read from its `pyproject.toml`; the generated bootstrap records the requested
version from the pinned metadata. A selected version must be at least the
requested version and share its major, or its minor as well below 1.0. A refusal
names both versions and pins; a compatible context is reused and the request's
own pin is reported. Products keep their own `project(VERSION)`: compiled
products configured under one context install separate packages that
`find_package` accepts or refuses by their own versions. The family requires
CMake 3.26 or later, because `$<BUILD_LOCAL_INTERFACE:>`, which keeps SDK
libraries out of an export, was added in 3.26; `pico_family_bootstrap` refuses
an older CMake and names the reason. The module validates its own arguments and
calls no private House helper. Its public entry points are
`pico_family_bootstrap`, `pico_family_init_sdk`, `pico_family_dependency`,
`pico_family_make_available`, `pico_family_sdk_link_libraries`,
`pico_family_sdk_config_snippet`, `pico_family_require_lwipopts_target`,
`pico_family_propagate_install`, `pico_family_declare_profile`,
`pico_family_declare_probe_option` and `pico_family_add_cross_probe`; the usage
guide gives each signature, behaviour and refusal, and the helper tests exercise
them without an SDK. The generated bootstrap selects the context through the
private `_pico_family_context`, which no library calls. Firmware builds default
only from the `PICO_SDK_PATH` CMake variable; the top level imports and
initializes the SDK once; a dependency takes its parent's SDK and board. The top
level accepts any board the SDK defines, and `PLATFORM` and `CYW43` refuse a
board the library cannot run on.
Dependencies are declared before any is populated, the first declaration wins, a
different later pin is reported, and `FETCHCONTENT_SOURCE_DIR_<NAME>` overrides
are reported with their revision and uncommitted state. A whole-build sizing
profile has one declaration per variable and one set of values; a second library
declaring it differently is fatal, naming both directories. Product fetches
carry no submodules. A portable host configure needs no SDK.

**AR-7** — Scaffolding uses House init with a pinned family at infra and House
at infra/house. house.toml refers to family.toml; AGENTS.md refers to the family
routes file. The scaffold writes pico.toml and the generated bootstrap, with no
adapter directory. Its single commit records the distribution URL without a
local checkout URL in history. The name determines the README title and CMake
project, package and target identifiers (hyphens become underscores), and the
uppercase option prefix. AGENTS.md describes a library. C++ repositories declare
product pins directly in CMake.

**AR-8** — Withdrawn: shared-layer independence is governed by EN-00.8 and
review rather than a family terms scanner.

**AR-9** — The family image is defined by `.devcontainer/Dockerfile`, and the
dev container configuration `.devcontainer/devcontainer.json` is strict JSON
that builds from it. The image is built for `linux/amd64` only. Its base is
pinned by index digest, apt packages by one dated snapshot of the archive, the
PyPI wheels by SHA-256, and the Pico SDK and picotool by the Git commit their
release tag must resolve to; the SDK is 2.3.0 and picotool 2.3.0. The clang
release is the one `house/config/.clang-version` names. The image holds no
shell-script linter, no serial package and no agent-tool file, mount or
extension. The configuration's only `runArgs` entry loads
`.devcontainer/seccomp.json`, Docker Engine 29.8.2's default syscall filter plus
`personality(ADDR_NO_RANDOMIZE)`, so a ThreadSanitizer test can run with
address-space randomisation off. The configuration asks for no host device.
House renders devcontainer.json from its editor base and the family's build/run
overlay. The image identity is its digest, recorded with the checkout commit.

**AR-10** — `python3 -m pico_tooling.qualify` runs inside the built image and
writes `qualification.json` and `qualification.txt`. It records the image
identity it is given, the operating system, every tool's version against the pin
that owns it, the SDK path, release and commit, the apt sources against the
pinned snapshot, every installed package with its version, that `pyserial` is
absent, the image's labels against the expected values, its digest and checkout
commit, and the build inputs' digests. It builds a synthetic family library for
the host with two compilers, a libFuzzer target under ASan and UBSan, a
`pico2_w` firmware program that links to a `.uf2` without fetching picotool,
ThreadSanitizer programs (one clean, one racy) under the syscall filter, and a
one-test GoogleTest project through House's pinned fetch. The GoogleTest check
needs a network: offline it reports `needs-network` without failing, and
`--require-network` makes an offline run a mismatch. With `--control` it runs
only the default-profile control: `setarch -R` must be refused and the engine's
security options must name its built-in profile. It exits 0 when every check
holds, 1 when any differs, naming each, and 2 when evidence could not be
gathered: not inside the image, an unreadable pin, no image identity, or a file
the host command should have written. A mismatch outranks missing evidence.

**AR-11** — `pico.toml` may declare `[[footprint]]` tables (`name`, `elf`,
`ram_kib`; optionally `when`, `flash_kib`, and `owned_prefix` with `owned_kib`
given together). A footprint row's optional `when` table maps valid lowercase
matrix axis names (`[a-z][a-z0-9_]*`) to non-empty strings. It applies only when
every `HOUSE_MATRIX_<UPPERCASE_AXIS>` environment variable equals its value; an
absent or empty table applies always. Unmet rows are reported as information,
not as passed measurements. Malformed conditions are refused by name. The input
also accepts `[[symbols]]` tables (`name`, `mode` of `objects` or `image`,
`path`, `sets`; optionally `expect`, whose only value is `"refused"`). Names are
unique within a table kind, paths stay inside the library, budgets are positive
finite numbers of KiB, and an unknown key, an unknown set, or a set asked in the
mode that cannot see it (`allocating-formatter` is an `image` check;
`soft-float`, `c-heap` and `c-heap-alloc` are `objects` checks) is refused as
unavailable input. Family gates import directly through family.toml; absent
budget tables make the corresponding gate not applicable. The footprint gate
uses `arm-none-eabi-objdump -h`. Flash sums every `LOAD` section.
Static RAM is the sum of every
`ALLOC` section except a `LOAD, READONLY` section with equal VMA and LMA,
`.heap`, and section names starting with `.stack`. An image with no loaded
bytes is unavailable, not a passing zero. It measures owned flash with
`arm-none-eabi-nm` for symbols defined in
files under `owned_prefix` that git tracks or does not ignore; it fails over a
budget. The symbols gate fails for a symbol an image defines or an object leaves
undefined that a set's expression names, counting only objects the compile
database ties to such a file. A `[[symbols]]` table with `expect = "refused"` is
a negative control: it names a fixture the gate must refuse, and passes only
when one of its own sets finds a symbol there; a clean fixture, or one refused
only by another set, fails the gate naming the table. A missing image or object
directory, an image or object older than an owned source, a missing or failing
binutils tool, an object absent from the compile database, a stripped image, and
an image attributing nothing to `owned_prefix` are unavailable, never a pass.

**AR-12** — `python3 -m infra.pico_tooling device` provides `list`, `bootsel`,
`flash` and `console` through the Windows host proxy only. Python checks the
host allow-list, holds one advisory lock per named serial and sequences the
1200-baud reset, up to 30 seconds waiting for BOOTSEL, load and up to 30 seconds
waiting for the application port to reconnect. An already-mounted bootloader
uses `--no-touch` without a reset. There is no default board. `--dry-run` acts
on nothing; commands never build. Image selection and empty Wi-Fi SSID refusal
retain their checks. Several images or ports are listed, never guessed. Missing
or unreachable setup exits 2 with the setup instructions. One lock per board
spans flashing and any following console. A held lock fails naming its holder.
No direct serial access or platform detection is provided.

**AR-13** — The standard-library console requests 115200 baud from the proxy and
reads its raw byte stream, reconnecting using the same serial after disconnects.
Interactive mode forwards input until interruption; agent mode requires `--until
RE` and finite positive `--timeout S`, logs bytes with `--log FILE`, and returns
0 on a match, 1 on timeout and 2 when it cannot run. Matching spans chunks with
incremental UTF-8 decoding and a 65,536-character tail. Reconnect waiting counts
toward the deadline. Other device statuses are 0 success, 1 operation failure, 2
refusal/unavailable inputs, 3 ambiguity, 130 interrupt and 143 termination.

**AR-14** — The repository declares `cxx` and builds, formats, lints and tests
padcheck's line protocol on the host: `tools/padcheck/line_protocol.hpp`, its
GoogleTest cases in `tools/testing`, and six compile-fail probes, each of which
discards one `[[nodiscard]]` result and passes only when the build fails with
the exact diagnostic of the compiler in use and the call's own text. The C++
builds with the pinned strict target and no suppression, and its package is
built and tested, never installed. GoogleTest uses an existing
`GTest::gtest_main` target or House's pinned fetch; a network-free build
provides that target first.

**AR-15** — `host/setup-dev-distro.ps1` provisions a new amd64 WSL distro
(default pico-dev) from the pinned Canonical Ubuntu WSL image, verifying its
SHA-256 before installation. It refuses an existing name/directory or non-NAT
networkingMode before installation. It runs unelevated, copies
`host/in-dev-distro.sh` through UNC, provisions the pinned Docker Engine, user
and wsl.conf as root, then restarts the distro and waits for Docker. It retains
a partial distro on failure and has no unregister mode. The shell verify prints
failed systemd units, wsl.conf and the binfmt listing; it does not attempt
Windows-process launch.

`host/device-proxy.ps1` runs in Windows PowerShell 5.1 without installing
dependencies. It listens only on its `-ListenAddress` unicast IPv4 literal
(default `127.0.0.1` for CI), and requires a per-workspace token. The connection
file carries host, port and token; the CLI validates the host and uses that
endpoint exclusively. It accepts newline-delimited JSON `list`, `allowed`,
`open` and `load`; successful `open` switches to a raw bidirectional stream. It
independently enforces its host-only `devices.toml` allow-list on open and load.
A load names an existing file inside the token's workspace, including a
`\\wsl.localhost` UNC workspace; rooted paths, traversal and reparse-point paths
are refused. Copy errors fail. Tokens are case-sensitive.
`host/setup-device-proxy.ps1` installs a private host copy and launcher, prints
the allow-list location without writing a serial, and creates no logon start.
Setup creates the inbound TCP firewall rule named pico-device-proxy-wsl for the
configured port, RemoteAddress LocalSubnet4, Profile Any and unrestricted
interfaces. A matching enabled rule needs no elevation; a mismatching rule of
that name is replaced and named in the output, with creation/replacement
performed in one elevated child. -NoFirewall skips the operation for CI. A
refused or timed-out proxy connection exits 2 with one line naming host:port and
the installed start-device-proxy.ps1 launcher to run on Windows before device
commands; no token or retry. The launcher checks the pico-dev distro, Docker
service, gateway and rule, then starts the installed proxy on Windows' WSL NAT
address. With -Distro the proxy checks every three seconds for any configured
workspace's running dev container. It waits at most 300 seconds for the first,
then exits normally when none is running, removing connection files and closing
sessions. An injected container query supports no-WSL CI tests. Without -Distro
it runs until stopped. `-Remove` stops/removes that installation and connection
files and the firewall rule while preserving configuration and allow-list. No
devcontainer platform logic starts the proxy. Host `-List` uses the request
handler's enumeration once, prints board details and exits without listening,
serial access or copying. Setup refuses unexpected config-directory entries
before any mutation. For a bootloader drive, it starts at the disk drive's
PNPDeviceID and follows DEVPKEY_Device_Parent through at most four parent links,
stopping at the first identifier accepted by Get-UsbSerial. No disk-instance
suffix is parsed. An unresolved drive has an empty serial and is never listed as
allowed or matched by a load.

## Traceability matrix

| Requirement | Verification |
|---|---|
| AR-1 | [Tests and criteria](#ar-1-verification) |
| AR-2 | [Tests and criteria](#ar-2-verification) |
| AR-3 | [Tests and criteria](#ar-3-verification) |
| AR-5 | [Tests and criteria](#ar-5-verification) |
| AR-6 | [Tests and criteria](#ar-6-verification) |
| AR-7 | [Tests and criteria](#ar-7-verification) |
| AR-9 | [Tests and criteria](#ar-9-verification) |
| AR-10 | [Tests and criteria](#ar-10-verification) |
| AR-11 | [Tests and criteria](#ar-11-verification) |
| AR-12 | [Tests and criteria](#ar-12-verification) |
| AR-13 | [Tests and criteria](#ar-13-verification) |
| AR-14 | [Tests and criteria](#ar-14-verification) |
| AR-15 | [Tests and criteria](#ar-15-verification) |

### AR-1 verification

- `test_gates.py`:
  `test_unreadable_or_invalid_input_cannot_run`;
  invalid keys, malformed metadata and unreadable input return unavailable.
- `test_injection.py`:
  `test_an_option_shaped_repository_is_refused_before_git_runs`;
  option-shaped repository values are refused before Git.
- `test_freshness.py`:
  `test_infra_deferral_is_refused_by_name`;
  retired deferral keys are refused by name.

### AR-2 verification

- `test_gates.py`:
  `test_missing_edited_and_unindexed_bootstrap`;
  family-files rejects missing/edited/unindexed bootstrap and accepts sync
  repair.
- `test_gates.py`:
  `test_a_library_without_its_input_cannot_run_but_the_infrastructure_skips`;
  libraries cannot hide missing input; infrastructure has an explicit skip.
- `test_family.py`:
  `test_real_family_layers_work_without_adapters`;
  the actual family supplies gates, trees, CI preparation and overlays.
- `test_family.py`:
  `test_library_jobs_inherit_the_pinned_family_image`;
  every library job container uses the digest-pinned family image.
- `test_family.py`:
  `test_family_container_user_survives_repository_job_overrides`;
  the root job user survives repository require rows and follows their options.

### AR-3 verification

- `test_freshness.py`:
  `test_current_annotated_release_passes`;
  the annotated current release passes.
- `test_freshness.py`:
  `test_stale_pin_warns_and_prereleases_are_ignored`;
  stale release adoption is informational.
- `test_freshness.py`:
  `test_versions_compare_numerically_not_lexically`;
  numeric version order selects the release.
- `test_freshness.py`:
  `test_a_lightweight_tag_is_not_a_release`;
  lightweight tags do not establish releases.
- `test_freshness.py`:
  `test_stale_warning_is_printed_at_column_zero`;
  the workflow warning starts at column zero.

### AR-5 verification

- `test_report.py`:
  `test_report_keeps_infra_pin_and_refuses_remote_inputs`;
  the report reads committed local pins and refuses remote inputs.

### AR-6 verification

- `test_cmake.py`:
  `test_both_orders_share_one_context_and_one_dependency`;
  both declaration orders reuse one context/dependency.
- `test_cmake.py`:
  `test_overrides_are_reported_and_siblings_ignored`;
  overrides report their state and sibling checkouts do not substitute pins.
- `test_cmake.py`:
  `test_release_compatibility_boundaries`;
  versions obey major/minor compatibility.
- `test_cmake.py`:
  `test_firmware_imports_and_initializes_the_sdk_once`;
  SDK import and initialization occur once.
- `test_cmake.py`:
  `test_the_family_module_calls_no_private_house_helper`;
  the helper uses no private House call.
- `test_sdk_config.py`:
  `test_real_sdk_package_restores_the_installed_interface`;
  installed consumers restore recorded SDK links.

### AR-7 verification

- `test_scaffold.py`:
  `test_scaffold_passes_ci_with_the_family_route`;
  the real scaffold has the family route and passes declared CI checks.
- `test_scaffold.py`:
  `test_a_hardcoded_platform_template_refuses_the_scaffold`;
  a template hardcoding a platform path is refused.
- `test_family.py`:
  `test_real_family_layers_work_without_adapters`;
  the scaffold imports the pinned family without adapters.

### AR-9 verification

- `test_image.py`:
`test_the_devcontainer_configuration_is_strict_json_that_builds_the_dockerfile`;
  the definition is strict JSON with the correct Dockerfile build route.
- `test_image.py`:
  `test_the_base_is_pinned_by_digest_and_the_architecture_is_not_chosen_by_it`;
  base and architecture pins have the declared form.
- `test_image.py`:
  `test_the_sdk_and_picotool_are_cloned_by_tag_and_checked_against_a_commit`;
  source tag/commit checks are present.
- `test_image.py`:
  `test_every_wheel_is_installed_by_hash`;
  all wheel inputs have hashes.
- `test_image.py`:
  `test_the_only_difference_from_upstream_is_the_no_randomize_rule`;
  the carried seccomp filter has only the approved difference.

### AR-10 verification

- `test_qualify.py`:
  `test_a_conforming_image_exits_zero_and_records_its_identity`;
  a synthetic conforming system produces an identity-bearing success.
- `test_qualify.py`:
  `test_a_tool_off_its_pin_exits_one_and_names_itself`;
  a pin mismatch is a named failure.
- `test_qualify.py`:
  `test_a_mismatch_outranks_missing_evidence`;
  faults outrank missing evidence.

### AR-11 verification

- `test_embedded_gates.py`:
  `test_sections_follow_placement_and_flags_not_a_name_list`,
  `test_generic_sections_have_nonzero_flash_and_ram`,
  `test_all_noload_sections_cannot_run`;
  flags and VMA/LMA include initialized data, vectors and uninitialized
  allocations at Pico and generic addresses; zero loaded bytes is unavailable.
- `test_embedded_gates.py`:
  `test_an_unavailable_image_hides_no_other_failure`;
  an over-budget image remains FAIL beside an unavailable row.
- `test_embedded_gates.py`:
  `test_symbols_fault_outranks_an_unavailable_row_and_keeps_reports`;
  symbol findings and reports remain beside unavailable rows.
- `test_embedded_gates.py`:
  `test_reentrant_newlib_heap_entries_are_matched`;
  newlib allocation/deallocation entries match the intended set.
- `test_embedded_gates.py`:
  `test_heap_sets_do_not_match_unrelated_prefixes`;
  unrelated prefixes such as freeaddrinfo are not heap matches.

### AR-12 verification

- `test_device_proxy.py`:
  `test_flash_resets_waits_loads_and_reconnects`;
  the fake host records the required reset/load/reconnect sequence.
- `test_device_proxy.py`:
  `test_dry_run_does_not_reset_or_load`;
  dry-run makes no device request.
- `test_device_proxy.py`:
  `test_lock_contention_refuses_before_reset_and_releases_afterwards`;
  locks refuse contention before reset.
- `test_device_images.py`:
  `test_several_images_are_listed_not_guessed`;
  ambiguous images are listed rather than guessed.

### AR-13 verification

- `test_device_proxy.py`:
  `test_console_matches_utf8_split_between_socket_reads`;
  UTF-8 matching spans transport chunks.
- `test_device_proxy.py`:
  `test_console_timeout_is_one_and_log_keeps_partial_output`;
  timeout returns 1 and preserves the raw partial capture.
- `test_device_proxy.py`:
  `test_interactive_console_forwards_input_and_reconnects`;
  interactive input forwarding and reconnect are exercised on a fake stream.
- `test_device_proxy.py`:
  `test_named_port_waits_after_disconnect_until_agent_deadline`;
  reconnect waiting obeys the agent deadline.

### AR-14 verification

`tools/testing/line_protocol_test.cpp` supplies the LineProtocol tests:
`FieldsAreTakenInOrder`, `APrefixOutOfRangeOrSignedPinIsInvalid`,
`AnOverlongLineIsDroppedAndTheNextIsRead`, and
`TheLastCharacterThatFitsAndTheFirstThatDoesNot` check parsing and bounds.
The six `pico_tooling_refuses_discarded_*` CTest cases check each nodiscard
refusal against its compiler diagnostic and the call's own text.

### AR-15 verification

- `test_image.py`:
  `test_the_distro_setup_inputs_are_pinned_and_the_shell_is_carried`;
  the script image inputs, Docker version and copied shell are pinned.
- `test_image.py`:
  `test_only_the_declared_host_proxy_scripts_are_powershell`;
  the host-script inventory is exact.
- `test_device_proxy.py`:
  `test_connection_file_supplies_the_ipv4_address`;
  the client uses the connection file endpoint.
- `test_device_proxy.py`:
  `test_proxy_connect_failure_names_endpoint_and_launcher_once`;
  refusal/timeout names the endpoint and launcher without retry.

AR-7 scaffold controls: `test_scaffold_history_records_only_the_distribution_url`
checks every committed .gitmodules using a distinct non-local URL;
`test_scaffold_name_defines_the_cmake_package_and_targets` checks the named
project, prefix, package, targets and title;
`test_scaffold_instructions_describe_a_library` checks the repository role.
