// SPDX-License-Identifier: MIT
// AR-17's host compile of run.hpp against declarations of the SDK calls it
// makes. The cases check what run.hpp decides; the SDK itself is the image's
// business.

#include "pico_family/device_test/run.hpp"

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

struct Board {
    std::uint32_t connect_after_ms = 0;
    std::uint32_t slept_ms = 0;
    std::vector<std::string> written;
};

// The fake board's state, made on first use so no global is mutable.
Board& board() {
    static Board state;
    return state;
}

void reset_board(std::uint32_t connect_after_ms = 0) {
    board().connect_after_ms = connect_after_ms;
    board().slept_ms = 0;
    board().written.clear();
}

constexpr std::uint32_t NEVER = ~std::uint32_t{0};

TEST(DeviceTestRun, WaitingEndsAtOnceWhenAConsoleIsAlreadyOpen) {
    reset_board();
    EXPECT_TRUE(pico_family::device_test::wait_for_console(1));
    EXPECT_EQ(board().slept_ms, 0U);
}

TEST(DeviceTestRun, WaitingEndsWhenTheConsoleOpens) {
    reset_board(3 * CONSOLE_POLL_MS);
    EXPECT_TRUE(pico_family::device_test::wait_for_console());
    EXPECT_EQ(board().slept_ms, 3 * CONSOLE_POLL_MS);
}

TEST(DeviceTestRun, WaitingGivesUpAtTheTimeoutAndReportsIt) {
    reset_board(NEVER);
    constexpr std::uint32_t TIMEOUT_MS = 5 * CONSOLE_POLL_MS;
    EXPECT_FALSE(pico_family::device_test::wait_for_console(TIMEOUT_MS));
    EXPECT_EQ(board().slept_ms, TIMEOUT_MS);
}

TEST(DeviceTestRun, TheIdentityNamesTheImageItsBoardAndTheDirtyCommit) {
    EXPECT_EQ(pico_family::device_test::identity().view(),
              "image demo_tests 1.2.3 board=pico2_w commit=abc123-dirty");
}

TEST(DeviceTestRun, ALineIsWrittenWithItsLineEnd) {
    reset_board();
    pico_family::device_test::put_line("ok 1 - HR-4 a");
    EXPECT_EQ(board().written, (std::vector<std::string>{"ok 1 - HR-4 a"}));
}

// report_forever never returns, so it is compiled, not run.
[[maybe_unused]] constexpr auto REPORTS =
    &pico_family::device_test::report_forever<4, 10>;

}  // namespace

bool stdio_usb_connected() {
    return board().slept_ms >= board().connect_after_ms;
}

void sleep_ms(std::uint32_t ms) { board().slept_ms += ms; }

int stdio_put_string(const char* text, int len, bool newline,
                     bool cr_translation) {
    EXPECT_TRUE(newline);
    EXPECT_TRUE(cr_translation);
    board().written.emplace_back(text, static_cast<std::size_t>(len));
    return len;
}
