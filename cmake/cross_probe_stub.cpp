// SPDX-License-Identifier: MIT
// The linker binds libnosys syscall names to this stub in a cross probe.
// The probe is freestanding and never runs. The stub provides definitions
// without link-time warnings or C++ declarations of C library names.
#include <cerrno>

extern "C" int pico_family_probe_unsupported() {
    errno = ENOSYS;
    return -1;
}
