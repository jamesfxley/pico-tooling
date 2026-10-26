# SPDX-License-Identifier: MIT
"""Whole-build sizing profiles are declared once and refuse unknown values (AR-6)."""

import shutil
import subprocess

import pytest

from tests.test_helpers import MODULE, PROJECT, configure

DECLARE = (
    "pico_family_declare_profile(PICO_EN NAME PROFILE DEFAULT default "
    "VALUES default large)\n"
)
MEDIUM = (
    "pico_family_declare_profile(PICO_EN NAME PROFILE DEFAULT default "
    "VALUES default medium)\n"
)
LARGE_DEFAULT = (
    "pico_family_declare_profile(PICO_EN NAME PROFILE DEFAULT large "
    "VALUES default large)\n"
)
REPORT = 'message(STATUS "profile=${PICO_EN_PROFILE}")\n'


def test_a_profile_defaults_and_accepts_each_listed_value(tmp_path):
    status, text, _ = configure(tmp_path, after=DECLARE + REPORT)
    assert status == 0, text
    assert "profile=default" in text
    status, text, _ = configure(
        tmp_path, "", DECLARE + REPORT, "-DPICO_EN_PROFILE=large",
    )
    assert status == 0, text
    assert "profile=large" in text


@pytest.mark.parametrize("value", ["enormous", "", "has space"])
def test_an_unlisted_profile_value_is_refused_naming_the_set(tmp_path, value):
    status, text, _ = configure(
        tmp_path, "", DECLARE, f"-DPICO_EN_PROFILE={value}",
    )
    assert status != 0, text
    assert f"PICO_EN_PROFILE must be one of default, large; got '{value}'" in text


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        ("pico_family_declare_profile(PICO_EN NAME PROFILE DEFAULT default)",
         "NAME, DEFAULT and VALUES are all required"),
        ("pico_family_declare_profile(PICO_EN NAME PROFILE DEFAULT x VALUES a b)",
         "DEFAULT 'x' is not one of VALUES"),
        ("pico_family_declare_profile(PICO_EN NAME PROFILE BOGUS DEFAULT a VALUES a)",
         "unrecognised arguments 'BOGUS'"),
    ],
)
def test_a_malformed_profile_declaration_is_refused(tmp_path, call, expected):
    status, text, _ = configure(tmp_path, after=call + "\n")
    assert status != 0, text
    assert expected in text


def two_libraries(tmp_path, second):
    """Configure a parent whose subdirectory declares the same profile again."""
    source = tmp_path / "two"
    shutil.rmtree(source, ignore_errors=True)
    (source / "other").mkdir(parents=True)
    (source / "CMakeLists.txt").write_text(
        PROJECT.format(
            module=MODULE.as_posix(), before="",
            after=DECLARE + "add_subdirectory(other)\n",
        ),
    )
    (source / "core.cpp").write_text("int core() { return 0; }\n")
    (source / "other/CMakeLists.txt").write_text(second)
    done = subprocess.run(
        ["cmake", "-S", str(source), "-B", str(source / "build")],
        capture_output=True, text=True, check=False,
    )
    return done.returncode, " ".join((done.stdout + done.stderr).split())


@pytest.mark.parametrize(
    ("second", "agrees"),
    [(DECLARE, True), (MEDIUM, False), (LARGE_DEFAULT, False)],
)
def test_a_second_declaration_must_agree_with_the_first(tmp_path, second, agrees):
    status, text = two_libraries(tmp_path, second)
    if agrees:
        assert status == 0, text
        return
    assert status != 0, text
    assert "PICO_EN_PROFILE is declared twice with different defaults or values" in text
    assert "by " in text
    assert "/two/other" in text
    assert "One build has one meaning for it" in text
