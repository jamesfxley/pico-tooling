// SPDX-License-Identifier: MIT
#pragma once
// A device-test image's results as a TAP 14 stream, with no SDK in it (AR-17).
//
// Cases record into fixed storage; emit() then hands the stream to a callback
// one line at a time. The stream is the subset `device test` judges: the
// version line, an identity comment, test points `ok|not ok <n> - <requirement
// ID> <case-name>` each with an optional detail comment, and last either the
// plan or `Bail out!`. Nothing allocates and nothing throws, so the same header
// serves the host test and the image.

#include <array>
#include <charconv>
#include <cstddef>
#include <iterator>
#include <string_view>

namespace pico_family::device_test {

/// The longest identity comment, without its "# ".
inline constexpr std::size_t IDENTITY_CAP = 190;
/// The capacity and detail length a Results has unless it is told otherwise.
inline constexpr std::size_t DEFAULT_MAX_CASES = 32;
inline constexpr std::size_t DEFAULT_DETAIL_CAP = 80;
/// The longest test point line; a longer one ends in "...".
inline constexpr std::size_t POINT_CAP = 96;

namespace detail {

inline constexpr std::string_view ELLIPSIS = "...";
inline constexpr std::string_view BAIL_PREFIX = "Bail out! ";
inline constexpr std::string_view DETAIL_INDENT = "  # ";
inline constexpr std::size_t NUMBER_CAP = 20;  // digits of a 64-bit number
inline constexpr std::size_t PLAN_CAP = 32;

/// Text in fixed storage. What does not fit is dropped and the end becomes
/// "...", so a truncation is visible in the stream. A line break in the text
/// becomes a space, so a caller's text can never start a line of its own.
template <std::size_t Capacity>
class FixedText {
    static_assert(Capacity > ELLIPSIS.size());

   public:
    /// Add text, or, once it does not fit, end the text in "...".
    void append(std::string_view text) {
        for (const char ch : text) {
            if (truncated_) {
                return;
            }
            if (size_ == Capacity) {
                truncate();
                return;
            }
            chars_[size_] = (ch == '\n' || ch == '\r') ? ' ' : ch;
            ++size_;
        }
    }

    /// Add a decimal number.
    void append_number(std::size_t value) {
        std::array<char, NUMBER_CAP> digits{};
        const auto done =
            std::to_chars(digits.data(), digits.data() + digits.size(), value);
        append({digits.data(), static_cast<std::size_t>(
                                   std::distance(digits.data(), done.ptr))});
    }

    /// The text so far; valid until the next append.
    [[nodiscard]] std::string_view view() const {
        return {chars_.data(), size_};
    }

    /// Whether nothing was added.
    [[nodiscard]] bool empty() const { return size_ == 0; }

   private:
    void truncate() {
        truncated_ = true;
        for (std::size_t i = 0; i < ELLIPSIS.size(); ++i) {
            chars_[Capacity - ELLIPSIS.size() + i] = ELLIPSIS[i];
        }
    }

    std::array<char, Capacity> chars_{};
    std::size_t size_ = 0;
    bool truncated_ = false;
};

}  // namespace detail

/// Up to MaxCases results; a detail comment holds up to DetailCap characters.
/// Overflow is a failure, not a loss: it ends the stream in `Bail out!`.
template <std::size_t MaxCases = DEFAULT_MAX_CASES,
          std::size_t DetailCap = DEFAULT_DETAIL_CAP>
class Results {
   public:
    /// One case. The requirement and the name are copied, so neither has to
    /// outlive the call. A failed case should say why in `detail`.
    void record(std::string_view requirement, std::string_view name,
                bool passed, std::string_view detail = {}) {
        if (bailed_) {
            return;
        }
        if (count_ == MaxCases) {
            detail::FixedText<DetailCap> reason;
            reason.append("more than ");
            reason.append_number(MaxCases);
            reason.append(" cases");
            bail_out(reason.view());
            return;
        }
        Case& next = cases_[count_];
        ++count_;
        next.point.append(passed ? "ok " : "not ok ");
        next.point.append_number(count_);
        next.point.append(" - ");
        next.point.append(requirement);
        next.point.append(" ");
        next.point.append(name);
        if (!detail.empty()) {
            next.detail.append(detail::DETAIL_INDENT);
            next.detail.append(detail);
        }
    }

    /// Stop the run: the stream ends in a `Bail out!` line, with the reason,
    /// instead of a plan.
    /// The first bail-out stands; later results are ignored.
    void bail_out(std::string_view reason) {
        if (bailed_) {
            return;
        }
        bailed_ = true;
        bail_.append(detail::BAIL_PREFIX);
        bail_.append(reason);
    }

    /// Call line(std::string_view) once per line, the content without its LF:
    /// the version line, "# " and the identity, each test point and its detail
    /// comment, then the plan or the bail-out.
    template <typename Line>
    void emit(std::string_view identity, const Line& line) const {
        line(std::string_view{"TAP version 14"});
        detail::FixedText<IDENTITY_CAP + 2> comment;
        comment.append("# ");
        comment.append(identity);
        line(comment.view());
        for (std::size_t i = 0; i < count_; ++i) {
            line(cases_[i].point.view());
            if (!cases_[i].detail.empty()) {
                line(cases_[i].detail.view());
            }
        }
        if (bailed_) {
            line(bail_.view());
            return;
        }
        detail::FixedText<detail::PLAN_CAP> plan;
        plan.append("1..");
        plan.append_number(count_);
        line(plan.view());
    }

   private:
    struct Case {
        detail::FixedText<POINT_CAP> point;
        detail::FixedText<detail::DETAIL_INDENT.size() + DetailCap> detail;
    };

    std::array<Case, MaxCases> cases_{};
    std::size_t count_ = 0;
    bool bailed_ = false;
    detail::FixedText<detail::BAIL_PREFIX.size() + DetailCap> bail_;
};

}  // namespace pico_family::device_test
