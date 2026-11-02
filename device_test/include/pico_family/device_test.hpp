// SPDX-License-Identifier: MIT
#pragma once
// A device-test image's output convention, over the Pico SDK's stdio (AR-16).
//
// Run prints an identity line, check() prints one line per case as it
// finishes, and finish() prints the last line. Nothing is stored beyond two
// counters and a flag. The identity definitions come from
// pico_family_add_device_test(). A crash or hang prints no last line.

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <string_view>

#include "pico/stdio.h"
#include "pico/stdio_usb.h"
#include "pico/time.h"

#if !defined(PICO_FAMILY_DEVICE_TEST_NAME) ||    \
    !defined(PICO_FAMILY_DEVICE_TEST_VERSION) || \
    !defined(PICO_FAMILY_DEVICE_TEST_BOARD) ||   \
    !defined(PICO_FAMILY_DEVICE_TEST_COMMIT) ||  \
    !defined(PICO_FAMILY_DEVICE_TEST_DIRTY)
#error \
    "add the image with pico_family_add_device_test(), which sets its identity"
#endif

namespace pico_family::device_test {

inline constexpr std::uint32_t CONSOLE_WAIT_MS = 30000;
inline constexpr std::uint32_t CONSOLE_POLL_MS = 10;
inline constexpr std::uint32_t IDLE_MS = 1000;
inline constexpr std::size_t NUMBER_CHARS = 20;  // digits of a 64-bit number
inline constexpr std::size_t DECIMAL = 10;

/// Wait up to timeout_ms for a host to open the USB console; whether one did.
inline bool wait_for_console(std::uint32_t timeout_ms = CONSOLE_WAIT_MS) {
    std::uint32_t remaining = timeout_ms;
    while (!stdio_usb_connected()) {
        if (remaining == 0) {
            return false;
        }
        const std::uint32_t step =
            remaining < CONSOLE_POLL_MS ? remaining : CONSOLE_POLL_MS;
        sleep_ms(step);
        remaining -= step;
    }
    return true;
}

#if PICO_FAMILY_DEVICE_TEST_DIRTY != 0
inline constexpr bool DIRTY_SOURCE = true;
#else
inline constexpr bool DIRTY_SOURCE = false;
#endif

namespace detail {

inline void emit(std::string_view piece) {
    stdio_put_string(piece.data(), static_cast<int>(piece.size()), false, true);
}

/// Print text without ending the line; a line break in it prints as a space.
inline void put(std::string_view text) {
    while (!text.empty()) {
        const std::size_t end = text.find_first_of("\r\n");
        emit(text.substr(0, end));
        if (end == std::string_view::npos) {
            return;
        }
        emit(" ");
        text.remove_prefix(end + 1);
    }
}

inline void put_number(std::size_t value) {
    std::array<char, NUMBER_CHARS> digits{};
    std::size_t first = digits.size();
    while (true) {
        --first;
        digits[first] = static_cast<char>('0' + (value % DECIMAL));
        value /= DECIMAL;
        if (value == 0) {
            break;
        }
    }
    stdio_put_string(&digits[first], static_cast<int>(digits.size() - first),
                     false, true);
}

inline void end_line() { stdio_put_string("", 0, true, true); }

/// Print "; " unless this is the first reason on the line.
inline void separate(bool& more) {
    put(more ? "; " : "");
    more = true;
}

/// Whether `text` is a requirement ID: [A-Z][A-Z0-9]*-[0-9]+.
inline bool is_requirement(std::string_view text) {
    const auto upper = [](char ch) { return ch >= 'A' && ch <= 'Z'; };
    const auto digit = [](char ch) { return ch >= '0' && ch <= '9'; };
    const std::size_t hyphen = text.rfind('-');
    if (hyphen == std::string_view::npos || hyphen == 0 ||
        !upper(text.front())) {
        return false;
    }
    const std::string_view number = text.substr(hyphen + 1);
    return !number.empty() && std::ranges::all_of(number, digit) &&
           std::ranges::all_of(text.substr(0, hyphen),
                               [&](char ch) { return upper(ch) || digit(ch); });
}

}  // namespace detail

/// One device-test run.
class Run {
   public:
    /// Wait for the USB console, then print the identity line.
    Run() {
        static_cast<void>(wait_for_console());
        detail::put("device-test: image " PICO_FAMILY_DEVICE_TEST_NAME
                    " " PICO_FAMILY_DEVICE_TEST_VERSION
                    " board=" PICO_FAMILY_DEVICE_TEST_BOARD
                    " commit=" PICO_FAMILY_DEVICE_TEST_COMMIT);
        detail::put(dirty_source() ? "-dirty" : "");
        detail::end_line();
    }

    /// Print `PASS|FAIL <requirement> <name>[: <detail>]` and count the case.
    void check(std::string_view requirement, std::string_view name, bool passed,
               std::string_view detail = {}) {
        ++cases_;
        const bool shaped = detail::is_requirement(requirement);
        if (!shaped && first_unshaped_ == 0) {
            first_unshaped_ = cases_;
        }
        failed_ += (passed && shaped) ? 0 : 1;
        detail::put(passed && shaped ? "PASS " : "FAIL ");
        detail::put(requirement);
        detail::put(" ");
        detail::put(name);
        if (!detail.empty()) {
            detail::put(": ");
            detail::put(detail);
        }
        detail::end_line();
    }

    /// Print the last line and say whether the run passed.
    [[nodiscard]] bool report() const {
        const bool passed =
            cases_ != 0 && failed_ == 0 && !dirty_source() && !unknown_source();
        if (passed) {
            detail::put("device-test: PASS (");
            detail::put_number(cases_);
            detail::put(" cases)");
        } else {
            bool more = false;
            detail::put("device-test: FAIL (");
            if (cases_ == 0) {
                detail::separate(more);
                detail::put("no cases");
            }
            if (failed_ != 0) {
                detail::separate(more);
                detail::put_number(failed_);
                detail::put(" of ");
                detail::put_number(cases_);
                detail::put(" failed");
            }
            if (first_unshaped_ != 0) {
                detail::separate(more);
                detail::put("case ");
                detail::put_number(first_unshaped_);
                detail::put(" does not start with a requirement ID");
            }
            if (dirty_source()) {
                detail::separate(more);
                detail::put("dirty source");
            }
            if (unknown_source()) {
                detail::separate(more);
                detail::put("source commit unknown");
            }
            detail::put(")");
        }
        detail::end_line();
        return passed;
    }

    /// Print the last line, then idle: the run ends when the host reads it.
    [[noreturn]] void finish() const {
        static_cast<void>(report());
        for (;;) {
            sleep_ms(IDLE_MS);
        }
    }

   private:
    static bool dirty_source() { return DIRTY_SOURCE; }

    static bool unknown_source() {
        return std::string_view{PICO_FAMILY_DEVICE_TEST_COMMIT} == "unknown";
    }

    std::size_t cases_ = 0;
    std::size_t failed_ = 0;
    std::size_t first_unshaped_ = 0;  // 1-based; 0 when every case had an ID
};

}  // namespace pico_family::device_test
