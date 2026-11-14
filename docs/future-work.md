# Future work

Deferrals follow [EN-03.7](../house/standard/engineering/03-documentation.md).

## FW-1 — RISC-V cores

### What is absent

The family builds only for the Arm cores of the RP2040 and the RP2350. The
RP2350's Hazard3 RISC-V cores (`PICO_PLATFORM` `rp2350-riscv`) have no
toolchain in the image and no CI leg.

### Why it is not built

No consumer has asked, and the cost is a RISC-V toolchain in the image, a
wider CI matrix and a review of the Arm-specific assumptions: fences,
assertions and footprint budgets.

### What would have to be true to build it

A consumer needs the RISC-V cores. Supporting them requires a toolchain in the
image, a CI leg and a review of each library's Arm-specific code.

### Version cost

Adding a platform is non-breaking under
[EN-06.1](../house/standard/engineering/06-release-and-versioning.md).

### Affected repositories

pico-tooling. The review identifies which libraries need a change; pico-util's
`check_publishable` branches on `__ARM_ARCH_6M__`. None is established yet.

## FW-2 — Linux and macOS device backends

### What is absent

Device commands run only through the Windows host proxy. No Linux or macOS
local-device backend exists, and no backend selector.

### Why it is not built

No developer on Linux or macOS uses the family; these backends are out of
scope until one does.

### What would have to be true to build it

A developer needs device commands on Linux or macOS. On macOS, the TCP path
through Docker Desktop's proxy is unconfirmed.

### Version cost

The Windows proxy route stays unchanged, so the addition is non-breaking under
[EN-06.1](../house/standard/engineering/06-release-and-versioning.md).

### Affected repositories

pico-tooling.

## FW-3 — Documented device behaviour

### What is absent

Official confirmation of the host and hardware behaviours the device commands
rely on, listed in the device guide's UNCONFIRMED section: the parent walk's
depth, the USB serial in the instance identifier and its equality between
bootloader and application, which application runs after a UF2 reboot, DTR and
RTS forwarding, the 1200-baud open during a reset, the launcher's adapter name
and `wsl.exe` options, the `LocalSubnet4` scope, and the dev container check.

### Why it is not built

The Microsoft, Raspberry Pi and UF2 documents consulted do not state these
behaviours, the Docker and Dev Containers documents have not been checked, and
an observation on one host does not establish them.

### What would have to be true to build it

Confirmation requires a Microsoft, Raspberry Pi, Docker or Dev Containers
document for each behaviour, or a design that no longer relies on it.

### Version cost

Documentation or host proxy changes that preserve the device commands are
non-breaking under
[EN-06.1](../house/standard/engineering/06-release-and-versioning.md).

### Affected repositories

pico-tooling.
