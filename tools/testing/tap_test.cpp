// SPDX-License-Identifier: MIT
// AR-17's cases: the results of a device-test image as a TAP 14 stream, with no
// SDK and no board involved.

#include "pico_family/device_test/tap.hpp"

#include <gtest/gtest.h>

#include <cstddef>
#include <string>
#include <string_view>
#include <vector>

namespace {

using pico_family::device_test::Results;

// A detail cap small enough to show the truncation, and text over each cap.
constexpr std::size_t SMALL_DETAIL_CAP = 10;
constexpr std::size_t OVER_POINT_CAP = pico_family::device_test::POINT_CAP * 2;
constexpr std::size_t OVER_IDENTITY_CAP =
    pico_family::device_test::IDENTITY_CAP * 2;

constexpr std::string_view IDENTITY =
    "image demo 0.1.0 board=pico2_w commit=abc";

template <typename Collection>
std::vector<std::string> emitted(const Collection& results) {
    std::vector<std::string> lines;
    results.emit(IDENTITY,
                 [&lines](std::string_view line) { lines.emplace_back(line); });
    return lines;
}

using Lines = std::vector<std::string>;

TEST(DeviceTestTap, AStreamIsVersionIdentityPointsAndPlanLast) {
    Results<> results;
    results.record("HR-4", "i2c-refuses-unreachable-pins", true);
    results.record("HR-4", "spi-refuses-unreachable-pins", false,
                   "miso=17 init=ok, expected INVALID_ARGUMENT");
    results.record("HR-5", "i2c-accepts-default-pins", true);
    EXPECT_EQ(
        emitted(results),
        (Lines{"TAP version 14", "# image demo 0.1.0 board=pico2_w commit=abc",
               "ok 1 - HR-4 i2c-refuses-unreachable-pins",
               "not ok 2 - HR-4 spi-refuses-unreachable-pins",
               "  # miso=17 init=ok, expected INVALID_ARGUMENT",
               "ok 3 - HR-5 i2c-accepts-default-pins", "1..3"}));
}

TEST(DeviceTestTap, NoCasesIsAPlanOfZero) {
    const Results<> results;
    EXPECT_EQ(emitted(results).back(), "1..0");
}

TEST(DeviceTestTap, ADetailBeyondItsCapIsTruncatedAndMarked) {
    Results<4, SMALL_DETAIL_CAP> results;
    results.record("HR-4", "a", false, "0123456789");
    results.record("HR-4", "b", false, "0123456789X");
    const Lines lines = emitted(results);
    EXPECT_EQ(lines[3], "  # 0123456789");
    EXPECT_EQ(lines[5], "  # 0123456...");
}

TEST(DeviceTestTap, ARecordBeyondTheCapacityEndsTheRunInABailOut) {
    Results<2> results;
    results.record("HR-4", "a", true);
    results.record("HR-4", "b", true);
    results.record("HR-4", "c", true);
    results.record("HR-4", "d", true);
    const Lines lines = emitted(results);
    ASSERT_EQ(lines.size(), 5U);
    EXPECT_EQ(lines[2], "ok 1 - HR-4 a");
    EXPECT_EQ(lines[3], "ok 2 - HR-4 b");
    EXPECT_EQ(lines[4], "Bail out! more than 2 cases");
}

TEST(DeviceTestTap, ABailOutReplacesThePlanAndTheFirstOneStands) {
    Results<> results;
    results.record("HR-4", "a", true);
    results.bail_out("hub silent");
    results.bail_out("second reason");
    results.record("HR-4", "late", true);
    const Lines lines = emitted(results);
    EXPECT_EQ(lines, (Lines{"TAP version 14",
                            "# image demo 0.1.0 board=pico2_w commit=abc",
                            "ok 1 - HR-4 a", "Bail out! hub silent"}));
}

TEST(DeviceTestTap, ALineBreakInTextNeverStartsALineOfItsOwn) {
    Results<> results;
    results.record("HR-4", "a\nok 9 - forged", false, "x\r\nBail out! forged");
    results.bail_out("one\nTAP version 14");
    const Lines lines = emitted(results);
    ASSERT_EQ(lines.size(), 5U);
    EXPECT_EQ(lines[2], "not ok 1 - HR-4 a ok 9 - forged");
    EXPECT_EQ(lines[3], "  # x  Bail out! forged");
    EXPECT_EQ(lines[4], "Bail out! one TAP version 14");
}

TEST(DeviceTestTap, ATooLongPointOrIdentityEndsInAnEllipsisWithinItsCap) {
    Results<> results;
    results.record("HR-4", std::string(OVER_POINT_CAP, 'n'), true);
    std::vector<std::string> lines;
    results.emit(std::string(OVER_IDENTITY_CAP, 'i'),
                 [&lines](std::string_view line) { lines.emplace_back(line); });
    EXPECT_EQ(lines[1].size(), pico_family::device_test::IDENTITY_CAP + 2);
    EXPECT_EQ(lines[1].substr(lines[1].size() - 3), "...");
    EXPECT_EQ(lines[2].size(), pico_family::device_test::POINT_CAP);
    EXPECT_EQ(lines[2].substr(lines[2].size() - 3), "...");
}

}  // namespace
