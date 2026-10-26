// SPDX-License-Identifier: MIT
// BR-1's cases: padcheck refuses in full a command it cannot carry out in full.
// Built with _GLIBCXX_ASSERTIONS (tools/testing/CMakeLists.txt), so a
// subscript past the line buffer aborts rather than passing.

#include "line_protocol.hpp"

#include <gtest/gtest.h>

#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>

namespace {

using padcheck::at_end;
using padcheck::LineBuffer;
using padcheck::ListField;
using padcheck::PairField;
using padcheck::PinField;
using padcheck::PinList;
using padcheck::take_field;
using padcheck::take_pin;
using padcheck::take_pin_list;
using padcheck::take_pin_pair;

// A pin no parse yields, so a field that leaves the pin alone is visible.
constexpr std::uint32_t UNTOUCHED = padcheck::LAST_PIN + 1;
// How far past the buffer an overlong line runs before its newline.
constexpr std::size_t OVERRUN = 20;

LineBuffer::Ready feed(LineBuffer& buffer, std::string_view text) {
    LineBuffer::Ready ready = LineBuffer::Ready::INCOMPLETE;
    for (const char ch : text) {
        ready = buffer.push(ch);
    }
    return ready;
}

TEST(LineProtocol, FieldsAreTakenInOrder) {
    std::string_view text = "pads 4 5";
    std::string_view field;
    ASSERT_TRUE(take_field(text, field));
    EXPECT_EQ(field, "pads");
    ASSERT_TRUE(take_field(text, field));
    EXPECT_EQ(field, "4");
    ASSERT_TRUE(take_field(text, field));
    EXPECT_EQ(field, "5");
    EXPECT_FALSE(take_field(text, field));
}

TEST(LineProtocol, AnEmptyFieldIsNone) {
    std::uint32_t pin = UNTOUCHED;
    std::string_view empty;
    EXPECT_EQ(take_pin(empty, pin), PinField::NONE);
    std::string_view spaces = "   ";
    EXPECT_EQ(take_pin(spaces, pin), PinField::NONE);
}

TEST(LineProtocol, EveryPinIsTaken) {
    for (std::uint32_t want = 0; want <= padcheck::LAST_PIN; ++want) {
        const std::string text = std::to_string(want);
        std::string_view view = text;
        std::uint32_t pin = UNTOUCHED;
        EXPECT_EQ(take_pin(view, pin), PinField::TAKEN) << text;
        EXPECT_EQ(pin, want);
    }
}

// A prefix parse is the defect take_pin exists to refuse: from_chars stops at
// the first non-digit and reports success.
TEST(LineProtocol, APrefixOutOfRangeOrSignedPinIsInvalid) {
    for (const char* bad :
         {"29", "99", "3x", "1e3", "x", "-1", "+4", "4.0", "999999999999"}) {
        std::string_view text = bad;
        std::uint32_t pin = UNTOUCHED;
        EXPECT_EQ(take_pin(text, pin), PinField::INVALID) << bad;
        EXPECT_EQ(pin, UNTOUCHED)
            << "an INVALID field leaves the pin untouched";
    }
}

// The shape that let `pads 4 5x 6` probe one pad and answer `# ok`.
TEST(LineProtocol, ABadFieldIsNotTheEnd) {
    std::string_view text = "4 5x 6";
    std::uint32_t pin = 0;
    EXPECT_EQ(take_pin(text, pin), PinField::TAKEN);
    EXPECT_EQ(pin, 4U);
    EXPECT_EQ(take_pin(text, pin), PinField::INVALID);
    EXPECT_EQ(pin, 4U);
}

// Acting as each pin was read drove `pads 4 5x`'s GP4 before refusing it.
TEST(LineProtocol, AListIsReadWhole) {
    PinList list;
    std::string_view good = "4 5 6";
    ASSERT_EQ(take_pin_list(good, list), ListField::TAKEN);
    ASSERT_EQ(list.count, 3U);
    EXPECT_EQ(list.pins[0], 4U);
    EXPECT_EQ(list.pins[1], 5U);
    EXPECT_EQ(list.pins[2], 6U);

    PinList bad;
    std::string_view late = "4 5x";
    EXPECT_EQ(take_pin_list(late, bad), ListField::INVALID);
    std::string_view early = "5x 4";
    EXPECT_EQ(take_pin_list(early, bad), ListField::INVALID)
        << "a bad field first is INVALID, not EMPTY";
    std::string_view none = "  ";
    EXPECT_EQ(take_pin_list(none, bad), ListField::EMPTY);
}

// Every GPIO once fills the list; one more field is refused, not dropped.
TEST(LineProtocol, OneMorePinThanEveryGpioIsTooMany) {
    std::string all;
    for (std::uint32_t pin = 0; pin <= padcheck::LAST_PIN; ++pin) {
        all += std::to_string(pin) + " ";
    }
    PinList full;
    std::string_view every = all;
    ASSERT_EQ(take_pin_list(every, full), ListField::TAKEN);
    EXPECT_EQ(full.count, padcheck::LAST_PIN + 1);
    all += "4";
    std::string_view over = all;
    EXPECT_EQ(take_pin_list(over, full), ListField::TOO_MANY);
}

// A pin driving itself, or clocking and carrying data at once, measures
// nothing.
TEST(LineProtocol, APairIsTwoDifferentPins) {
    std::uint32_t first = 0;
    std::uint32_t second = 0;
    std::string_view good = "4 5";
    ASSERT_EQ(take_pin_pair(good, first, second), PairField::TAKEN);
    EXPECT_EQ(first, 4U);
    EXPECT_EQ(second, 5U);
    std::string_view one = "4";
    EXPECT_EQ(take_pin_pair(one, first, second), PairField::MISSING);
    std::string_view bad = "4 5x";
    EXPECT_EQ(take_pin_pair(bad, first, second), PairField::INVALID);
    std::string_view extra = "4 5 6";
    EXPECT_EQ(take_pin_pair(extra, first, second), PairField::TRAILING);
    std::string_view same = "4 4";
    EXPECT_EQ(take_pin_pair(same, first, second), PairField::SAME);
}

TEST(LineProtocol, AtEndTellsAFieldFromSpaces) {
    std::uint32_t pin = 0;
    std::string_view text = "5 6";
    ASSERT_EQ(take_pin(text, pin), PinField::TAKEN);
    EXPECT_FALSE(at_end(text));
    std::string_view exact = "5";
    ASSERT_EQ(take_pin(exact, pin), PinField::TAKEN);
    EXPECT_TRUE(at_end(exact));
    std::string_view padded = "5   ";
    ASSERT_EQ(take_pin(padded, pin), PinField::TAKEN);
    EXPECT_TRUE(at_end(padded));
}

TEST(LineProtocol, ALineEndsAtNewlineAndDropsCarriageReturn) {
    LineBuffer buffer;
    EXPECT_EQ(feed(buffer, "pads 4\n"), LineBuffer::Ready::LINE);
    EXPECT_EQ(buffer.line(), "pads 4");
    buffer.reset();
    EXPECT_EQ(feed(buffer, "pads 4\r\n"), LineBuffer::Ready::LINE);
    EXPECT_EQ(buffer.line(), "pads 4");
    buffer.reset();
    EXPECT_EQ(feed(buffer, "pads"), LineBuffer::Ready::INCOMPLETE);
}

// Refused whole, not truncated and run: before the buffer refused, a long
// prefix followed by a real command ran that command.
TEST(LineProtocol, AnOverlongLineIsDroppedAndTheNextIsRead) {
    LineBuffer buffer;
    std::string long_line(padcheck::LINE_CAP + OVERRUN, 'a');
    long_line += " drive 3 4\n";
    EXPECT_EQ(feed(buffer, long_line), LineBuffer::Ready::OVERLONG);
    EXPECT_EQ(feed(buffer, "pads 7\n"), LineBuffer::Ready::LINE);
    EXPECT_EQ(buffer.line(), "pads 7");
}

// The buffer keeps one byte spare, so LINE_CAP - 1 characters are a line and
// LINE_CAP are not.
TEST(LineProtocol, TheLastCharacterThatFitsAndTheFirstThatDoesNot) {
    LineBuffer edge;
    const std::string fits(padcheck::LINE_CAP - 1, 'b');
    EXPECT_EQ(feed(edge, fits + "\n"), LineBuffer::Ready::LINE);
    EXPECT_EQ(edge.line(), fits);
    edge.reset();
    EXPECT_EQ(feed(edge, fits + "b\n"), LineBuffer::Ready::OVERLONG);
}

}  // namespace
