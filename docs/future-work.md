# Future work

Work deliberately not done, one entry per deferral, in the form `EN-03.7`
defines.

## FW-1 — RISC-V cores

### What is absent

The family builds only for the Arm cores of the RP2040 and the RP2350. The
RP2350's Hazard3 RISC-V cores (`PICO_PLATFORM` `rp2350-riscv`) have no
toolchain in the image and no CI leg.

### Why it is not built

No consumer has asked, and the cost is a RISC-V toolchain in the image, a wider
CI matrix and a review of the Arm-specific assumptions: fences, assertions and
footprint budgets.

### What would have to be true to build it

A consumer that needs the RISC-V cores. Then the image gains the RISC-V
toolchain, the CI matrix gains a leg, and each library's Arm-specific code is
reviewed.

### Version cost

Not breaking under `EN-06.1`: it adds a platform.

### Affected repositories

pico-tooling. The review identifies which libraries need a change; pico-util's
`check_publishable` branches on `__ARM_ARCH_6M__`. None is established yet.

## FW-2 — Linux and macOS device backends

### What is absent

Device commands run only through the Windows host proxy. No Linux or macOS
local-device backend exists, and no backend selector.

### Why it is not built

No developer on Linux or macOS uses the family; these backends are out of scope
until one does.

### What would have to be true to build it

A developer who works on Linux or macOS and needs device commands there. On
macOS the TCP path through Docker Desktop's proxy is unconfirmed.

### Version cost

Not breaking under `EN-06.1`: the Windows proxy route is unchanged.

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

A Microsoft, Raspberry Pi, Docker or Dev Containers document that states each
behaviour, or a design that no longer relies on it.

### Version cost

Not breaking under `EN-06.1`: it changes documentation, or the host proxy
without changing the device commands.

### Affected repositories

pico-tooling.
