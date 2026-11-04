// SPDX-License-Identifier: MIT
// padcheck's parser reads an external byte stream without hardware (AR-14).
// The same header compiles for host tests and the image (BR-1).
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

// The next field is returned in `field`, advancing `text` past it.
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

// The next pin can be valid, absent or invalid (BR-1). An invalid field
// cannot be treated as the end of the list.
enum class PinField : std::uint8_t { NONE, TAKEN, INVALID };

// The next field is a GPIO number only when the whole field is in range.
[[nodiscard]] inline PinField take_pin(std::string_view& text,
                                       std::uint32_t& pin) {
    std::string_view field;
    if (!take_field(text, field)) {
        return PinField::NONE;
    }
    std::uint32_t value = 0;
    const auto result =
        std::from_chars(field.data(), field.data() + field.size(), value);
    // from_chars can succeed on a numeric prefix. Accepting that prefix
    // would act on the wrong pin when the field has a suffix.
    if (result.ec != std::errc{} || result.ptr != field.data() + field.size() ||
        value > LAST_PIN) {
        return PinField::INVALID;
    }
    pin = value;
    return PinField::TAKEN;
}

// The result reports whether only spaces remain. A fixed-argument command
// rejects trailing fields so that `net 5 6` cannot be answered for one net.
[[nodiscard]] inline bool at_end(std::string_view text) {
    std::string_view field;
    return !take_field(text, field);
}

// A list command can name every GPIO once. A line can hold more fields than
// there are GPIOs, so the list length needs a separate check.
inline constexpr std::size_t PIN_LIST_CAP = LAST_PIN + 1;

/// The list stores pins in the order named by the command.
struct PinList {
    /// The first `count` entries are the pins.
    std::array<std::uint32_t, PIN_LIST_CAP> pins{};
    /// This counts the named entries in `pins`.
    std::size_t count = 0;
};

enum class ListField : std::uint8_t { TAKEN, EMPTY, INVALID, TOO_MANY };

// All remaining fields are read as pins before any is acted on (BR-1).
// Acting before validation could drive pins in an invalid command.
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
        // The bounds check permits subscripting without the exception runtime.
        list.pins[list.count] = pin;
        ++list.count;
    }
}

enum class PairField : std::uint8_t { TAKEN, MISSING, INVALID, TRAILING, SAME };

// The command takes two different pins and no trailing fields (BR-1).
// A pin driving itself, or carrying SDA and SCL, yields no useful measurement.
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

/// This accumulates a line and reports whether it is complete or overlong
/// (BR-1). An overlong line is discarded through its newline so its tail cannot
/// become a command.
class LineBuffer {
   public:
    /// A character leaves an incomplete, complete or overlong line.
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

    /// The view is valid until the next push(). Call once per LINE, then
    /// reset().
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
