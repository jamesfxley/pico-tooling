// SPDX-License-Identifier: MIT
// BR-1's refusal of a dropped status. With PROBE undefined this compiles and is
// part of every build, so the probe itself is sound; each PROBE value discards
// one result the line protocol marks [[nodiscard]], which must not compile.

#include <cstdint>
#include <string_view>

#include "line_protocol.hpp"

namespace {

[[maybe_unused]] void line_protocol_probe() {
    [[maybe_unused]] std::string_view text = "4 5";
    [[maybe_unused]] std::string_view field;
    [[maybe_unused]] std::uint32_t pin = 0;
    [[maybe_unused]] std::uint32_t second = 0;
    [[maybe_unused]] padcheck::PinList list;
    [[maybe_unused]] padcheck::LineBuffer buffer;
    [[maybe_unused]] const char ch = '4';
#if defined(PROBE) && PROBE == 1
    padcheck::take_field(text, field);
#elif defined(PROBE) && PROBE == 2
    padcheck::take_pin(text, pin);
#elif defined(PROBE) && PROBE == 3
    padcheck::at_end(text);
#elif defined(PROBE) && PROBE == 4
    buffer.push(ch);
#elif defined(PROBE) && PROBE == 5
    padcheck::take_pin_list(text, list);
#elif defined(PROBE) && PROBE == 6
    padcheck::take_pin_pair(text, pin, second);
#else
    static_cast<void>(padcheck::take_field(text, field));
    static_cast<void>(padcheck::take_pin(text, pin));
    static_cast<void>(padcheck::at_end(text));
    static_cast<void>(buffer.push(ch));
    static_cast<void>(padcheck::take_pin_list(text, list));
    static_cast<void>(padcheck::take_pin_pair(text, pin, second));
#endif
}

}  // namespace
