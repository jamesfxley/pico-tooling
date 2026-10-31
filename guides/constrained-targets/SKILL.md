---
name: constrained-targets
description: "Read before making a claim about on-device behaviour, static footprint or allocation, and before cross-compiling, adding a sizing knob or profile macro, chasing a footprint or heap-growth problem, or writing a hardware adapter. Contents: the two storage pools, proving zero allocation after initialisation, the footprint and symbols gates and their pico.toml tables, compile-time sizing profiles, the cross tree, hardware seams, and what makes a device run evidence."
---

# Constrained targets

The rules are [CXX-11](../../house/standard/cxx/11-constrained-targets.md). This
is how to work under them in a family library. It pairs with
[cxx-standard](../../house/guides/cxx-standard/SKILL.md).

## The two pools

Storage divides by lifetime, and the pools are budgeted and gated separately:

- **Static RAM** sums `ALLOC` sections except `LOAD, READONLY` sections
  with equal VMA and LMA, `.heap`, and names starting with `.stack`. It is fixed
  at link time; the
  footprint gate below measures it.
- **Initialisation-time heap** is allocated once before the start call. It is
  permitted and budgeted; what is forbidden is allocation on the steady-state
  paths afterwards.

Conflating them makes both ungateable. State each budget as the expression that
produces it, so a configuration change cannot leave the budget behind:

```text
per-slot storage = max_headers × (name_capacity + value_capacity)
                 + buffered_body + rx_capacity + head_capacity
total            = per-slot × max_connections
```

## Proving zero post-init allocation

Use two independent checks, because each misses what the other catches:

1. **A counter.** Override global `operator new` and `operator delete`, reset
   after the start call, and assert zero at the end of the suite. It catches any
   allocation on a path a test exercised.
2. **A heap watermark on the device.** Sample the heap high-water mark under
  sustained load and assert that it stops growing. It catches the paths tests do
  not reach, and tells bounded growth from a leak: a design that hands ownership
  of a caller-supplied buffer to the library grows to a bound and then flattens,
   which is correct and looks like a leak until the tail is flat.

The bound is arithmetic, not an observation: `max_connections ×
max_buffered_body`. Assert that the measured saturation sits inside it.

The symbols gate adds a static check: the library's own objects must leave
undefined none of the heap symbols (`c-heap` for the allocator, deallocator and
operator new/delete; `c-heap-alloc` for the allocating subset), the soft-float
helpers (`soft-float`), and an image must not define the allocating formatter
routines (`allocating-formatter`).

## Footprint and symbols gates

A library declares each image and object set in `pico.toml`. Its family
reference
supplies the gates and the `firmware` gate group (`docs/usage-guide.md`,
"Embedded gates"):

```toml
[[footprint]]
name = "bench"
elf = "build-firmware/examples/bench/app.elf"
ram_kib = 20           # static RAM budget
flash_kib = 128        # optional
owned_prefix = "src"   # optional, with owned_kib: flash attributed to this tree
owned_kib = 48

[[symbols]]
name = "log probe"
mode = "objects"       # or "image"
path = "build-firmware/tests/firmware/CMakeFiles/probe.dir"
sets = ["c-heap-alloc"]
```

`python3 dev.py gate footprint` and `gate symbols` read the linked image with
`arm-none-eabi-objdump` and `arm-none-eabi-nm` (they must be on `PATH`), fail
over a
stated budget or on a forbidden symbol, and name the image and the figure. They
report **cannot run**, never a pass, when the image or object directory is
missing, when it is older than an owned source (rebuild first), when the tools
are
missing, or when an image built without debug information cannot satisfy an
owned
budget. A footprint that jumped is almost always one buffer: find it with
`arm-none-eabi-nm --size-sort --print-size` on the image.

Flash sums every `LOAD` section. Static RAM sums `ALLOC` sections except
`LOAD, READONLY` sections with equal VMA and LMA, `.heap` and `.stack*`.
The VMA/LMA comparison retains RAM-resident code flagged `READONLY` by the SDK.
Owned flash uses source-attributed code and read-only symbols. Zero loaded
bytes makes an image unavailable.

The `c-heap` set matches whole symbol names: `malloc`, `calloc`, `realloc`,
`free`, their newlib `_malloc_r`, `_calloc_r`, `_realloc_r`, `_free_r` forms,
and mangled operator new/delete entries (including size, alignment and
nothrow forms). `c-heap-alloc` omits deallocation entries. An unrelated name
such as `freeaddrinfo` does not match either set.

Gate each supported configuration, state the gate in the specification, and keep
the measured value in the run record (`EN-03.2`).

## Sizing profiles

Every static size derives from a named compile-time profile. A new knob needs a
`static_assert` binding it to whatever it must agree with (`CXX-11.2`). Two
values
that must match and live in different files will diverge, and the symptom is a
buffer sized for one window while the stack advertises another:

```cpp
static_assert(Profile::rx_capacity >= ADVERTISED_WINDOW,
              "rx buffer must cover a full advertised window or delivered "
              "bytes are dropped");
```

A whole-build profile is declared with `pico_family_declare_profile`; one
variable
has one declaration and one set of values, and a second library declaring it
differently is fatal.

**The propagation trap.** A profile macro a consumer can observe must be a
`PUBLIC` compile definition on the target that owns the profile header
(`CXX-10.3`). A directory-scoped `add_compile_definitions` reaches only the
defining repository's targets, so a consumer compiles the header without it,
disagrees about a structure's size, and gets stack corruption at a point
unrelated
to the cause. Verify rather than assume: configure a consumer with a non-default
profile and search its `compile_commands.json` for the definition, per
translation
unit.

## The cross tree

A cross build has its own build directory, because it is a different toolchain.
It needs `PICO_SDK_PATH` as a CMake variable, and the board is any board the
SDK defines that the library's `PLATFORM` and `CYW43` requirements accept. The
compile database merges the trees so the editor resolves
cross-only
sources;
[cxx-build-and-toolchain](../../house/guides/cxx-build-and-toolchain/SKILL.md)
covers the linting mechanics, which is where most of the friction is, and
`docs/build.md` covers the family's commands.

## Hardware seams

One interface per device, a fake in the testing module, and only the adapter
touches registers (`CXX-11.7`).

The contract, not just the signature, is what the fake must implement. The
classic
failure: a read function that returns an error for an idle or absent bus where
the
caller's drain loop expects success. The loop wedges or raises a spurious fault,
and no host test shows it because the fake was written to the signature.

Where an interrupt publishes a value wider than the platform's atomic word, use
a
seqlock (`CXX-08.4`). A 64-bit timestamp written as two 32-bit stores can be
read
between them, producing a time that never happened.

Where a level-triggered signal can be missed or coalesced, consult the live
level
as well as the latched edge, and count the fallback reads: a read served by the
level fallback has no fresh edge and anchors its data to an earlier timestamp,
which is a real accuracy difference worth observing rather than hiding.

## Claims about on-device behaviour

Never state that something is hardware-validated without a device run
(`EN-06.6`). The pre-merge minimum without hardware is host tests under every
configuration, a cross compile and the footprint gate. That is not validation.

When measuring on a device, bracket a sweep with a health check and discard
degraded data: a radio link, thermal state or power-saving mode can move
throughput several-fold and looks exactly like a regression. Functional results
from a degraded run stay valid; performance numbers do not. Record the
conditions
with every measurement (`EN-06.7`), build type included: a debug build is
materially slower than a release build.

## What makes a run evidence

A capture is not a measurement until it carries its conditions (`EN-06.7`) and
can
be falsified:

- **A conditions table**: date, board, firmware version, toolchain and SDK,
  dependency versions, build type and network. A record inherits nothing from
  the
  record above it.
- **An independent cross-check.** A value inside a plausibility window can still
  be wrong. Compare against an instrument the device does not control, such as
  the
  capturing host's own clock, and not only against the window.
- **A live negative control in the same run**, wherever the measurement is a
  count. A counter that reports zero and a counter that is dead produce the same
  output. Where the control cannot fire, such as a lock that links to an empty
  function, the rig cannot be built honestly and the question needs a different
  instrument.
- **A re-run after the code changes.** A run record backing a requirement is
stale
  the moment the code it exercises moves.

Arm the capture before the device is reset or reflashed, where the tooling
allows
it, because diagnostic output lands at start-up, often before a console attached
afterwards can see it. `device.md` says how the device commands bear on this.
