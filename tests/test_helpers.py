# SPDX-License-Identifier: MIT
"""Host-side refusals and records of the ported firmware helpers (AR-6).

Each case configures a tiny project that includes the family module directly.
A fake SDK stands in where a firmware configure is needed, so no real SDK or
toolchain is involved, and the ambient SDK environment is always scrubbed.
"""

import os
import shutil
import subprocess

import pytest

from tests.conftest import ROOT

MODULE = ROOT / "cmake/pico_family.cmake"
PROJECT = """\
cmake_minimum_required(VERSION 3.26)
include("{module}")
{before}
project(helper LANGUAGES CXX)
{after}
"""
SDK = """\
message(STATUS "fake SDK included for PICO_BOARD ${{PICO_BOARD}}")
set(PICO_PLATFORM "{platform}")
{radio}
macro(pico_sdk_init)
endmacro()
"""


def configure(tmp_path, before="", after="", *arguments, environment=None):
    """Configure a throwaway project; return (exit code, text with one-line spacing)."""
    source = tmp_path / "project"
    shutil.rmtree(source, ignore_errors=True)
    source.mkdir()
    (source / "core.cpp").write_text("int core() { return 0; }\n")
    (source / "CMakeLists.txt").write_text(
        PROJECT.format(module=MODULE.as_posix(), before=before, after=after),
    )
    scrubbed = {
        key: value for key, value in os.environ.items()
        if not key.startswith("PICO_")
    }
    done = subprocess.run(
        ["cmake", "-S", str(source), "-B", str(source / "build"), *arguments],
        capture_output=True, text=True, check=False,
        env={**scrubbed, **(environment or {})},
    )
    return done.returncode, " ".join((done.stdout + done.stderr).split()), source


def fake_sdk(tmp_path, *, platform="rp2350-arm-s", cyw43=True):
    sdk = tmp_path / "sdk"
    sdk.mkdir(exist_ok=True)
    (sdk / "pico_sdk_init.cmake").write_text(
        SDK.format(
            platform=platform, radio="set(PICO_CYW43_SUPPORTED 1)" if cyw43 else "",
        ),
    )
    return sdk


LIBRARY = """\
add_library(core STATIC core.cpp)
add_library(sdk_part INTERFACE)
"""


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (
            "core sdk_part",
            (
                "pico_family_sdk_link_libraries: unrecognised arguments "
                "'sdk_part'. Every library must be under PUBLIC or PRIVATE."
            ),
        ),
        ("core", "pico_family_sdk_link_libraries: no libraries given for core"),
    ],
)
def test_sdk_link_libraries_refuses_bad_arguments(tmp_path, call, expected):
    status, text, _ = configure(
        tmp_path, after=LIBRARY + f"pico_family_sdk_link_libraries({call})\n",
    )
    assert status != 0, text
    assert expected in text


def test_sdk_link_libraries_records_links_and_keeps_them_out_of_an_export(tmp_path):
    status, text, source = configure(
        tmp_path,
        after=LIBRARY + "pico_family_sdk_link_libraries(core PUBLIC sdk_part "
        "PRIVATE sdk_part)\n"
        "get_target_property(public core PICO_FAMILY_SDK_LINKS_PUBLIC)\n"
        "get_target_property(private core PICO_FAMILY_SDK_LINKS_PRIVATE)\n"
        'message(STATUS "recorded public=${public} private=${private}")\n'
        "export(TARGETS core FILE ${CMAKE_BINARY_DIR}/coreTargets.cmake)\n",
    )
    assert status == 0, text
    assert "recorded public=sdk_part private=sdk_part" in text
    exported = (source / "build/coreTargets.cmake").read_text()
    assert "sdk_part" not in exported


def test_a_plain_link_would_not_export_so_the_wrapper_matters(tmp_path):
    # Control for the previous test: without BUILD_LOCAL_INTERFACE, the export
    # of a target linking another unexported target is an error.
    status, text, _ = configure(
        tmp_path,
        after=LIBRARY + "target_link_libraries(core PUBLIC sdk_part)\n"
        "export(TARGETS core FILE ${CMAKE_BINARY_DIR}/coreTargets.cmake)\n",
    )
    assert status != 0, text
    assert "not in any export set" in text


def test_lwipopts_refusal_names_the_requirement_with_and_without_a_fallback(tmp_path):
    plain = "pico_family_require_lwipopts_target(mylib)\n"
    status, text, _ = configure(tmp_path, after=plain)
    assert status != 0, text
    assert (
        "mylib: PICO_LWIPOPTS_TARGET must name the target carrying your lwipopts.h"
        in text
    )
    assert "To build this repository standalone" not in text
    status, text, _ = configure(
        tmp_path,
        after="pico_family_require_lwipopts_target(mylib FALLBACK demo_opts)\n",
    )
    assert status != 0, text
    assert (
        "To build this repository standalone, pass -DPICO_LWIPOPTS_TARGET=demo_opts."
        in text
    )
    status, text, _ = configure(tmp_path, "", plain, "-DPICO_LWIPOPTS_TARGET=app_opts")
    assert status == 0, text
    status, text, _ = configure(
        tmp_path, after="pico_family_require_lwipopts_target(mylib BOGUS)\n",
    )
    assert status != 0, text
    assert (
        "pico_family_require_lwipopts_target(mylib): unrecognised arguments 'BOGUS'"
        in text
    )


def test_propagate_install_forces_dependency_install_only_when_the_library_installs(
    tmp_path,
):
    call = "pico_family_propagate_install(LIB UTIL LOGGING)\n"
    report = (
        'message(STATUS "util=[${UTIL_ENABLE_INSTALL}] '
        'logging=[${LOGGING_ENABLE_INSTALL}]")\n'
    )
    status, text, _ = configure(tmp_path, after=call + report)
    assert status == 0, text
    assert "util=[] logging=[]" in text
    status, text, _ = configure(
        tmp_path, "set(LIB_ENABLE_INSTALL ON)\n", call + report,
    )
    assert status == 0, text
    assert "util=[ON] logging=[ON]" in text
    status, text, _ = configure(
        tmp_path, "set(LIB_ENABLE_INSTALL ON)\n",
        "pico_family_propagate_install(LIB)\n",
    )
    assert status != 0, text
    assert "pico_family_propagate_install(LIB): no dependency prefixes given" in text


def firmware(tmp_path, call, *arguments, environment=None, **sdk):
    root = fake_sdk(tmp_path, **sdk)
    return configure(
        tmp_path, call, "", f"-DPICO_SDK_PATH={root}", *arguments,
        environment=environment,
    )


def test_the_bootstrap_refuses_unknown_and_valueless_arguments(tmp_path):
    status, text, _ = configure(tmp_path, "pico_family_bootstrap(APP BOGUS)\n")
    assert status != 0, text
    assert "pico_family_bootstrap: unrecognised arguments 'BOGUS'" in text
    status, text, _ = configure(tmp_path, "pico_family_bootstrap(APP PLATFORM)\n")
    assert status != 0, text
    assert "pico_family_bootstrap: no value given for 'PLATFORM'" in text


def test_the_platform_requirement_checks_the_selected_board(tmp_path):
    status, text, _ = firmware(
        tmp_path, "pico_family_bootstrap(APP PLATFORM rp2040)\n",
    )
    assert status != 0, text
    assert (
        "APP needs PICO_PLATFORM rp2040, and PICO_BOARD 'pico2_w' is rp2350-arm-s"
        in text
    )
    status, text, _ = firmware(
        tmp_path, "pico_family_bootstrap(APP PLATFORM rp2350)\n",
    )
    assert status == 0, text


def test_the_radio_requirement_checks_the_selected_board(tmp_path):
    status, text, _ = firmware(
        tmp_path, "pico_family_bootstrap(APP CYW43)\n", cyw43=False,
    )
    assert status != 0, text
    assert (
        "APP needs a board with the CYW43 radio, and PICO_BOARD 'pico2_w' has none"
        in text
    )
    status, text, _ = firmware(tmp_path, "pico_family_bootstrap(APP CYW43)\n")
    assert status == 0, text


def test_an_environment_board_is_refused_rather_than_replaced(tmp_path):
    call = "pico_family_bootstrap(APP)\n"
    status, text, _ = firmware(tmp_path, call, environment={"PICO_BOARD": "pico"})
    assert status != 0, text
    assert (
        "PICO_BOARD is 'pico' in the environment and unset as a CMake variable"
        in text
    )
    assert "Pass -DPICO_BOARD=<board> to choose." in text
    status, text, _ = firmware(
        tmp_path, call, "-DPICO_BOARD=pico_w", environment={"PICO_BOARD": "pico"},
    )
    assert status == 0, text


@pytest.mark.parametrize("board", ["pico", "pico2", "custom_rp2350b_board"])
def test_any_board_reaches_the_sdk_without_an_allow_list(tmp_path, board):
    status, text, _ = firmware(
        tmp_path, "pico_family_bootstrap(APP)\n", f"-DPICO_BOARD={board}",
    )
    assert status == 0, text
    assert f"fake SDK included for PICO_BOARD {board}" in text


def test_a_radio_free_board_meets_the_platform_and_refuses_the_radio(tmp_path):
    status, text, _ = firmware(
        tmp_path, "pico_family_bootstrap(APP PLATFORM rp2040)\n",
        "-DPICO_BOARD=pico", platform="rp2040", cyw43=False,
    )
    assert status == 0, text
    status, text, _ = firmware(
        tmp_path, "pico_family_bootstrap(APP CYW43)\n",
        "-DPICO_BOARD=pico", platform="rp2040", cyw43=False,
    )
    assert status != 0, text
    assert (
        "APP needs a board with the CYW43 radio, and PICO_BOARD 'pico' has none"
        in text
    )


def test_a_forced_firmware_configure_needs_a_real_sdk_path(tmp_path):
    status, text, _ = configure(
        tmp_path, "pico_family_bootstrap(APP)\n", "", "-DAPP_BUILD_FIRMWARE=ON",
    )
    assert status != 0, text
    assert "PICO_SDK_PATH must point to a valid Pico SDK checkout" in text
    status, text, _ = configure(
        tmp_path, "pico_family_bootstrap(APP)\n", "", "-DAPP_BUILD_FIRMWARE=ON",
        f"-DPICO_SDK_PATH={tmp_path / 'absent'}",
    )
    assert status != 0, text
    assert "Could not find pico_sdk_init.cmake in" in text


def test_the_context_selector_is_private_and_not_documented_as_an_entry_point(
    tmp_path,
):
    status, text, _ = configure(
        tmp_path,
        after=(
            "if(COMMAND pico_family_context)\n"
            '    message(FATAL_ERROR "the selector is public")\n'
            "endif()\n"
            "if(NOT COMMAND _pico_family_context)\n"
            '    message(FATAL_ERROR "the selector is missing")\n'
            "endif()\n"
        ),
    )
    assert status == 0, text
    guide = (ROOT / "docs/usage-guide.md").read_text(encoding="utf-8")
    assert "| `pico_family_context" not in guide
    assert "`_pico_family_context`" in guide


def test_a_second_include_does_not_redefine_the_helpers(tmp_path):
    # CMake keeps a redefined command's previous body as _<name>, so that name
    # appearing means the module ran twice. The control proves the probe works.
    spelled = (MODULE.parent / ".." / "cmake" / MODULE.name).as_posix()
    control = tmp_path / "twice.cmake"
    control.write_text("function(probe)\nendfunction()\n")
    status, text, _ = configure(
        tmp_path,
        before=(
            f'include("{control.as_posix()}")\n'
            f'include("{control.as_posix()}")\n'
            "if(NOT COMMAND _probe)\n"
            '    message(FATAL_ERROR "control: a redefinition leaves no trace")\n'
            "endif()\n"
            f'include("{spelled}")\n'
            f'include("{MODULE.as_posix()}")\n'
            "foreach(helper IN ITEMS _pico_family_context pico_family_dependency\n"
            "        pico_family_sdk_link_libraries pico_family_propagate_install\n"
            "        pico_family_bootstrap)\n"
            "    if(COMMAND _${helper})\n"
            '        message(FATAL_ERROR "${helper} was redefined")\n'
            "    endif()\n"
            "endforeach()\n"
        ),
    )
    assert status == 0, text


def test_the_family_requires_cmake_3_26_naming_the_reason(tmp_path):
    # CMake is not run at 3.24 here; the test sets CMAKE_VERSION to stand in
    # for it. BUILD_LOCAL_INTERFACE is "versionadded:: 3.26" in the CMake manual.
    status, text, _ = configure(
        tmp_path, "set(CMAKE_VERSION 3.24.0)\npico_family_bootstrap(APP)\n",
    )
    assert status != 0, text
    assert (
        "pico_family_bootstrap: the pico family needs CMake 3.26 or later, "
        "because $<BUILD_LOCAL_INTERFACE:> keeps SDK libraries out of an export; "
        "this is CMake 3.24.0" in text
    )
    status, text, _ = configure(
        tmp_path, "set(CMAKE_VERSION 3.26.0)\npico_family_bootstrap(APP)\n",
    )
    assert status == 0, text
