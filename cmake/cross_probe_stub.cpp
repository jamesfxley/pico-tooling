// SPDX-License-Identifier: MIT
// The one stub every libnosys syscall name resolves to in a cross probe.
//
// A probe is freestanding and never run, so no syscall is ever called; the link
// only needs a definition for each name the C library references, and a stub
// that carries no link-time warning. The names are bound to this function by
// the linker (pico_family_add_cross_probe), so no source here spells a name the
// C library's ABI fixes.
#include <cerrno>

extern "C" int pico_family_probe_unsupported() {
    errno = ENOSYS;
    return -1;
}
