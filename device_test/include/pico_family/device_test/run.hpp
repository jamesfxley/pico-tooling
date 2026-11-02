// SPDX-License-Identifier: MIT
#pragma once
// Run a device-test image on the board: wait for the console, then report the
// results over the SDK's stdio (AR-17). For the image it compiles against the
// Pico SDK; the host test compiles it against declarations of the three SDK
// calls it makes. The identity definitions come from
// pico_family_add_device_test().

#include <cstddef>
#include <cstdint>
#include <string_view>

#include "pico/stdio.h"
#include "pico/stdio_usb.h"
#include "pico/time.h"
#include "pico_family/device_test/tap.hpp"

#if !defined(PICO_FAMILY_DEVICE_TEST_NAME) ||    \
    !defined(PICO_FAMILY_DEVICE_TEST_VERSION) || \
    !defined(PICO_FAMILY_DEVICE_TEST_BOARD) ||   \
    !defined(PICO_FAMILY_DEVICE_TEST_COMMIT) ||  \
    !defined(PICO_FAMILY_DEVICE_TEST_DIRTY)
#error \
    "add the image with pico_family_add_device_test(), which sets its identity"
#endif

namespace pico_family::device_test {

inline constexpr std::uint32_t CONSOLE_POLL_MS = 10;
inline constexpr std::uint32_t DEFAULT_CONSOLE_TIMEOUT_MS = 30000;
inline constexpr std::uint32_t DEFAULT_REPORT_PERIOD_MS = 2000;

/// Wait up to timeout_ms for a host to open the USB console. Returns whether
/// one did; the run continues either way.
inline bool wait_for_console(
    std::uint32_t timeout_ms = DEFAULT_CONSOLE_TIMEOUT_MS) {
    std::uint32_t waited = 0;
    while (!stdio_usb_connected()) {
        if (waited >= timeout_ms) {
            return false;
        }
        sleep_ms(CONSOLE_POLL_MS);
        waited += CONSOLE_POLL_MS;
    }
    return true;
}

/// The identity comment: `image <name> <version> board=<board>
/// commit=<sha>[-dirty]`. The commit is `unknown` when the configure could
/// not ask git.
inline detail::FixedText<IDENTITY_CAP> identity() {
    detail::FixedText<IDENTITY_CAP> text;
    text.append("image ");
    text.append(PICO_FAMILY_DEVICE_TEST_NAME);
    text.append(" ");
    text.append(PICO_FAMILY_DEVICE_TEST_VERSION);
    text.append(" board=");
    text.append(PICO_FAMILY_DEVICE_TEST_BOARD);
    text.append(" commit=");
    text.append(PICO_FAMILY_DEVICE_TEST_COMMIT);
    if (PICO_FAMILY_DEVICE_TEST_DIRTY != 0) {
        text.append("-dirty");
    }
    return text;
}

inline void put_line(std::string_view text) {
    stdio_put_string(text.data(), static_cast<int>(text.size()), true, true);
}

/// Emit the stream, then again every period_ms, forever, so a console that
/// attaches late still receives a whole stream.
template <std::size_t MaxCases, std::size_t DetailCap>
[[noreturn]] void report_forever(
    const Results<MaxCases, DetailCap>& results,
    std::uint32_t period_ms = DEFAULT_REPORT_PERIOD_MS) {
    const auto who = identity();
    for (;;) {
        results.emit(who.view(), put_line);
        sleep_ms(period_ms);
    }
}

}  // namespace pico_family::device_test
