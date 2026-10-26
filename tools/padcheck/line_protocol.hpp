// SPDX-License-Identifier: MIT
// padcheck's line protocol: the parsing, with no hardware in it (AR-14).
//
// Separated from main.cpp so BR-1 has cases rather than a review note. Every
// function here is pure logic over an external byte stream -- a CXX-12.1 trust
// boundary -- and none of it touches the SDK, so the same header compiles for
// the host test and for the image.
#pragma once

#include <array>
#include <charconv>
#include <cstddef>
#include <cstdint>
#include <string_view>
#include <system_error>

namespace padcheck {

inline constexpr std::uint32_t LAST_PIN = 28;
inline constexpr std::size_t LINE_CAP = 96;

// The next whitespace-delimited field of `text`, advancing `text` past it.
[[nodiscard]] inline bool take_field(std::string_view& text,
                                     std::string_view& field) {
    while (!text.empty() && text.front() == ' ') {
        text.remove_prefix(1);
    }
    if (text.empty()) {
        return false;
    }
    std::size_t end = text.find(' ');
    if (end == std::string_view::npos) {
        end = text.size();
    }
    field = text.substr(0, end);
    text.remove_prefix(end);
    return true;
}

// The outcome of asking for one more pin (BR-1). Three states rather than a
// bool, because a caller that cannot tell NONE from INVALID stops at a
// malformed field and reports success over the pins it never examined -- the
// truncation CXX-07.2 forbids, in a tool whose entire product is a verdict.
enum class PinField : std::uint8_t { NONE, TAKEN, INVALID };

// The next field as a GPIO number, rejecting anything out of range.
[[nodiscard]] inline PinField take_pin(std::string_view& text,
                                       std::uint32_t& pin) {
    std::string_view field;
    if (!take_field(text, field)) {
        return PinField::NONE;
    }
    std::uint32_t value = 0;
    const auto result =
        std::from_chars(field.data(), field.data() + field.size(), value);
    // The whole field, not a prefix of it: from_chars stops at the first
    // non-digit and reports success, so accepting a prefix turns a typo into a
    // silent operation on a plausible wrong pin.
    if (result.ec != std::errc{} || result.ptr != field.data() + field.size() ||
        value > LAST_PIN) {
        return PinField::INVALID;
    }
    pin = value;
    return PinField::TAKEN;
}

// Whether the line holds nothing but spaces. A command taking a fixed number of
// pins refuses a trailing field rather than discarding it: `net 5 6` asked
// about two nets and can be answered for only one.
[[nodiscard]] inline bool at_end(std::string_view text) {
    std::string_view field;
    return !take_field(text, field);
}

// Every GPIO once: the most pins one list command can name. A line has room for
// more fields than this, so the bound is checked rather than assumed.
inline constexpr std::size_t PIN_LIST_CAP = LAST_PIN + 1;

/// The pins one list command named, in the order given.
struct PinList {
    /// The first `count` entries are the pins.
    std::array<std::uint32_t, PIN_LIST_CAP> pins{};
    /// How many entries of `pins` were named.
    std::size_t count = 0;
};

enum class ListField : std::uint8_t { TAKEN, EMPTY, INVALID, TOO_MANY };

// Every remaining field as a pin, read whole before any is acted on (BR-1). A
// verb that acted on each pin as it read it would drive the pins before a
// malformed field later on the line refused the command.
[[nodiscard]] inline ListField take_pin_list(std::string_view& text,
                                             PinList& list) {
    list.count = 0;
    std::uint32_t pin = 0;
    for (;;) {
        const PinField field = take_pin(text, pin);
        if (field == PinField::NONE) {
            return list.count == 0 ? ListField::EMPTY : ListField::TAKEN;
        }
        if (field == PinField::INVALID) {
            return ListField::INVALID;
        }
        if (list.count == list.pins.size()) {
            return ListField::TOO_MANY;
        }
        // Subscripted, not .at(): the return above is the bounds check, and
        // .at() would link the exception runtime into an image built without
        // exceptions, for a throw that cannot happen.
        list.pins[list.count] = pin;
        ++list.count;
    }
}

enum class PairField : std::uint8_t { TAKEN, MISSING, INVALID, TRAILING, SAME };

// Exactly two different pins and nothing after them (BR-1). One pin named
// twice is refused: a pin driving itself, or carrying SDA and SCL at once,
// yields a reading that measures nothing.
[[nodiscard]] inline PairField take_pin_pair(std::string_view& text,
                                             std::uint32_t& first,
                                             std::uint32_t& second) {
    const PinField one = take_pin(text, first);
    const PinField two = take_pin(text, second);
    if (one == PinField::NONE || two == PinField::NONE) {
        return PairField::MISSING;
    }
    if (one == PinField::INVALID || two == PinField::INVALID) {
        return PairField::INVALID;
    }
    if (!at_end(text)) {
        return PairField::TRAILING;
    }
    return first == second ? PairField::SAME : PairField::TAKEN;
}

/// Accumulates one line, and says which of three things it has (BR-1). OVERLONG
/// is separate from LINE because an overlong line is refused, not repaired:
/// recycling the buffer mid-line would run its tail as a command the operator
/// never typed.
class LineBuffer {
   public:
    /// What one more character leaves: no line yet, a whole line, or a refused
    /// overlong line.
    enum class Ready : std::uint8_t { INCOMPLETE, LINE, OVERLONG };

    /// Add one character; a newline completes the line it ends.
    [[nodiscard]] Ready push(char ch) {
        if (ch == '\r') {
            return Ready::INCOMPLETE;
        }
        if (ch == '\n') {
            const Ready ready = overflowed_ ? Ready::OVERLONG : Ready::LINE;
            if (ready == Ready::OVERLONG) {
                used_ = 0;
                overflowed_ = false;
            }
            return ready;
        }
        if (overflowed_) {
            return Ready::INCOMPLETE;  // already refused; discard to newline
        }
        if (used_ + 1 < buffer_.size()) {
            buffer_[used_++] = ch;
        } else {
            overflowed_ = true;
        }
        return Ready::INCOMPLETE;
    }

    /// Valid until the next push(). Call once per LINE, then reset().
    [[nodiscard]] std::string_view line() const {
        return {buffer_.data(), used_};
    }

    /// Forget the current line, whatever state it was in.
    void reset() {
        used_ = 0;
        overflowed_ = false;
    }

   private:
    std::array<char, LINE_CAP> buffer_{};
    std::size_t used_ = 0;
    bool overflowed_ = false;
};

}  // namespace padcheck
