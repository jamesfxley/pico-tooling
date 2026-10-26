# SPDX-License-Identifier: MIT
"""The family firmware tree (AR-2).

The family reference imports the firmware attribute directly from its pin. House
reads a profile's name, enabled flag, CMake arguments and environment.
"""

import json
import os
import re
import shutil
import subprocess
from types import SimpleNamespace

DEFAULT_BOARD = "pico2_w"
COMPILER = "arm-none-eabi-g++"
# The compiler flags the Pico SDK 2.3.0 gives each supported board's platform:
# rp2040 uses cmake/preload/toolchains/pico_arm_cortex_m0plus_gcc.cmake line 5,
# rp2350 uses pico_arm_cortex_m33_gcc.cmake line 4. clang-tidy needs the system
# include directories of the multilib those flags select.
BOARD_FLAGS = {
    "pico_w": ("-mcpu=cortex-m0plus", "-mthumb"),
    "pico2_w": ("-mcpu=cortex-m33", "-mthumb", "-march=armv8-m.main+fp+dsp"),
}
SEARCH_LIST = re.compile(
    r"#include <\.\.\.> search starts here:\n(.*?)\nEnd of search list",
    re.DOTALL,
)


def system_includes(board, run=subprocess.run, which=shutil.which):
    """Return clang-tidy arguments naming the cross compiler's system includes.

    Returns nothing for a board with no recorded flags or an absent compiler;
    the configure step then reports the board or the toolchain.
    """
    flags = BOARD_FLAGS.get(board)
    if flags is None or which(COMPILER) is None:
        return []
    said = run(
        [COMPILER, "-std=c++20", *flags, "-x", "c++", "-E", "-v", "-"],
        input="", capture_output=True, text=True, check=False,
    ).stderr
    found = SEARCH_LIST.search(said)
    if found is None:
        return []
    return [f"--extra-arg=-isystem{line.strip()}" for line in found[1].splitlines()]


def firmware_profile(environ=None, run=subprocess.run, which=shutil.which):
    """Return the cross tree, enabled only when an SDK is named.

    The board comes from HOUSE_MATRIX_BOARD, else PICO_BOARD, else pico2_w.
    """
    environ = os.environ if environ is None else environ
    sdk = environ.get("PICO_SDK_PATH", "")
    board = (
        environ.get("HOUSE_MATRIX_BOARD") or environ.get("PICO_BOARD") or DEFAULT_BOARD
    )
    if not sdk:
        return SimpleNamespace(
            name="firmware", enabled=False, cmake_args=(), env={}, sync_overlay={},
        )
    return SimpleNamespace(
        name="firmware",
        enabled=True,
        cmake_args=(
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DPICO_SDK_PATH={sdk}",
            f"-DPICO_BOARD={board}",
        ),
        env={"HOUSE_CLANG_TIDY_ARGS": json.dumps(system_includes(board, run, which))},
        sync_overlay={},
    )

firmware = firmware_profile()
