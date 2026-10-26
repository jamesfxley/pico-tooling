# Architecture

Libraries pin pico-tooling at `infra`; it pins House at `house`. House owns the
runner, generic gates, sanitize tree, structured configuration and workflow.
`family.toml` supplies family gates, the firmware tree, CI matrices/preparation,
context directories and the devcontainer overlay. Repository rows override
family rows with the same identity. Modules import directly from the pin.

`pico_tooling/metadata.py` validates budget and infrastructure inputs.
`render.py` and `sync.py` generate only the pin-bearing CMake bootstrap;
`gate_files.py` compares it. `gate_freshness.py` checks the online release channel.
`report.py` reports infrastructure adoption from committed local repositories.
Product dependency declarations belong in library CMakeLists.txt.

`agents/AGENTS.md` routes library work to House and family guides. The root
AGENTS.md routes work on pico-tooling itself. Tests own synthetic repositories
and configure real SDK fixtures when PICO_FAMILY_TEST_SDK is supplied.

## Devices

`device.py` owns the single device workflow: host allow-list queries, one
per-serial process lock, reset, bootloader wait, load, reconnect and console.
`device_proxy.py` is its JSON/socket client; `device_images.py` selects built
images and checks credentials. No backend selector or direct USB/serial access
is present. The connection file is found by walking up from the working folder.

`host/device-proxy.ps1` is the only transport. It enforces the host allow-list
and workspace load paths, and exposes a raw serial stream. Setup keeps its
executable copy and configuration outside the container's writable workspace;
the installed launcher starts it on the WSL gateway before the container opens.
The container watch ends it after the last matching dev container stops. The
dev container never starts it. Protocol and setup details belong in the [device guide](../guides/device.md).
