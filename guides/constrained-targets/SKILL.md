---
name: constrained-targets
description: "Read before making a claim about on-device behaviour, static footprint or allocation, and before cross-compiling, adding a sizing knob or profile macro, chasing a footprint or heap-growth problem, or writing a hardware adapter. Contents: the two storage pools, proving zero allocation after initialisation, the footprint and symbols gates and their pico.toml tables, compile-time sizing profiles, the cross tree, hardware seams, and what makes a device run evidence."
---

# Constrained targets

This guide applies
[CXX-11](../../house/standard/cxx/11-constrained-targets.md) to family
libraries alongside [cxx-standard](../../house/guides/cxx-standard/SKILL.md).
The [family README](../../README.md) defines the shared terms.

## The two pools

Storage divides by lifetime, and the pools are budgeted and gated separately:

- Static RAM is fixed at link time. The
  [footprint gate](../../docs/usage-guide.md#embedded-gates) measures it.
- Initialisation-time heap is allocated once before the start call. It is
  permitted and budgeted; what is forbidden is allocation on the steady-state
  paths afterwards.

State each budget as an expression so it stays valid when the configuration
changes:

```text
per-slot storage = max_headers × (name_capacity + value_capacity)
                 + buffered_body + rx_capacity + head_capacity
total            = per-slot × max_connections
```

## Proving zero post-init allocation

Use two independent checks, because each misses what the other catches:

1. Override global `operator new` and `operator delete`, reset
   after the start call, and assert zero at the end of the suite. It catches any
   allocation on a path a test exercised.
2. Sample the device heap high-water mark under sustained load and assert
   that it stops growing. It catches paths tests do not reach. A library
   taking ownership of caller-supplied buffers can grow to a bound before
   stabilising; that growth is not a leak.

The bound is calculated as `max_connections × max_buffered_body`. Assert that
measured saturation stays within it.

The symbols gate adds a static check. The library's own objects must leave no
heap symbols undefined (`c-heap` covers allocation and deallocation;
`c-heap-alloc` covers allocation only), nor any soft-float helpers
(`soft-float`). An image must not define allocating formatter routines
(`allocating-formatter`).

## Footprint and symbols gates

A library declares each image and object set in `pico.toml`. Its family
reference supplies the gates in the `firmware` group. The [usage
guide](../../docs/usage-guide.md#embedded-gates) describes the tables.

`python3 dev.py gate footprint` and `gate symbols` use `arm-none-eabi-objdump`
and `arm-none-eabi-nm`; the tools must be on `PATH`. The gates fail over a
stated budget or on a forbidden symbol and name the image and figure. Missing
images, object directories or tools report `CANNOT_RUN`. So do stale builds
and images without debug information needed for an owned-flash budget. Rebuild
stale inputs first. Find buffers behind a footprint increase with
`arm-none-eabi-nm --size-sort --print-size`.

[AR-11](../../docs/technical-specification.md) defines the footprint
calculations. The address comparison retains RAM-resident code flagged
`READONLY` by the SDK.

The `c-heap` set matches whole symbol names: `malloc`, `calloc`, `realloc`,
`free`, their newlib `_malloc_r`, `_calloc_r`, `_realloc_r`, `_free_r` forms,
and mangled operator new/delete entries (including size, alignment and nothrow
forms). `c-heap-alloc` omits deallocation entries. An unrelated name such as
`freeaddrinfo` does not match either set.

Gate each supported configuration, state the gate in the specification, and
keep the measured value in the run record
([EN-03.2](../../house/standard/engineering/03-documentation.md)).

## Sizing profiles

Static sizes and their binding assertions follow
[CXX-11.2](../../house/standard/cxx/11-constrained-targets.md). For example, a
receive buffer smaller than the advertised window loses bytes:

```cpp
static_assert(Profile::rx_capacity >= ADVERTISED_WINDOW,
              "rx buffer must cover a full advertised window or delivered "
              "bytes are dropped");
```

Whole-build profiles use
[`pico_family_declare_profile`](../../docs/usage-guide.md#cmake-entry-points).

A profile macro a consumer can observe must be a `PUBLIC` compile definition
on the target that owns the profile header
([CXX-10.3](../../house/standard/cxx/10-headers-and-abi.md)). A missing macro
can make the consumer and library disagree about a structure's size, causing
stack corruption. Configure a consumer with a non-default profile and search
its `compile_commands.json` for the definition in each translation unit.

## The cross tree

A cross build has its own build directory, because it is a different
toolchain. The [usage
guide](../../docs/usage-guide.md#tree-profiles-and-the-dev-container) covers
SDK and board selection. The merged compile database lets the editor resolve
cross-only sources.
[cxx-build-and-toolchain](../../house/guides/cxx-build-and-toolchain/SKILL.md)
covers linting, and the [build guide](../../docs/build.md) covers family
commands.

## Hardware seams

Hardware interfaces and fakes follow
[CXX-11.7](../../house/standard/cxx/11-constrained-targets.md).

The fake's contract is part of that rule. A read function returning an error
for an idle or absent bus where the caller expects success can hang or fault a
drain loop. A fake written only to the signature misses the defect.

Where an interrupt publishes a value wider than the platform's atomic word,
use a seqlock, a counter that lets readers detect an interrupted update
(`CXX-08.4`). A 64-bit timestamp written as two 32-bit stores can be read
between them, producing a time that never existed.

Where a level-triggered signal can be missed or coalesced, consult the live
level as well as the latched edge, and count fallback reads. A fallback read
has no fresh edge, so its data uses an earlier timestamp. Counting these reads
exposes the loss of timestamp accuracy.

## Claims about on-device behaviour

Hardware-validation claims follow
[EN-06.6](../../house/standard/engineering/06-release-and-versioning.md).
Without hardware, host tests under every configuration, a cross compile and
the footprint gate provide preliminary evidence.
[EN-06.9](../../house/standard/engineering/06-release-and-versioning.md) governs
device tests before merge.

When measuring on a device, bracket a sweep with a health check and discard
degraded data: a radio link, thermal state or power-saving mode can move
throughput several-fold and looks exactly like a regression. Functional
results from a degraded run stay valid; performance numbers do not.
Measurement conditions follow
[EN-06.7](../../house/standard/engineering/06-release-and-versioning.md).
Build type matters because debug and release builds differ in speed.

## What makes a run evidence

A measurement needs conditions (`EN-06.7`) and a way to detect a wrong result:

- A conditions table includes date, board, firmware version, toolchain and
  SDK, dependency versions, build type and network. Each record carries its
  own conditions.
- An independent cross-check is needed. A value inside a plausibility window
  can still be wrong. Compare against an instrument the device does not control, such as
  the capturing host's clock, as well as the plausibility window.
- A count needs a live negative control in the same run. A counter that
  reports zero and a dead counter produce the same output. Where the control cannot fire, such as a lock that links to an empty
  function, the rig cannot be built honestly and the question needs a different
  instrument.
- A run record backing a requirement becomes stale when the code it
  exercises changes.

Arm the capture before reset or reflash where the tooling allows it.
Diagnostic output often arrives before a console can attach. The [device
guide](../device.md#watch-the-console) explains capture with device commands.
