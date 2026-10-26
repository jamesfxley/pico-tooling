# SPDX-License-Identifier: MIT
"""SDK package snippets preserve bytes and restore consumer links (AR-6)."""

import os
import subprocess

import pytest

from tests.test_cmake import real_sdk
from tests.test_helpers import LIBRARY, MODULE, configure

EXPECTED = """
# Pico SDK libraries. Not exportable, so re-applied here; see
# pico_family_sdk_link_libraries in pico-tooling.
if(NOT TARGET sdk_part)
    message(FATAL_ERROR
        "helper: no target 'sdk_part'. This package "
        "links the Pico SDK, so the SDK must be initialised before "
        "find_package(helper): include pico_sdk_import.cmake and "
        "call pico_sdk_init() first.")
endif()
set_property(TARGET helper::core APPEND PROPERTY
    INTERFACE_LINK_LIBRARIES sdk_part)
set_property(TARGET helper::core APPEND PROPERTY
    INTERFACE_LINK_LIBRARIES $<LINK_ONLY:sdk_part>)
"""


@pytest.mark.parametrize("linked", [True, False])
def test_sdk_snippet_matches_the_baseline_block(tmp_path, linked):
    call = (
        "pico_family_sdk_link_libraries(helper_core PUBLIC sdk_part PRIVATE sdk_part)\n"
        if linked else ""
    )
    status, text, source = configure(
        tmp_path,
        after=LIBRARY.replace("core STATIC", "helper_core STATIC") + call + (
            "pico_family_sdk_config_snippet(snippet TARGETS helper_core)\n"
            'file(READ "${snippet}" block)\n'
            'file(WRITE "${CMAKE_BINARY_DIR}/observed" "${block}")\n'
        ),
    )
    assert status == 0, text
    assert (source / "build/observed").read_text() == (EXPECTED if linked else "")


def run(*args, cwd):
    done = subprocess.run(
        [str(arg) for arg in args], cwd=cwd, capture_output=True, text=True,
        check=False, env={**os.environ, "GIT_ALLOW_PROTOCOL": "file"},
    )
    assert done.returncode == 0, done.stdout[-6000:] + done.stderr[-6000:]
    assert "warning:" not in (done.stdout + done.stderr).lower()
    return done


@pytest.mark.real_sdk
def test_real_sdk_package_restores_the_installed_interface(tmp_path):
    sdk = real_sdk()
    producer = tmp_path / "producer"
    producer.mkdir()
    (producer / "core.cpp").write_text(
        '#include "pico/time.h"\nint core() { return time_us_64() != 0; }\n',
    )
    (producer / "CMakeLists.txt").write_text(
        f"""cmake_minimum_required(VERSION 3.26)
include("{sdk}/external/pico_sdk_import.cmake")
project(sample VERSION 1.0.0 LANGUAGES C CXX ASM)
pico_sdk_init()
include("{MODULE}")
add_library(sample_core STATIC core.cpp)
pico_family_sdk_link_libraries(sample_core PUBLIC pico_stdlib)
pico_family_sdk_config_snippet(snippet TARGETS sample_core)
house_cxx_install_package(PACKAGE sample VERSION 1.0.0 NAMESPACE sample
    TARGETS sample_core CONFIG_SNIPPET "${{snippet}}")
""",
    )
    prefix = tmp_path / "prefix"
    run(
        "cmake", "-S", producer, "-B", producer / "build", "-G", "Ninja",
        f"-DPICO_SDK_PATH={sdk}", "-DPICO_BOARD=pico2_w",
        f"-DCMAKE_INSTALL_PREFIX={prefix}", cwd=tmp_path,
    )
    run("cmake", "--build", producer / "build", "--target", "install", cwd=tmp_path)
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "main.cpp").write_text("int core();\nint main() { return core(); }\n")
    (consumer / "CMakeLists.txt").write_text(
        f"""cmake_minimum_required(VERSION 3.26)
include("{sdk}/external/pico_sdk_import.cmake")
project(consumer LANGUAGES C CXX ASM)
pico_sdk_init()
find_package(sample CONFIG REQUIRED)
add_executable(app main.cpp)
target_link_libraries(app PRIVATE sample::core)
""",
    )
    run(
        "cmake", "-S", consumer, "-B", consumer / "build", "-G", "Ninja",
        f"-DPICO_SDK_PATH={sdk}", "-DPICO_BOARD=pico2_w",
        f"-Dsample_DIR={prefix}/lib/cmake/sample", cwd=tmp_path,
    )
    run("cmake", "--build", consumer / "build", cwd=tmp_path)
    assert (consumer / "build/app.elf").is_file()
