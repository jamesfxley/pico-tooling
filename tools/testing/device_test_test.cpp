// SPDX-License-Identifier: MIT
// AR-16's cases: a device-test image's output, over declarations of the SDK
// calls it makes. Built three times (tools/testing/CMakeLists.txt), once per
// kind of source the image can name: SOURCE_CLEAN, SOURCE_DIRTY or
// SOURCE_UNKNOWN.

#include "pico_family/device_test.hpp"

#include <gtest/gtest.h>

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

#include "pico/stdio.h"
#include "pico/stdio_usb.h"
#include "pico/time.h"

namespace {

using pico_family::device_test::CONSOLE_POLL_MS;
using pico_family::device_test::CONSOLE_WAIT_MS;
using pico_family::device_test::wait_for_console;
// Not `Run`: that is a member of every TEST body's base class.
using DeviceRun = pico_family::device_test::Run;
using Lines = std::vector<std::string>;

struct Board {
    std::uint32_t connect_after_ms = 0;
    std::uint32_t slept_ms = 0;
    std::string partial;
    Lines lines;
};

// The fake board's state, made on first use so no global is mutable.
Board& board() {
    static Board state;
    return state;
}

constexpr std::uint32_t NEVER = ~std::uint32_t{0};

void reset_board(std::uint32_t connect_after_ms = 0) {
    board() = Board{};
    board().connect_after_ms = connect_after_ms;
}

#if defined(SOURCE_DIRTY)
constexpr std::string_view IDENTITY =
    "device-test: image demo_tests 1.2.3 board=pico2_w commit=abc123-dirty";
constexpr std::string_view SOURCE_REASON = "dirty source";
#elif defined(SOURCE_UNKNOWN)
constexpr std::string_view IDENTITY =
    "device-test: image demo_tests 1.2.3 board=pico2_w commit=unknown";
constexpr std::string_view SOURCE_REASON = "source commit unknown";
#else
constexpr std::string_view IDENTITY =
    "device-test: image demo_tests 1.2.3 board=pico2_w commit=abc123";
constexpr std::string_view SOURCE_REASON;
#endif

// The last line of a run whose cases did the same, with a source reason added.
std::string with_source(std::string reasons) {
    if (SOURCE_REASON.empty()) {
        return reasons;
    }
    return (reasons.empty() ? "" : reasons + "; ") + std::string{SOURCE_REASON};
}

std::string last_line(const DeviceRun& run, bool* passed = nullptr) {
    const bool ok = run.report();
    if (passed != nullptr) {
        *passed = ok;
    }
    return board().lines.back();
}

TEST(DeviceTest, WaitingEndsAtOnceWhenAConsoleIsAlreadyOpen) {
    reset_board();
    EXPECT_TRUE(wait_for_console(1));
    EXPECT_EQ(board().slept_ms, 0U);
}

TEST(DeviceTest, WaitingEndsWhenTheConsoleOpens) {
    reset_board(3 * CONSOLE_POLL_MS);
    EXPECT_TRUE(wait_for_console());
    EXPECT_EQ(board().slept_ms, 3 * CONSOLE_POLL_MS);
}

TEST(DeviceTest, WaitingGivesUpAfterThirtySeconds) {
    reset_board(NEVER);
    EXPECT_FALSE(wait_for_console());
    EXPECT_EQ(board().slept_ms, CONSOLE_WAIT_MS);
    EXPECT_EQ(CONSOLE_WAIT_MS, 30000U);
}

TEST(DeviceTest, WaitingNeverSleepsPastATimeoutThatIsNotAWholePollCount) {
    reset_board(NEVER);
    constexpr std::uint32_t TIMEOUT_MS = (2 * CONSOLE_POLL_MS) + 5;
    EXPECT_FALSE(wait_for_console(TIMEOUT_MS));
    EXPECT_EQ(board().slept_ms, TIMEOUT_MS);
}

TEST(DeviceTest, ARunWaitsForTheConsoleThenPrintsItsIdentity) {
    reset_board(2 * CONSOLE_POLL_MS);
    const DeviceRun run;
    EXPECT_EQ(board().slept_ms, 2 * CONSOLE_POLL_MS);
    EXPECT_EQ(board().lines, (Lines{std::string{IDENTITY}}));
}

TEST(DeviceTest, ACheckPrintsItsLineAtOnce) {
    reset_board();
    DeviceRun run;
    run.check("HR-4", "i2c-refuses-swapped-sda-scl", true);
    run.check("HR-4", "spi-refuses-the-other-instance", false,
              "init=accepted pads=changed");
    EXPECT_EQ(board().lines, (Lines{std::string{IDENTITY},
                                    "PASS HR-4 i2c-refuses-swapped-sda-scl",
                                    "FAIL HR-4 spi-refuses-the-other-instance: "
                                    "init=accepted pads=changed"}));
}

TEST(DeviceTest, ALineBreakInCallerTextPrintsAsASpace) {
    reset_board();
    DeviceRun run;
    run.check("HR-4", "a\nPASS HR-9 forged", true,
              "x\r\ndevice-test: PASS (9)");
    ASSERT_EQ(board().lines.size(), 2U);
    EXPECT_EQ(board().lines[1],
              "PASS HR-4 a PASS HR-9 forged: x  device-test: PASS (9)");
}

TEST(DeviceTest, AllCasesPassingEndsInPassWithTheCountUnlessTheSourceFails) {
    reset_board();
    DeviceRun run;
    run.check("HR-4", "a", true);
    run.check("HR-5", "b", true);
    bool passed = false;
    const std::string line = last_line(run, &passed);
    if (SOURCE_REASON.empty()) {
        EXPECT_EQ(line, "device-test: PASS (2 cases)");
        EXPECT_TRUE(passed);
    } else {
        EXPECT_EQ(line, "device-test: FAIL (" + with_source("") + ")");
        EXPECT_FALSE(passed);
    }
}

TEST(DeviceTest, FailedCasesAreCountedOfAll) {
    reset_board();
    DeviceRun run;
    run.check("HR-4", "a", false);
    run.check("HR-4", "b", true);
    run.check("HR-5", "c", false, "why");
    bool passed = true;
    EXPECT_EQ(last_line(run, &passed),
              "device-test: FAIL (" + with_source("2 of 3 failed") + ")");
    EXPECT_FALSE(passed);
}

TEST(DeviceTest, NoCasesFails) {
    reset_board();
    const DeviceRun run;
    bool passed = true;
    EXPECT_EQ(last_line(run, &passed),
              "device-test: FAIL (" + with_source("no cases") + ")");
    EXPECT_FALSE(passed);
}

TEST(DeviceTest, ARequirementThatIsNotAnIdFailsTheCaseAndNamesIt) {
    for (const std::string_view bad :
         {"", "hr-4", "HR4", "HR-", "-4", "H R-4", "HR-4x", "AB-C-1", "4R-4"}) {
        reset_board();
        DeviceRun run;
        run.check("HR-4", "a", true);
        run.check(bad, "b", true);
        run.check("HR-5", "c", true);
        run.check(bad, "d", true);
        EXPECT_EQ(board().lines[2], "FAIL " + std::string{bad} + " b") << bad;
        EXPECT_EQ(last_line(run),
                  "device-test: FAIL (" +
                      with_source("2 of 4 failed; case 2 does not start with a "
                                  "requirement ID") +
                      ")")
            << bad;
    }
}

TEST(DeviceTest, ARequirementThatIsAnIdPasses) {
    for (const std::string_view good : {"HR-4", "AR-16", "A1-0", "FW3X-007"}) {
        reset_board();
        DeviceRun run;
        run.check(good, "a", true);
        EXPECT_EQ(board().lines[1], "PASS " + std::string{good} + " a") << good;
    }
}

TEST(DeviceTest, SeveralReasonsJoinWithASemicolon) {
    reset_board();
    DeviceRun run;
    run.check("bad", "a", false);
    EXPECT_EQ(last_line(run),
              "device-test: FAIL (" +
                  with_source("1 of 1 failed; case 1 does not start with a "
                              "requirement ID") +
                  ")");
}

// finish() never returns, so it is compiled, not run.
[[maybe_unused]] constexpr auto FINISHES = &DeviceRun::finish;

}  // namespace

bool stdio_usb_connected() {
    return board().slept_ms >= board().connect_after_ms;
}

void sleep_ms(std::uint32_t ms) { board().slept_ms += ms; }

int stdio_put_string(const char* text, int len, bool newline,
                     bool cr_translation) {
    EXPECT_TRUE(cr_translation);
    board().partial.append(text, static_cast<std::size_t>(len));
    if (newline) {
        board().lines.push_back(board().partial);
        board().partial.clear();
    }
    return len;
}
