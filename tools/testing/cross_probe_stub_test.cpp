// SPDX-License-Identifier: MIT
// The stub every libnosys syscall name resolves to in a cross probe
// (pico_family_add_cross_probe) reports that no system call exists. A probe is
// never run, so this host test is the only place the stub's body executes.

#include <gtest/gtest.h>

#include <cerrno>

extern "C" int pico_family_probe_unsupported();

namespace {

TEST(CrossProbeStub, FailsWithMinusOneAndSetsEnosys) {
    errno = 0;
    EXPECT_EQ(pico_family_probe_unsupported(), -1);
    EXPECT_EQ(errno, ENOSYS);
}

TEST(CrossProbeStub, ReplacesAnEarlierErrnoEachCall) {
    errno = EINTR;
    EXPECT_EQ(pico_family_probe_unsupported(), -1);
    EXPECT_EQ(errno, ENOSYS);
}

}  // namespace
