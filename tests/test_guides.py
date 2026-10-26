# SPDX-License-Identifier: MIT
"""The family guides are tool-neutral, mark what is unconfirmed, match the tools.

The guides and procedures routed from every library's instruction file name no
agent tool, link only to files that exist, and describe commands and exit
statuses the code has.
"""

import re
import sys
from pathlib import Path

import pytest

from pico_tooling import device_errors
from pico_tooling.embedded import SYMBOL_SETS
from tests.conftest import ROOT, run

DOCUMENTS = [
    "guides/device.md",
    "guides/constrained-targets/SKILL.md",
    "docs/build.md",
    "docs/new-library.md",
]
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
# Flags of other programs the device guide quotes: picotool's own.
PICOTOOL_FLAGS = {"--ser", "--verify", "--execute", "--force", "--usb"}


@pytest.mark.parametrize("name", DOCUMENTS)
def test_every_relative_link_resolves(name):
    path = ROOT / name
    links = [
        link
        for link in LINK.findall(path.read_text(encoding="utf-8"))
        if "://" not in link
    ]
    for link in links:
        assert (path.parent / link).resolve().exists(), f"{name}: {link}"


@pytest.mark.parametrize("name", DOCUMENTS[:1])
def test_the_device_guide_marks_hardware_claims_it_cannot_support(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    section = text.split("## UNCONFIRMED", 1)[1]
    for needed in ("datasheets", "Microsoft", "UF2 specification"):
        assert needed in section


def test_every_flag_the_device_guide_names_exists():
    flags = set()
    for action in ("list", "bootsel", "flash", "console"):
        helped = run(
            sys.executable,
            "-m",
            "pico_tooling",
            "device",
            action,
            "--help",
            cwd=ROOT,
        ).stdout
        flags.update(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", helped))
    named = set(
        re.findall(
            r"(?<![\w-])(--[a-z][a-z-]*)",
            (ROOT / "guides/device.md").read_text(encoding="utf-8"),
        ),
    )
    assert named - PICOTOOL_FLAGS <= flags, named - PICOTOOL_FLAGS - flags
    assert {
        "--serial",
        "--dry-run",
        "--no-touch",
        "--port",
        "--build-dir",
        "--json",
        "--console",
        "--until",
        "--timeout",
        "--log",
    } <= named


def test_the_exit_status_table_lists_every_status_the_commands_return():
    table = (
        (ROOT / "guides/device.md")
        .read_text(encoding="utf-8")
        .split(
            "## Exit statuses",
            1,
        )[1]
        .split("##", 1)[0]
    )
    for status in (
        device_errors.OK,
        device_errors.FAILED,
        device_errors.CANNOT_TRY,
        device_errors.AMBIGUOUS,
        device_errors.INTERRUPTED,
        device_errors.TERMINATED,
    ):
        assert re.search(rf"(?:\| |/ ){status}\b", table), status


def test_the_constrained_targets_guide_names_the_sets_the_gate_has():
    text = (ROOT / "guides/constrained-targets/SKILL.md").read_text(encoding="utf-8")
    assert all(f"`{name}`" in text for name in SYMBOL_SETS)
    front = text.split("---", 2)[1]
    assert re.search(r"^name: constrained-targets$", front, re.MULTILINE)
    assert Path(ROOT / "house/standard/cxx/11-constrained-targets.md").is_file()
