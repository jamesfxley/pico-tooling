# SPDX-License-Identifier: MIT
"""Judge the TAP 14 subset a device-test image emits; nothing here touches a board.

Pure functions over decoded text (AR-16). The subset is `TAP version 14`, test
points `ok|not ok <n> - <requirement ID> <case-name>`, comments, `Bail out!`
and a plan that comes last. Any other line is passed over, never a failure.
"""

import re
from dataclasses import dataclass, field

VERSION = re.compile(r"TAP version 14\s*$")
PLAN = re.compile(r"1\.\.(\d+)\s*(#.*)?$")
BAIL = re.compile(r"bail out!", re.IGNORECASE)
POINT = re.compile(r"(not ok|ok)(?=\s|$)(?:\s+(\d+))?(?:\s+-)?\s*(.*)$")
DIRECTIVE = re.compile(r"\s#\s*(skip|todo)\b", re.IGNORECASE)
COMMENT = re.compile(r"\s*#\s?(.*)$")
IDENTITY = re.compile(r"image\s.*")
COMMIT = re.compile(r"(?:^|\s)commit=(\S*)")
PLAIN_COMMIT = re.compile(r"[0-9a-f]+")
YAML_START = re.compile(r"\s+---\s*$")
NO_REQUIREMENT = "(none)"


def lines_of(text):
    """Return the complete lines of `text`, with CRLF and CR read as LF."""
    return re.sub(r"\r\n?", "\n", text).split("\n")[:-1]


def first_stream(text):
    """Return the first complete stream in `text`, or None.

    A stream is a version line followed by a plan or a `Bail out!` line. A plan
    with no version line before it joins a stream midway and is skipped; a
    second version line abandons the stream before it, which never finished.
    """
    started = None
    for index, line in enumerate(lines_of(text)):
        if VERSION.match(line):
            started = index
        elif started is not None and (PLAN.match(line) or BAIL.match(line)):
            return lines_of(text)[started : index + 1]
    return None


@dataclass
class Verdict:
    """What a complete stream says."""

    identity: str | None = None
    planned: int | None = None
    bail: str | None = None
    numbers: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)  # requirement -> [passed, failed]
    failed: list = field(default_factory=list)  # [point line, comments]
    reasons: list = field(default_factory=list)


def judge(stream):
    """Return the Verdict of one complete stream."""
    verdict = Verdict()
    detail = None
    for line in stream[1:]:
        point = POINT.match(line)
        comment = COMMENT.match(line)
        plan = PLAN.match(line)
        if BAIL.match(line):
            verdict.bail = line[len("bail out!") :].strip()
        elif plan:
            verdict.planned = int(plan.group(1))
        elif point:
            detail = take_point(verdict, line, point)
        elif comment:
            if verdict.identity is None and IDENTITY.match(comment.group(1)):
                verdict.identity = comment.group(1)
            elif detail is not None:
                detail.append(comment.group(1))
        elif YAML_START.match(line):
            verdict.reasons.append("a YAML block is outside the subset")
    finish(verdict)
    return verdict


def take_point(verdict, line, point):
    """Record one test point; return its comment list when it failed, else None."""
    status, number, description = point.groups()
    number = int(number) if number else len(verdict.numbers) + 1
    verdict.numbers.append(number)
    words = description.split(maxsplit=1)
    requirement = words[0] if words else NO_REQUIREMENT
    counts = verdict.counts.setdefault(requirement, [0, 0])
    directive = DIRECTIVE.search(line)
    if directive:
        verdict.reasons.append(
            f"test point {number} has a {directive.group(1).upper()} directive, "
            "which the subset does not have",
        )
    if status == "ok" and not directive:
        counts[0] += 1
        return None
    counts[1] += 1
    detail = []
    verdict.failed.append([line.strip(), detail])
    return detail


def names_a_commit(identity):
    """Whether the identity comment names a plain commit: not -dirty, not unknown."""
    found = COMMIT.search(identity or "")
    return found is not None and PLAIN_COMMIT.fullmatch(found.group(1)) is not None


def finish(verdict):
    """Add the reasons a stream fails that no single line carries."""
    if verdict.bail is not None:
        verdict.reasons.insert(0, f"Bail out! {verdict.bail}".rstrip())
    elif verdict.planned == 0:
        verdict.reasons.append("the plan is 1..0, so no case ran")
    elif verdict.planned != len(verdict.numbers):
        verdict.reasons.append(
            f"the plan is 1..{verdict.planned} but {len(verdict.numbers)} test "
            "points ran",
        )
    elif verdict.numbers != list(range(1, verdict.planned + 1)):
        verdict.reasons.append("the test point numbers are not 1..N, each once")
    if not names_a_commit(verdict.identity):
        found = COMMIT.search(verdict.identity or "")
        shown = f"commit={found.group(1)}" if found else "no commit in the identity"
        verdict.reasons.append(f"the image's source is not a commit ({shown})")
    failed = sum(failed for _, failed in verdict.counts.values())
    if failed:
        verdict.reasons.insert(
            0, f"{failed} test point{'s' * (failed != 1)} not ok",
        )


def report(verdict):
    """Return the verdict's lines for standard error, the last one the result."""
    out = [
        f"==> {verdict.identity}"
        if verdict.identity
        else "==> no image identity comment in the stream",
    ]
    out.extend(
        f"==> {requirement}: {passed} passed, {failed} failed"
        for requirement, (passed, failed) in verdict.counts.items()
    )
    for point, comments in verdict.failed:
        out.append(f"==> {point}")
        out.extend(f"==>     {comment}" for comment in comments)
    if verdict.reasons:
        out.append(f"==> device test: FAIL: {'; '.join(verdict.reasons)}")
    else:
        out.append("==> device test: PASS")
    return out
