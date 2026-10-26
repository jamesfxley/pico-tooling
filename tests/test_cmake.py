# SPDX-License-Identifier: MIT
"""Configure real synthetic libraries through one family context (AR-6)."""

import os
import re
import shutil
from pathlib import Path

import pytest

from tests.conftest import (
    ROOT,
    STANDARD_URL,
    commit,
    family,
    git,
    make_house_source,
    make_infra_source,
    run,
    scaffold,
)

PRODUCT = """\
cmake_minimum_required(VERSION 3.26)
include(cmake/pico_family_bootstrap.cmake)
pico_family_bootstrap({prefix})
project({name} VERSION {version} LANGUAGES NONE)
pico_family_init_sdk(${{{prefix}_BUILD_FIRMWARE}})
{dependencies}
set_property(GLOBAL APPEND PROPERTY PICO_TEST_POPULATED {name})
add_library({name} INTERFACE)
"""
APPLICATION = PRODUCT.replace(
    "add_library({name} INTERFACE)\n",
    """get_property(imports GLOBAL PROPERTY FAKE_SDK_IMPORTS)
get_property(inits GLOBAL PROPERTY FAKE_SDK_INITS)
get_property(populated GLOBAL PROPERTY PICO_TEST_POPULATED)
list(LENGTH imports imports)
list(LENGTH inits inits)
message(STATUS "summary imports=${{imports}} inits=${{inits}} "
    "populated=${{populated}} firmware=${{{prefix}_BUILD_FIRMWARE}}")
""",
)
PLAIN_PARENT = """\
cmake_minimum_required(VERSION 3.26)
project(plain LANGUAGES NONE)
include(FetchContent)
FetchContent_Declare(alpha GIT_REPOSITORY "{alpha}" GIT_TAG {head}
    GIT_SUBMODULES "")
FetchContent_MakeAvailable(alpha)
"""
# Local fixtures pin file paths and serve the standard's published URL from the
# local checkout; published pins are https and need neither.
FILE_ALLOWANCE = {
    "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_KEY_0": "protocol.file.allow",
    "GIT_CONFIG_VALUE_0": "always",
    "GIT_CONFIG_KEY_1": f"url.{ROOT / 'house/standard'}.insteadOf",
    "GIT_CONFIG_VALUE_1": STANDARD_URL,
}
LIBRARY = """\
cmake_minimum_required(VERSION 3.26)
include(cmake/pico_family_bootstrap.cmake)
pico_family_bootstrap({prefix})
project({name} VERSION {version} LANGUAGES CXX)
pico_family_init_sdk(${{{prefix}_BUILD_FIRMWARE}})
house_cxx_common_settings(OFF)
add_library({name}_core STATIC src/core.cpp)
add_library({name}::core ALIAS {name}_core)
target_sources({name}_core PUBLIC FILE_SET HEADERS BASE_DIRS include
    FILES include/{name}/core.hpp)
target_include_directories({name}_core PUBLIC
    $<BUILD_INTERFACE:${{CMAKE_CURRENT_SOURCE_DIR}}/include>
    $<INSTALL_INTERFACE:${{CMAKE_INSTALL_INCLUDEDIR}}>)
house_cxx_install_package(PACKAGE {name} VERSION ${{PROJECT_VERSION}}
    NAMESPACE {name} TARGETS {name}_core)
"""
PROBE = """\
cmake_minimum_required(VERSION 3.26)
include(cmake/pico_family_bootstrap.cmake)
pico_family_bootstrap({prefix})
project({name} VERSION {version} LANGUAGES C CXX ASM)
pico_family_init_sdk(${{{prefix}_BUILD_FIRMWARE}})
house_cxx_common_settings(OFF)
house_cxx_add_strict_target({name}_strict LANGUAGES CXX)
add_library({name}_headers INTERFACE)
pico_family_declare_probe_option({prefix})
if({prefix}_ENABLE_FIRMWARE_PROBE)
    pico_family_add_cross_probe({name}_probe PACKAGE {name} SOURCE probe.cpp
        LIBRARIES {name}_headers)
endif()
message(STATUS
    "probe={prefix}_ENABLE_FIRMWARE_PROBE=${{{prefix}_ENABLE_FIRMWARE_PROBE}}")
"""
CONSUMER = """\
cmake_minimum_required(VERSION 3.26)
project(consumer LANGUAGES CXX)
find_package(alpha {alpha} CONFIG REQUIRED)
find_package(beta {beta} CONFIG REQUIRED)
add_executable(consumer main.cpp)
target_link_libraries(consumer PRIVATE alpha::core beta::core)
"""
NEW_HELPER = """
function(pico_family_new_helper)
    message(STATUS "new helper ran")
endfunction()
"""
# A product that calls a helper which only a version 0.1.1 context provides.
CALLER = PRODUCT.replace("project(", "pico_family_new_helper()\nproject(")
FAKE_SDK = """\
set_property(GLOBAL APPEND PROPERTY FAKE_SDK_IMPORTS imported)
set(PICO_PLATFORM "rp2350-arm-s")
set(PICO_CYW43_SUPPORTED 1)
macro(pico_sdk_init)
    set_property(GLOBAL APPEND PROPERTY FAKE_SDK_INITS initialized)
endmacro()
"""


def advance(infra_source, branch, summary, *, version=None, addition=""):
    # Side branches keep the default branch, which scaffolds pin, at v0.1.0.
    git(infra_source, "checkout", "--quiet", "-b", branch, "main")
    if version:
        target = infra_source / "pyproject.toml"
        target.write_text(target.read_text().replace('version = "0.1.0"',
                                                   f'version = "{version}"'))
        target = infra_source / "cmake/pico_family.cmake"
        target.write_text(target.read_text() + addition)
    else:
        (infra_source / "CHANGELOG.md").write_text(f"# {summary}\n")
    revision = commit(infra_source, summary)
    git(infra_source, "checkout", "--quiet", "main")
    return revision


def product(root, infra_source, name, layout=None, **dependencies):
    """Scaffold a synthetic product; layout may set template, version and infra."""
    layout = {"template": PRODUCT, "version": "1.0.0", "infra": None, **(layout or {})}
    infra = layout["infra"]
    scaffold(infra_source, root, name=name.replace("_", "-"))
    if infra:
        git(root / "infra", "fetch", "--quiet", str(infra_source), infra)
        git(root / "infra", "checkout", "--quiet", infra)
        git(root, "add", "infra")
    declarations = "".join(
        f'pico_family_dependency({key} REPOSITORY "{location}" REVISION {revision})\n'
        for key, (location, revision) in dependencies.items()
    )
    if dependencies:
        declarations += f"pico_family_make_available({' '.join(dependencies)})\n"
    (root / "CMakeLists.txt").write_text(
        layout["template"].format(
            prefix=name.upper(), name=name, version=layout["version"],
            dependencies=declarations,
        ),
    )
    done = family(root, "sync")
    assert done.returncode == 0, done.stderr
    return root, commit(root, "tooling: add the synthetic product")


@pytest.fixture(scope="module")
def repos(tmp_path_factory):
    base = tmp_path_factory.mktemp("family")
    infra = make_infra_source(base / "infra", make_house_source(base / "house"))
    same_version = advance(infra, "compatible", "docs: note a compatible release")
    incompatible_version = advance(
        infra, "incompatible", "tooling: start version 0.2.0", version="0.2.0",
    )
    # A later patch that adds a helper (probe E of the planner review).
    patch_version = advance(
        infra, "minor", "tooling: start version 0.1.1", version="0.1.1",
        addition=NEW_HELPER,
    )
    # An equal release and an incompatible major.
    equal_version = same_version
    major_version = advance(
        infra, "major", "tooling: start version 1.0.0", version="1.0.0",
    )
    util, first = product(base / "util", infra, "util")
    (util / "NOTES.md").write_text("# Later util\n")
    second = commit(util, "docs: add notes")
    alpha, alpha_head = product(
        base / "alpha", infra, "alpha", {"version": "1.2.0"}, util=(util, first),
    )
    beta, beta_head = product(
        base / "beta", infra, "beta", {"version": "3.4.0"}, util=(util, first),
    )
    newer, newer_head = product(
        base / "newer", infra, "newer", {"infra": same_version},
        util=(util, second),
    )
    future, future_head = product(
        base / "future", infra, "future", {"infra": incompatible_version},
    )
    caller, caller_head = product(
        base / "caller", infra, "caller",
        {"infra": patch_version, "template": CALLER},
    )
    older, older_head = product(
        base / "older", infra, "older", {"infra": equal_version},
    )
    major, major_head = product(
        base / "major", infra, "major", {"infra": major_version},
    )
    sdk = base / "fake sdk"
    sdk.mkdir()
    (sdk / "pico_sdk_init.cmake").write_text(FAKE_SDK)
    return {
        "base": base, "infra": infra, "util": (util, first, second),
        "alpha": (alpha, alpha_head), "beta": (beta, beta_head),
        "newer": (newer, newer_head), "future": (future, future_head), "sdk": sdk,
        "same_version": same_version, "patch_version": patch_version,
        "caller": (caller, caller_head), "older": (older, older_head),
        "major": (major, major_head), "equal_version": equal_version,
    }


def application(repos, name, **dependencies):
    root = repos["base"] / name
    if not root.exists():
        product(root, repos["infra"], "app", {"template": APPLICATION}, **dependencies)
    return root


def configure(root, *arguments, env=None):
    build = root / "build"
    shutil.rmtree(build, ignore_errors=True)
    return run("cmake", "-S", root, "-B", build, *arguments, cwd=root,
               check=False, env=env)


def summary(done):
    match = re.search(r"summary (.*)", done.stdout)
    assert match, done.stdout + done.stderr
    return match.group(1)


# The real SDK comes from this variable only. An ambient PICO_SDK_PATH must never
# select it: the host tests prove that variable is ignored.
SDK_VARIABLE = "PICO_FAMILY_TEST_SDK"


def real_sdk():
    named = os.environ.get(SDK_VARIABLE)
    if not named:
        pytest.skip(f"{SDK_VARIABLE} names no Pico SDK checkout")
    if not (Path(named) / "pico_sdk_init.cmake").is_file():
        pytest.skip(f"{SDK_VARIABLE}={named} holds no pico_sdk_init.cmake")
    if shutil.which("arm-none-eabi-gcc") is None:
        pytest.skip("arm-none-eabi-gcc is not on PATH")
    return Path(named)


@pytest.mark.parametrize(("first", "second"), [("alpha", "beta"), ("beta", "alpha")])
def test_both_orders_share_one_context_and_one_dependency(repos, first, second):
    root = application(
        repos, f"app-{first}-{second}", lib1=repos[first], lib2=repos[second],
    )
    done = configure(root)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("pico family: context ") == 1
    populated = summary(done).split("populated=")[1].split()[0].split(";")
    assert populated.count("util") == 1
    assert {"alpha", "beta", "util"} <= set(populated)
    assert "firmware=OFF" in summary(done)


def test_firmware_imports_and_initializes_the_sdk_once(repos):
    root = application(repos, "app-firmware", lib1=repos["alpha"], lib2=repos["beta"])
    done = configure(root, f"-DPICO_SDK_PATH={repos['sdk']}")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "imports=1 inits=1" in summary(done)
    assert "firmware=ON" in summary(done)


def test_environment_sdk_path_keeps_a_portable_host_configure(repos):
    root = application(repos, "app-host", lib1=repos["alpha"])
    done = configure(root, env={"PICO_SDK_PATH": str(repos["sdk"])})
    assert done.returncode == 0, done.stdout + done.stderr
    assert "imports=0 inits=0" in summary(done)
    assert "firmware=OFF" in summary(done)


def test_a_different_release_line_is_fatal(repos):
    root = application(repos, "app-incompatible", lib1=repos["future"])
    done = configure(root)
    assert done.returncode != 0
    # CMake wraps long diagnostics; compare the words, not the line breaks.
    text = " ".join((done.stdout + done.stderr).split())
    assert "pins version 0.2.0" in text
    assert "this build selected version 0.1.0" in text


def test_a_requester_of_the_next_major_is_fatal_with_both_versions(repos):
    root = application(repos, "app-major", lib1=repos["major"])
    done = configure(root)
    text = " ".join((done.stdout + done.stderr).split())
    assert done.returncode != 0, text
    assert "pins version 1.0.0" in text
    assert "but this build selected version 0.1.0" in text
    assert "Align the infra pins or supply a compatible context from the parent" in text


def test_a_requester_of_the_equal_version_reuses_the_current_context(repos):
    root = application(repos, "app-older", lib1=repos["older"])
    done = configure(root)
    text = " ".join((done.stdout + done.stderr).split())
    assert done.returncode == 0, text
    assert done.stdout.count("pico family: context ") == 1
    assert "(version 0.1.0)" in done.stdout
    assert "reusing selected context" in done.stdout


def test_a_compatible_newer_pin_reuses_the_context_and_reports_conflicts(repos):
    root = application(repos, "app-newer", lib1=repos["alpha"], lib2=repos["newer"])
    done = configure(root)
    assert done.returncode == 0, done.stdout + done.stderr
    text = done.stdout
    assert f"pins {repos['same_version']}; reusing selected context" in text
    _, first, second = repos["util"]
    assert (
        f"util selected {first} from alpha; newer pins {second}, which is not used"
        in text
    )


def test_the_parents_own_pin_wins_over_its_dependencies(repos):
    util, first, second = repos["util"]
    root = application(
        repos, "app-parent", lib1=repos["alpha"], util=(util, second),
    )
    done = configure(root)
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"util pinned {second} by app" in done.stdout
    assert f"util selected {second} from app; alpha pins {first}" in done.stdout


def test_overrides_are_reported_and_siblings_ignored(repos):
    util, first, _ = repos["util"]
    root = application(repos, "app-override", lib1=repos["alpha"])
    sibling = repos["base"] / "util-sibling"
    sibling.mkdir(exist_ok=True)
    (sibling / "CMakeLists.txt").write_text('message(FATAL_ERROR "sibling used")\n')
    done = configure(root)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "sibling used" not in done.stdout + done.stderr
    assert f"util pinned {first} by alpha" in done.stdout
    working = repos["base"] / "util-working"
    if not working.exists():
        git(repos["base"], "clone", "--quiet", str(util), str(working))
    (working / "NOTES.md").write_text("# Uncommitted\n")
    done = configure(root, f"-DFETCHCONTENT_SOURCE_DIR_UTIL={working}")
    assert done.returncode == 0, done.stdout + done.stderr
    head = git(working, "rev-parse", "HEAD")
    assert (
        f"util override {working} at {head} with uncommitted changes; alpha pins "
        f"{first}" in done.stdout
    )


def test_a_firmware_dependency_requires_the_parent_to_import_the_sdk(repos):
    root = application(repos, "app-no-sdk", lib1=repos["alpha"])
    done = configure(
        root, f"-DPICO_SDK_PATH={repos['sdk']}", "-DAPP_BUILD_FIRMWARE=OFF",
    )
    assert done.returncode != 0
    text = " ".join((done.stdout + done.stderr).split())
    assert "ALPHA is a dependency here, so the top-level project must import" in text


def test_a_plain_parent_fetches_the_pinned_chain_once(repos):
    alpha, head = repos["alpha"]
    root = repos["base"] / "plain-parent"
    root.mkdir(exist_ok=True)
    (root / "CMakeLists.txt").write_text(PLAIN_PARENT.format(alpha=alpha, head=head))
    done = configure(root, env=FILE_ALLOWANCE)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("pico family: context ") == 1
    assert "_deps/pico_tooling-src" in done.stdout
    deps = root / "build/_deps"
    copies = list(deps.rglob("house/cxx/cmake/house.cmake"))
    assert len(copies) == 1, copies
    assert not (deps / "alpha-src/infra/cmake").exists()


def context_line(done):
    assert done.returncode == 0, done.stdout + done.stderr
    lines = [row for row in done.stdout.splitlines() if "pico family: context " in row]
    assert len(lines) == 1, done.stdout
    return " ".join(lines[0].split())


def test_a_matching_infra_checkout_is_not_an_override(repos):
    root = application(repos, "app-infra-pinned", lib1=repos["alpha"])
    line = context_line(configure(root))
    pin = git(root, "ls-tree", "HEAD", "infra").split()[2]
    assert f"pico family: context {pin} (version 0.1.0)" in line
    assert "override" not in line


def test_an_infra_checkout_at_another_commit_is_reported_as_an_override(repos):
    root = application(repos, "app-infra-moved", lib1=repos["alpha"])
    pin = git(root, "ls-tree", "HEAD", "infra").split()[2]
    other = repos["same_version"]
    git(root / "infra", "fetch", "--quiet", str(repos["infra"]), other)
    git(root / "infra", "checkout", "--quiet", other)
    line = context_line(configure(root))
    assert f"context override {other} " in line
    assert f"pins {pin}" in line


def test_a_dirty_infra_checkout_is_reported_as_an_override(repos):
    root = application(repos, "app-infra-dirty", lib1=repos["alpha"])
    pin = git(root, "ls-tree", "HEAD", "infra").split()[2]
    (root / "infra/LOCAL-NOTES.md").write_text("# Uncommitted\n")
    line = context_line(configure(root))
    assert f"context override {pin} with uncommitted changes " in line
    assert f"pins {pin}" in line


def test_a_fetchcontent_override_of_the_infrastructure_is_reported(repos):
    alpha, head = repos["alpha"]
    base = repos["base"]
    pin = git(alpha, "ls-tree", "HEAD", "infra").split()[2]
    working = make_infra_source(base / "infra-working", make_house_source(
        base / "house-working",
    ))
    revision = git(working, "rev-parse", "HEAD")
    assert revision != pin
    root = base / "plain-override"
    root.mkdir(exist_ok=True)
    (root / "CMakeLists.txt").write_text(PLAIN_PARENT.format(alpha=alpha, head=head))
    done = configure(
        root, f"-DFETCHCONTENT_SOURCE_DIR_PICO_TOOLING={working}", env=FILE_ALLOWANCE,
    )
    line = context_line(done)
    assert f"context override {revision} " in line
    assert f"pins {pin}" in line


def test_the_family_module_calls_no_private_house_helper():
    # House's underscore-prefixed CMake helpers are private (EN-00.8), and no
    # gate parses CMake, so only this test notices a dependency on one.
    text = (ROOT / "cmake/pico_family.cmake").read_text(encoding="utf-8")
    assert "_house_" not in text


def library(base, infra, name, version, value):
    """Scaffold a compiled host product that installs a versioned package."""
    root, _ = product(
        base / f"{name}-package", infra, name,
        {"template": LIBRARY, "version": version},
    )
    (root / "include" / name).mkdir(parents=True)
    (root / "src").mkdir(exist_ok=True)
    (root / f"include/{name}/core.hpp").write_text(
        f"#pragma once\nint {name}_value();\n",
    )
    (root / "src/core.cpp").write_text(
        f'#include "{name}/core.hpp"\nint {name}_value() {{ return {value}; }}\n',
    )
    return root, commit(root, "tooling: add the compiled synthetic product")


def consume(base, prefix, *, alpha, beta):
    source = base / "consumer"
    source.mkdir(exist_ok=True)
    (source / "CMakeLists.txt").write_text(CONSUMER.format(alpha=alpha, beta=beta))
    (source / "main.cpp").write_text(
        '#include <cstdio>\n#include "alpha/core.hpp"\n#include "beta/core.hpp"\n'
        'int main() { std::printf("%d\\n", alpha_value() * 10 + beta_value()); }\n',
    )
    build = source / "build"
    shutil.rmtree(build, ignore_errors=True)
    done = run("cmake", "-S", source, "-B", build, f"-DCMAKE_PREFIX_PATH={prefix}",
               cwd=source, check=False)
    return done, build


def test_independent_package_versions_install_and_are_found_by_version(repos):
    base = repos["base"]
    alpha = library(base, repos["infra"], "alpha", "1.2.0", 7)
    beta = library(base, repos["infra"], "beta", "3.4.0", 3)
    root = application(repos, "app-packages", lib1=alpha, lib2=beta)
    configured = configure(root)
    assert configured.returncode == 0, configured.stdout + configured.stderr
    assert configured.stdout.count("pico family: context ") == 1
    run("cmake", "--build", root / "build", cwd=root)
    prefix = base / "prefix"
    shutil.rmtree(prefix, ignore_errors=True)
    run("cmake", "--install", root / "build", "--prefix", prefix, cwd=root)

    found, build = consume(base, prefix, alpha="1.2.0", beta="3.4.0")
    assert found.returncode == 0, found.stdout + found.stderr
    run("cmake", "--build", build, cwd=base)
    assert run(build / "consumer", cwd=base).stdout.strip() == "73"

    for requested, name, offered in (
        ({"alpha": "2.0", "beta": "3.4.0"}, "alpha", "1.2.0"),
        ({"alpha": "1.3.0", "beta": "3.4.0"}, "alpha", "1.2.0"),
        ({"alpha": "1.2.0", "beta": "4.0"}, "beta", "3.4.0"),
    ):
        refused, _ = consume(base, prefix, **requested)
        text = " ".join((refused.stdout + refused.stderr).split())
        assert refused.returncode != 0, text
        assert (
            f'package "{name}" that is compatible with requested version '
            f'"{requested[name]}"' in text
        ), text
        assert f"version: {offered}" in text, text


@pytest.mark.real_sdk
def test_a_real_sdk_firmware_configure_of_two_libraries_shares_one_context(repos):
    sdk = real_sdk()
    root = application(repos, "app-real-sdk", lib1=repos["alpha"], lib2=repos["beta"])
    done = configure(root, f"-DPICO_SDK_PATH={sdk}")
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    assert "firmware=ON" in summary(done)
    assert done.stdout.count("pico family: context ") == 1
    cache = (root / "build/CMakeCache.txt").read_text()
    assert f"PICO_SDK_PATH:PATH={sdk}" in cache
    assert "arm-none-eabi-gcc" in cache
    assert "PICO_PLATFORM:STRING=rp2350" in cache


def test_a_selected_version_older_than_the_requester_is_fatal(repos):
    # Probe E: without a minimum-version rule the older context is reused, and the build
    # dies later on "Unknown CMake command pico_family_new_helper".
    root = application(repos, "app-old-context", lib1=repos["caller"])
    done = configure(root)
    text = " ".join((done.stdout + done.stderr).split())
    assert done.returncode != 0, text
    assert "needs version 0.1.1" in text
    assert "selected the older version 0.1.0" in text
    assert "Raise the parent's infra pin to version 0.1.1 or later" in text
    assert "Unknown CMake command" not in text


def test_a_selected_version_newer_or_equal_is_reused(repos):
    root = repos["base"] / "app-new-context"
    product(
        root, repos["infra"], "app",
        {"template": APPLICATION, "infra": repos["patch_version"]},
        lib1=repos["alpha"], lib2=repos["caller"],
    )
    done = configure(root)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("pico family: context ") == 1
    assert "reusing selected context" in done.stdout
    assert "new helper ran" in done.stdout


SYSCALLS = [
    "_chown", "_close", "_execve", "_fork", "_fstat", "_getentropy", "_getpid",
    "_gettimeofday", "_isatty", "_kill", "_link", "_lseek", "_open", "_read",
    "_readlink", "_stat", "_symlink", "_times", "_unlink", "_wait", "_write",
]


def probe_library(repos, name):
    root, _ = product(
        repos["base"] / name, repos["infra"], name,
        {"template": PROBE, "version": "1.0.0"},
    )
    (root / "probe.cpp").write_text("int main() { return 0; }\n")
    return root


def test_the_probe_option_is_off_for_a_host_configure(repos):
    root = probe_library(repos, "probehost")
    done = configure(root)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "probe=PROBEHOST_ENABLE_FIRMWARE_PROBE=OFF" in done.stdout


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (("PACKAGE", "pkg"), "PACKAGE and SOURCE are both required"),
        (("SOURCE", "probe.cpp"), "PACKAGE and SOURCE are both required"),
        (("PACKAGE", "pkg", "SOURCE", "probe.cpp", "EXTRA"), "unrecognised arguments"),
        (("PACKAGE", "pkg", "SOURCE"), "no value given for"),
    ],
)
def test_a_cross_probe_refuses_bad_arguments(repos, arguments, message):
    root = repos["base"] / ("probe-bad-" + "-".join(arguments).replace(".", "-"))
    call = (
        "{name}_probe PACKAGE {name} SOURCE probe.cpp\n"
        "        LIBRARIES {name}_headers)"
    )
    template = PROBE.replace(
        call,
        "{name}_probe " + " ".join(arguments) + ")",
    ).replace("if({prefix}_ENABLE_FIRMWARE_PROBE)", "if(TRUE)")
    product(
        root, repos["infra"], "probebad", {"template": template, "version": "1.0.0"},
    )
    done = configure(root)
    text = " ".join((done.stdout + done.stderr).split())
    assert done.returncode != 0
    assert message in text


@pytest.mark.real_sdk
def test_a_real_sdk_probe_links_with_no_warning_and_binds_the_syscalls(repos):
    sdk = real_sdk()
    root = probe_library(repos, "probelink")
    done = configure(root, "-GNinja", f"-DPICO_SDK_PATH={sdk}")
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    assert "probe=PROBELINK_ENABLE_FIRMWARE_PROBE=ON" in done.stdout
    built = run("cmake", "--build", root / "build", "--target", "probelink_probe",
                cwd=root, check=False)
    log = built.stdout + built.stderr
    assert built.returncode == 0, log[-3000:]
    assert "warning" not in log.lower(), log
    commands = run(
        "ninja", "-t", "commands", "probelink_probe", cwd=root / "build",
    ).stdout
    for flag in ("-fno-exceptions", "-fno-rtti", "--specs=nosys.specs"):
        assert flag in commands, flag
    assert commands.count("--defsym=") == len(SYSCALLS)
    elf = root / "build/probelink_probe.elf"
    assert elf.is_file()
    names = run("arm-none-eabi-nm", "--defined-only", elf, cwd=root).stdout
    defined = {line.split()[-1] for line in names.splitlines() if line.split()}
    assert "pico_family_probe_unsupported" in defined
    assert set(SYSCALLS) <= defined
    assert {"_sbrk", "_exit"} <= defined


@pytest.mark.parametrize(
    ("selected", "requested", "accepted"),
    [("1.3.0", "1.2.9", True), ("1.2.9", "1.3.0", False),
     ("1.3.0", "2.0.0", False), ("0.2.0", "0.1.0", False)],
)
def test_release_compatibility_boundaries(tmp_path, selected, requested, accepted):
    # AR-6: check both directions, including a newer incompatible 0.x minor.
    root = tmp_path / "context"
    root.mkdir()
    (root / "CMakeLists.txt").write_text(
        'cmake_minimum_required(VERSION 3.26)\nproject(boundaries NONE)\n'
        f'include("{ROOT}/cmake/pico_family.cmake")\n'
        f'set_property(GLOBAL PROPERTY PICO_FAMILY_ROOT "{ROOT}")\n'
        'set_property(GLOBAL PROPERTY PICO_FAMILY_REVISION "selected-pin")\n'
        f'set_property(GLOBAL PROPERTY PICO_FAMILY_SELECTED_VERSION "{selected}")\n'
        f'_pico_family_context("{ROOT}" "requested-pin" "{requested}")\n',
    )
    done = configure(root)
    text = " ".join((done.stdout + done.stderr).split())
    assert (done.returncode == 0) == accepted, text
    if not accepted:
        assert f"{requested} (requested-pin)" in text
        assert f"{selected} (selected-pin)" in text
        assert "Align the infra pins" in text or "Raise the parent's infra pin" in text
