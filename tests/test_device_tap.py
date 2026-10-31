# SPDX-License-Identifier: MIT
"""The judge of a device-test TAP stream, over text alone (AR-16)."""

import pytest

from pico_tooling.device_tap import first_stream, judge, report

HEAD = "TAP version 14\n# image demo 0.1.0 board=pico2_w commit=abc123\n"
PASSING = HEAD + "ok 1 - HR-4 a\nok 2 - HR-4 b\nok 3 - HR-5 c\n1..3\n"


def verdict_of(text):
    stream = first_stream(text)
    assert stream is not None, text
    return judge(stream)


def test_every_point_ok_and_counted_by_the_plan_passes():
    verdict = verdict_of(PASSING)
    assert not verdict.reasons
    assert report(verdict) == [
        "==> image demo 0.1.0 board=pico2_w commit=abc123",
        "==> HR-4: 2 passed, 0 failed",
        "==> HR-5: 1 passed, 0 failed",
        "==> device test: PASS",
    ]


def test_a_not_ok_fails_and_names_its_case_and_comments():
    text = HEAD + "ok 1 - HR-4 a\nnot ok 2 - HR-4 b\n  # case 2: miso=17\n1..2\n"
    lines = report(verdict_of(text))
    assert "==> HR-4: 1 passed, 1 failed" in lines
    assert lines[-3:] == [
        "==> not ok 2 - HR-4 b",
        "==>     case 2: miso=17",
        "==> device test: FAIL: 1 test point not ok",
    ]


@pytest.mark.parametrize("bail", ["Bail out! hub silent", "BAIL OUT! hub silent"])
def test_bail_out_fails_with_its_reason_in_any_case(bail):
    verdict = verdict_of(HEAD + f"ok 1 - HR-4 a\n{bail}\n")
    assert verdict.reasons == ["Bail out! hub silent"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("ok 1 - HR-4 a\n1..2\n", "the plan is 1..2 but 1 test points ran"),
        ("ok 1 - HR-4 a\nok 2 - HR-4 b\n1..1\n", "the plan is 1..1 but 2"),
        ("ok 1 - HR-4 a\nok 1 - HR-4 b\n1..2\n", "numbers are not 1..N"),
        ("ok 2 - HR-4 a\nok 1 - HR-4 b\n1..2\n", "numbers are not 1..N"),
        ("1..0\n", "no case ran"),
    ],
)
def test_a_count_or_numbering_mismatch_fails(body, message):
    (reason,) = verdict_of(HEAD + body).reasons
    assert message in reason


def test_unnumbered_points_count_in_order():
    assert not verdict_of(HEAD + "ok - HR-4 a\nok - HR-4 b\n1..2\n").reasons


@pytest.mark.parametrize("tail", ["# SKIP no pin", "# todo later", "#skip"])
def test_a_skip_or_todo_directive_fails(tail):
    reasons = verdict_of(HEAD + f"ok 1 - HR-4 a {tail}\n1..1\n").reasons
    assert any("directive" in reason for reason in reasons)


def test_a_yaml_block_fails():
    text = HEAD + "ok 1 - HR-4 a\n  ---\n  at: x\n  ...\n1..1\n"
    assert verdict_of(text).reasons == ["a YAML block is outside the subset"]


def test_crlf_and_cr_read_as_lf():
    assert not verdict_of(PASSING.replace("\n", "\r\n")).reasons
    assert not verdict_of(PASSING.replace("\n", "\r")).reasons


def test_lines_that_are_not_tap_are_passed_over():
    text = HEAD.replace("\n#", "\nboot banner\n#", 1)
    text += "ok 1 - HR-4 a\nlibrary says hello\n\n  indented noise\n1..1\n"
    assert not verdict_of(text).reasons


def test_a_stream_without_a_plan_is_not_complete():
    assert first_stream(HEAD + "ok 1 - HR-4 a\n") is None


def test_the_last_line_counts_only_once_it_is_terminated():
    assert first_stream(HEAD + "ok 1 - HR-4 a\n1..1") is None
    assert first_stream(HEAD + "ok 1 - HR-4 a\n1..1\n") is not None


def test_a_plan_joined_midway_is_skipped_for_the_next_stream():
    text = "ok 2 - HR-4 b\n1..2\n" + PASSING
    stream = first_stream(text)
    assert stream[0] == "TAP version 14"
    assert not judge(stream).reasons
    assert first_stream("ok 2 - HR-4 b\n1..2\n") is None


def test_a_stream_cut_short_is_abandoned_for_the_next_version_line():
    text = HEAD + "ok 1 - HR-4 a\n" + PASSING
    assert len(first_stream(text)) == len(PASSING.splitlines())


def test_a_repeated_stream_is_judged_once_from_its_first_copy():
    stream = first_stream(PASSING + PASSING.replace("ok 3", "not ok 3"))
    assert not judge(stream).reasons


def test_a_missing_identity_is_said_so():
    lines = report(verdict_of("TAP version 14\nok 1 - HR-4 a\n1..1\n"))
    assert lines[0] == "==> no image identity comment in the stream"
