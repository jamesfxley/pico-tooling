# SPDX-License-Identifier: MIT
"""The shared House tree profiles and the files sync renders for them (AR-2)."""

import json
import subprocess

import pytest

from pico_tooling import profiles

SEARCH = (
    "ignored\n#include <...> search starts here:\n /one\n /two/three\n"
    "End of search list.\nignored\n"
)


class Compiler:
    """Records the compiler invocations and answers with a fixed search list."""

    def __init__(self, stderr=SEARCH):
        self.calls = []
        self.stderr = stderr

    def __call__(self, command, **_options):
        self.calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", self.stderr)


def present(_name):
    return "/usr/bin/arm-none-eabi-g++"


def absent(_name):
    return None


def firmware(environ, compiler=None, which=present):
    return profiles.firmware_profile(environ, compiler or Compiler(), which)


def test_the_firmware_tree_is_off_without_an_sdk_and_never_runs_the_compiler():
    compiler = Compiler()
    tree = firmware({}, compiler)
    assert (tree.name, tree.enabled) == ("firmware", False)
    assert (tree.cmake_args, tree.env) == ((), {})
    assert compiler.calls == []
    assert firmware({"PICO_SDK_PATH": ""}, compiler).enabled is False


def test_the_firmware_tree_is_a_release_build_for_the_named_sdk_and_default_board():
    tree = firmware({"PICO_SDK_PATH": "/opt/sdk"})
    assert tree.enabled is True
    assert tree.cmake_args == (
        "-DCMAKE_BUILD_TYPE=Release", "-DPICO_SDK_PATH=/opt/sdk",
        "-DPICO_BOARD=pico2_w",
    )


@pytest.mark.parametrize(
    ("environ", "board"),
    [
        ({}, "pico2_w"),
        ({"PICO_BOARD": "pico_w"}, "pico_w"),
        ({"HOUSE_MATRIX_BOARD": "pico_w"}, "pico_w"),
        ({"HOUSE_MATRIX_BOARD": "pico_w", "PICO_BOARD": "pico2_w"}, "pico_w"),
        ({"HOUSE_MATRIX_BOARD": "", "PICO_BOARD": "pico_w"}, "pico_w"),
    ],
)
def test_the_board_comes_from_the_matrix_then_the_environment_then_the_default(
    environ, board,
):
    tree = firmware({"PICO_SDK_PATH": "/sdk", **environ})
    assert f"-DPICO_BOARD={board}" in tree.cmake_args


@pytest.mark.parametrize(
    ("board", "flags"),
    [
        ("pico", ["-mcpu=cortex-m0plus", "-mthumb"]),
        ("pico_w", ["-mcpu=cortex-m0plus", "-mthumb"]),
        ("pico2", ["-mcpu=cortex-m33", "-mthumb", "-march=armv8-m.main+fp+dsp"]),
        ("pico2_w", ["-mcpu=cortex-m33", "-mthumb", "-march=armv8-m.main+fp+dsp"]),
    ],
)
def test_clang_tidy_gets_the_system_includes_of_the_boards_multilib(board, flags):
    compiler = Compiler()
    tree = firmware({"PICO_SDK_PATH": "/sdk", "PICO_BOARD": board}, compiler)
    [command] = compiler.calls
    assert command[0] == "arm-none-eabi-g++"
    assert all(flag in command for flag in flags)
    assert json.loads(tree.env["HOUSE_CLANG_TIDY_ARGS"]) == [
        "--extra-arg=-isystem/one", "--extra-arg=-isystem/two/three",
    ]


@pytest.mark.parametrize(
    ("which", "stderr", "board"),
    [
        (absent, SEARCH, "pico2_w"),
        (present, "no search list here\n", "pico2_w"),
        (present, SEARCH, "unknown_board"),
    ],
)
def test_no_system_includes_when_they_cannot_be_read(which, stderr, board):
    compiler = Compiler(stderr)
    tree = firmware({"PICO_SDK_PATH": "/sdk", "PICO_BOARD": board}, compiler, which)
    assert tree.env == {"HOUSE_CLANG_TIDY_ARGS": "[]"}
    if board == "unknown_board":
        assert compiler.calls == []
