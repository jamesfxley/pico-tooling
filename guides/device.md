# Device operations

Run `python3 -m infra.pico_tooling device` from a family library in the dev
container. The Windows host proxy is the only backend. Python owns the host
allow-list check, board lock, reset, wait, flash and console. The proxy owns
its host allow-list and accepts only workspace-relative loads. Commands never
build or select an unnamed board.

## Supported platforms

| Developer setup | Container build/test/lint | Device commands | TCP path seen by the board |
|---|---|---|---|
| Windows, Docker Engine in WSL NAT mode | yes | Windows proxy | kernel NAT |
| Windows, Docker Desktop | yes | unsupported | Desktop connection proxy |
| macOS, Docker Desktop | yes | no backend | UNCONFIRMED: Desktop proxy |
| Linux, Docker Engine | yes | no backend | kernel bridge NAT |
| CI Linux runner | yes | not used | not run |

The image, devcontainer configuration and seccomp settings are engine-neutral.
Device commands require the documented Windows/WSL route. No Linux or macOS
local-device backend is supplied (FW-2).

## One-time setup

Install and enable WSL first (WSL 2.4.10 or newer). From an unelevated
Windows PowerShell 5.1 window, run the family's distro setup:

```powershell
& <family>\host\setup-dev-distro.ps1
```

It creates `pico-dev` under the current user's LOCALAPPDATA directory from
Canonical's pinned Ubuntu 26.04.1 amd64 WSL image, verifies its SHA-256 before
installation, and installs Docker Engine 29.8.2. It needs network access to
Canonical and the Ubuntu/Docker apt repositories. `-Image <path>` uses an
already downloaded copy with the same checksum; the original file is kept.
`-Distro` selects another name and `-User` overrides the Linux name derived
from the Windows user. Existing distros/directories, non-amd64 hosts and a
non-NAT networkingMode in .wslconfig are refused before installation.

The setup copies `host/in-dev-distro.sh` through the distro's UNC share,
runs it as root, then restarts that distro and waits for Docker. The script
keeps systemd on, Windows interop/PATH injection off, and drive automounting
and fstab processing off. `verify` prints failed systemd units and the binfmt
listing. The distro's wsl.conf disables interop; Microsoft documents
[that setting as controlling Windows-process launch support](https://learn.microsoft.com/en-us/windows/wsl/wsl-config#interop-settings).

Setup retains a partially installed distro on failure. It does not remove
or overwrite a distro. Deliberate removal permanently deletes its whole
filesystem, including every workspace, image and setting. See [distro removal](../docs/usage-guide.md#distro-removal)
and preserve anything needed before doing so.

Use an ordinary Windows VS Code window. Enable Dev Containers' `executeInWSL`
and set `executeInWSLDistro` to `pico-dev`. Open the workspace by its Windows
UNC path, for example `\\wsl.localhost\pico-dev\home\<user>\<folder>`, then
reopen in its container. The WSL extension's installer requires the Windows
drive mount and is not the entry point for this configuration. Decline
VS Code's offer to reopen the folder in WSL, and do not use a recent entry or
Remote Explorer item labelled WSL; those use the WSL extension.

In Windows PowerShell 5.1, run the pinned family's setup script with exactly
the same workspace path:

```powershell
& <family>\host\setup-device-proxy.ps1 -Workspace '\\wsl.localhost\pico-dev\home\<user>\<folder>'
```

Setup copies the proxy and `start-device-proxy.ps1` launcher into the current
user's pico configuration directory and sets its access rules to allow only
that user; administrators' ownership and backup privileges still apply. It
reads/updates access rules only, leaving ownership and audit settings untouched.
A protected folder with exactly one inheritable user FullControl allow rule
needs no access-rule update. Setup refuses unexpected entries before mutation;
the five expected files are device-proxy.ps1, start-device-proxy.ps1,
device-proxy.json, device-proxy.log and devices.toml. Subdirectories are refused.

Only the firewall operation requests elevation. Setup creates the inbound
TCP rule `pico-device-proxy-wsl`, on the configured port (default 47600),
with `RemoteAddress LocalSubnet4`, `Profile Any` and no interface restriction.
A matching enabled rule is kept without elevation. Setup replaces a rule of
that name with different settings in one elevated child and names the
replacement in its output. The scope uses Microsoft's local-IPv4-subnet
keyword rather than an adapter identity, so it has no adapter reference to
refresh after a restart. Microsoft defines the keyword as all local IPv4
addresses, and the rule admits them to the port; the proxy
still listens only on Windows' WSL gateway address and requires the workspace
token. See [Microsoft's rule parameters](https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule).
`-NoFirewall` skips this operation for CI or a machine without the distro.
Updating stops an old installed proxy and removes its connection files;
an old pico-device-proxy.lnk is removed and named in the output.
Setup starts no proxy and creates no logon entry.

Setup prints the host allow-list location. Enumerate serials with the installed
copy in Windows PowerShell:

```powershell
& (Join-Path $env:APPDATA 'pico/device-proxy.ps1') -List
```

`-List` starts no listener, opens no serial port and copies nothing. Edit the
host's devices.toml by hand; the container cannot read or write it:

```toml
[[device]]
serial = "BOARD-SERIAL"
label = "bench board"
```

The host reader accepts only these fields, double-quoted unescaped strings
and optional comments. A malformed allow-list authorizes nothing.

## Start before opening the container

Run the installed launcher from Windows PowerShell:

```powershell
& (Join-Path $env:APPDATA 'pico/start-device-proxy.ps1') -Distro pico-dev
```

It reads the distro's default gateway, verifies that it is Windows' IPv4
address on the WSL adapter, checks Docker and the firewall rule, then starts
the installed proxy copy hidden on that address. A missing distro, unavailable
Docker service, missing/mismatched rule or occupied port stops with a message.
It waits for an authenticated answer without enumerating/opening a board,
then prints that the container can now be opened.

The proxy queries the distro's Docker Engine every three seconds for running
dev containers whose devcontainer.local_folder label matches a configured workspace.
It waits at most five minutes for the first matching running dev container,
then exits normally once none is running, removing its connection files and
closing active sessions. If the initial wait expires, run the launcher again.
With no `-Distro`, the proxy runs until stopped; that loopback mode serves the
no-device Windows CI test. The container never starts the Windows proxy.

Each workspace's private `.pico-device-proxy.json` carries `host`, `port` and
`token`. Host is a non-wildcard unicast IPv4 literal; the CLI connects only to
that address. Keep the file untracked and private. A token grants the served
workspace's files and the boards in the host allow-list. Missing/invalid setup
or an unreachable proxy exits 2 with setup/launcher instructions.

`setup-device-proxy.ps1 -Remove` stops the installed copy, removes its launcher,
connection files and any old shortcut, and removes the firewall rule through
one elevated child. It preserves device-proxy.json and devices.toml. With
`-NoFirewall`, removal leaves the firewall untouched.

## List and authorize

```text
python3 -m infra.pico_tooling device list [--json]
```

List reads enumeration data without opening a serial port or loading an image.
It shows serial, ports, bootloader drive and host allow-list membership. Check
the physical board and intended image before authorizing an action; the proxy
does not infer a board model from a port. Acting commands require `--serial S`;
there is no default board. Authorization is checked in Python through `allowed`
and again by the host before `open` or `load`.

A bootloader drive is tied to its board through the Windows device tree. The
proxy starts at the disk drive's PNPDeviceID and follows DEVPKEY_Device_Parent
at most four times, accepting the first identifier with Raspberry Pi's USB
vendor ID 0x2E8A; an RP2350 whose OTP overrides the vendor ID is not found. It
uses the last segment of that identifier, not a parsed disk-instance suffix.
Windows sets that segment to the device's USB serial when the device reports
one and to location information otherwise. If no
accepted ancestor is found, the drive's serial is empty: it is never listed
as allowed or matched by a load. Before a first flash, check one board in
normal mode,
then unplug it and replug it with BOOTSEL held, running host `-List` in each
mode. A bootloader drive must report the same non-empty serial. A mismatch or
missing/ambiguous enumeration is a finding: do not assume `load` can locate the
board and do not flash. No serial translation or fallback is provided.

## Build and flash

Build with the repository's firmware build instructions first. A `.uf2` path
must resolve inside the served workspace. A name selects a directory under
`build-firmware/` (else `build/`), or `--build-dir D`. Several matches exit 3
with their paths. An empty `PICO_*_WIFI_SSID` in the image's CMake cache is
refused with the reconfigure command; an absent cache produces a warning.

```text
python3 -m infra.pico_tooling device flash --serial S [--port P] [--build-dir D] [--dry-run] [--no-touch] [--console --until RE --timeout S --log FILE] [image|path.uf2]
python3 -m infra.pico_tooling device bootsel --serial S [--port P]
```

`--dry-run` prints the plan without a reset or copy; it still needs the proxy
and authorization. A real flash holds one advisory lock per serial throughout
reset, load, reconnect and any requested console session. A second command exits
1 naming the holder. Locks use your private runtime directory, with a private
per-user temporary directory as fallback. Host serial opens also fail if busy.

A running board is opened at 1200 baud for the reset. SDK 2.3.0 defines this in
`src/rp2_common/pico_usb_reset/include/pico/usb_reset_config.h:10–27` and handles
it in `pico_usb_reset/usb_reset.c:147–148`. It needs firmware using the SDK's USB
stdio with baud reset enabled; firmware driving TinyUSB directly does not enable
it by default. The firmware can reset while the 1200-baud open is still in
progress, so the open can fail even though the reset happened (FW-3).
An open refused with `failed` or `absent`, or a connection closed before the
open reply, still leads to the BOOTSEL wait. If the named bootloader appears,
the CLI reports that the port vanished during the reset as expected and
continues. Otherwise it exits 2 with the open error and BOOTSEL instructions.
`token`, `denied`, `path`, `request` and `busy` refusals stop immediately with
their normal statuses. **A blank board's first flash needs the BOOTSEL button:** hold
it while connecting the board, then use `--no-touch`. That option refuses a
board not already in BOOTSEL. Python waits up to 30 seconds for the named
bootloader, requests the load, then waits up to 30 seconds for that serial's
application port. A missing reset or reconnect is a failure, never proof of
successful flashing. Firmware without USB serial cannot satisfy reconnect.

The host refuses ambiguous drives, paths outside the token's workspace, missing
files and reparse-point paths (including junctions and symbolic links). A copy
error fails even when the drive disappears. UF2 copying does not read the image
back; a successful command is not a firmware correctness or byte-verification
claim.

## Watch the console

```text
python3 -m infra.pico_tooling device console --serial S [--port P] [--until RE --timeout S] [--log FILE]
```

The console opens at 115200 baud with DTR and RTS asserted. Interactive mode
forwards standard input and copies output until Ctrl+C or termination. On a
lost connection it waits for the same serial and reconnects. `--port` chooses
among that board's ports; ambiguity exits 3 rather than guessing.

Agent mode requires both `--until RE` and a finite positive `--timeout S`.
It does not forward input. It matches decoded UTF-8 across received chunks in
the most recent 65,536 characters, returns 0 on a match and 1 on timeout,
including time waiting for a reconnect. `--log FILE` appends exact received
bytes in either mode. Invalid options or an unusable log exit 2. Output before
the console attaches is not captured; use `flash --console` and firmware that
waits for USB connection or reports on request when startup output matters.

## Device tests

```text
python3 -m infra.pico_tooling device test --serial S --timeout S [--port P] [--build-dir D] [--no-touch] [--dry-run] [--log FILE] [image|path.uf2]
```

A device test runs the cases a host test cannot establish, on the board, and
judges them. The command flashes exactly as `flash` does (lock, reset, BOOTSEL
wait, load, reconnect, image selection), holds the console in agent mode under
the same lock, and stops at the first complete stream: a `TAP version 14` line
followed by a plan or a `Bail out!` line. `--timeout` is required. Naming
`tests/device` selects `build-firmware/tests/device/*.uf2`. A plan with no
version line before it joins a stream midway and is skipped; the command waits
for the next re-emission. Board output goes to standard output, `--log` appends
its exact bytes, and lines that are not TAP pass through.

The verdict goes to standard error: the image's identity comment, one line per
requirement ID (`==> HR-4: 2 passed, 0 failed`), each failed case with its
comment lines, and a last line, `==> device test: PASS` or `==> device test:
FAIL: <reason>`. Status 0 means every test point is `ok`, numbered 1..N once
each, with N the plan. Status 1 is a `not ok`, a `Bail out!`, a count or
numbering mismatch, a plan of 1..0, an identity whose commit is `-dirty`,
`unknown` or absent, no complete stream before the deadline, or a failed flash
step; 2, 3, 130 and 143 are as for the console. `--dry-run`
prints the plan and acts on nothing.

The image emits this subset of TAP 14, which the command and `tap.hpp` share:

```text
TAP version 14
# image pico_bno085_device_tests 0.1.0 board=pico2_w commit=<sha>[-dirty]
ok 1 - HR-4 i2c-refuses-unreachable-pins
not ok 2 - HR-4 spi-refuses-unreachable-pins
  # miso=17 init=ok, expected INVALID_ARGUMENT
1..2
```

- One test point per case: `ok|not ok <n> - <requirement ID> <case-name>`. The
  first word of the description is the requirement ID. A case that cites two
  IDs is two cases.
- The plan comes last. A stream without one, such as an image that crashed or
  hung, fails.
- `Bail out! <reason>` stops the run and fails it.
- Comment lines carry a failed case's detail and the image identity. Skips,
  TODO directives and YAML blocks are outside the subset and fail the run: a
  device test holds or fails.
- CRLF and CR read as LF, since the SDK's stdio translates LF to CRLF.

The firmware side is `device_test/include/pico_family/device_test/`.
`tap.hpp` records cases in fixed storage and emits the stream, with no SDK and
no allocation. `run.hpp` waits up to 30 seconds for the USB console, then emits
the stream and re-emits it every 2 seconds, so a console that attaches late
still receives a whole one. That DTR reaches the board is UNCONFIRMED, below;
the re-emission makes the run independent of it. A library adds the image with
`pico_family_add_device_test` (see the usage guide and `docs/new-library.md`),
which defines the identity: name, version, board and the commit of the library's
source, with `-dirty` when its working tree has changes. Without git the commit
is `unknown`. The identity is read when the build is configured: `dev.py build`
configures on every call, but a build run straight through CMake after a commit
or an edit keeps the identity of the last configure.

A run is evidence for a pull request only when the image names the commit it
was built from, so a `-dirty`, `unknown` or missing commit fails the run:
commit locally, then build and run.

Record a run in the pull request's Verification section: the board serial, the
image's commit from the identity line, the command, and the verdict output. A
device test measures nothing; a measurement is a benchmark, and benchmarks are
a separate tier.

## Protocol

One newline-delimited UTF-8 JSON request per TCP connection, always with
`token`. `Read-Line` accepts at most 65,535 bytes before the LF delimiter;
it refuses another non-LF byte once that count is reached. LF is not counted.
Replies have `ok: true` or `ok: false`, `code` and
`error`. After a successful `open` reply, all following bytes are raw serial
traffic in both directions until closure.

| cmd | Inputs besides token | Successful reply |
|---|---|---|
| list | none | boards: serial, product, ports, bootloader, drive, listed |
| allowed | serial | allowed boolean |
| open | serial, port, baud | ok, then raw stream |
| load | serial, path (workspace-relative) | ok after copy |

`token`, `denied`, `path`, `request` and `absent` refuse before an operation;
`busy` and `failed` report failure. The host checks its allow-list before any
open or load and binds a load to the token's workspace.

## Exit statuses

| Status | Meaning |
|---|---|
| 0 | Completed, console pattern matched or device test passed |
| 1 | Reset/reconnect or console timeout, copy failure, busy port or held lock, failed device test |
| 2 | Cannot run: setup unavailable, refused token/serial/path, absent board, invalid options, missing image or unusable log |
| 3 | Several images or ports without a selection |
| 130 / 143 | Interrupted / terminated |

## UNCONFIRMED

Official documentation does not establish these behaviours (FW-3).

| Behaviour | What the documentation leaves open |
|---|---|
| The parent walk reaches the board's USB device within four steps | Microsoft USB/PnP documentation describes parent links, not a mass-storage disk's depth below the device |
| Windows copies the USB serial into the instance identifier unchanged, and the bootloader and the application report the same serial | Microsoft USB documentation does not state the copy; the RP2040 datasheet does not say what its boot ROM serial is derived from; the RP2350 datasheet and the SDK give each source, not that the strings are equal |
| The application that enumerates after the reboot is the image just copied | The RP2040 and RP2350 datasheets and the UF2 specification document the reboot, not which application then enumerates |
| DTR and RTS reach the board when the port opens | Microsoft documents the SerialPort properties, not how the USB serial driver forwards them |
| The 1200-baud open can fail while the reset happens | Microsoft serial documentation does not describe a device leaving during an open |
| The launcher's adapter name and the `wsl.exe` options it passes | Microsoft WSL documentation names neither |
| `LocalSubnet4` covers the WSL NAT subnet | Microsoft defines the keyword as all local IPv4 addresses without naming that subnet |
| The proxy's dev container check | Docker's label filter and the Dev Containers `devcontainer.local_folder` label are not checked against their documentation |

The Python fake-proxy tests exercise protocol and sequencing only. They do not
establish these host or hardware properties. No Linux kernel USB routing is used.
