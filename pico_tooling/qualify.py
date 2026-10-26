# SPDX-License-Identifier: MIT
"""Qualify the built family image from inside it (AR-10).

Run in the image with the pico-tooling checkout mounted read-only and an output
directory mounted writable:

    python3 -m pico_tooling.qualify --source /src --out /out \
        --image-id sha256:<id> [--image-tag <tag>]

Every pin is read from the checkout, where the Dockerfile, House and the family
module own it. The report is written twice, as qualification.json and
qualification.txt. Exit 0 when every check holds, 1 when a tool, pin or probe
differs from what the checkout requires (the report names it), 2 when the
evidence could not be gathered: not inside the image, an unreadable input, or no
image identity. A mismatch outranks missing evidence.

The standard library only; the image's own tools do the work.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

OK, MISMATCH, MISSING, NEEDS = "ok", "mismatch", "missing", "needs-network"
LABELS = {
    OK: "ok     ", MISMATCH: "MISMATCH", MISSING: "MISSING ",
    NEEDS: "needs   ",
}
APT_SOURCES = "/etc/apt/sources.list.d/ubuntu.sources"
# Docker Engine 29.8.2's default syscall filter with one rule added:
# personality(ADDR_NO_RANDOMIZE). See .devcontainer/README.md.
SECCOMP_SHA256 = "64a3e3aa3f3077d448633fc08b046b173959a3c211529a08e426f1e6a0a6c1cd"
ADDR_NO_RANDOMIZE = 0x40000
IMAGE_LABELS = {
    "org.opencontainers.image.title": "pico family development image",
    "org.opencontainers.image.description": (
        "The pico family's toolchain, Pico SDK and gates"
    ),
    "org.opencontainers.image.licenses": "MIT",
}
# The base image sets these; this image must not inherit them.
OVERRIDDEN_LABELS = (
    "org.opencontainers.image.version", "org.opencontainers.image.created",
)
ABSENT_LABELS = ("org.opencontainers.image.source",)
BUILTIN_PROFILE = "name=seccomp,profile=builtin"
GTEST_PROJECT = """\
cmake_minimum_required(VERSION 3.26)
project(qual_gtest LANGUAGES CXX)
include("{house}")
house_cxx_common_settings(OFF)
house_cxx_enable_gtest()
add_executable(qual_gtest test.cpp)
target_link_libraries(qual_gtest PRIVATE GTest::gtest_main)
gtest_discover_tests(qual_gtest)
"""
GTEST_SOURCE = "#include <gtest/gtest.h>\nTEST(Qual, Adds) { EXPECT_EQ(1 + 1, 2); }\n"
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
PRESENT = (
    "git", "curl", "bash", "make", "pkg-config", "ccache", "gh",
    "arm-none-eabi-gcc", "arm-none-eabi-g++", "arm-none-eabi-nm",
    "arm-none-eabi-size", "arm-none-eabi-objdump",
)
PACKAGES = (
    "gcc-arm-none-eabi", "binutils-arm-none-eabi", "libnewlib-arm-none-eabi",
    "libstdc++-arm-none-eabi-newlib",
    "cmake", "ninja-build", "make", "ccache", "python3", "doxygen", "gh",
)
HOST_LIBRARY = """\
cmake_minimum_required(VERSION 3.26)
include("{module}")
pico_family_bootstrap(QUAL)
project(qual LANGUAGES CXX)
message(STATUS "qual firmware=${{QUAL_BUILD_FIRMWARE}}")
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_library(qual_core STATIC core.cpp)
target_compile_options(qual_core PUBLIC -Wall -Wextra -Werror -fstrict-flex-arrays=3)
add_executable(qual_main main.cpp)
target_link_libraries(qual_main PRIVATE qual_core)
enable_testing()
add_test(NAME qual_main COMMAND qual_main)
"""
FIRMWARE_PROGRAM = """\
cmake_minimum_required(VERSION 3.26)
set(PICO_BOARD pico2_w)
include(pico_sdk_import.cmake)
project(qual_fw C CXX ASM)
pico_sdk_init()
add_executable(qual_fw main.cpp)
target_link_libraries(qual_fw pico_stdlib pico_cyw43_arch_none)
pico_add_extra_outputs(qual_fw)
"""
FIRMWARE_MAIN = """\
#include "pico/cyw43_arch.h"
#include "pico/stdlib.h"
int main() {
    stdio_init_all();
    return cyw43_arch_init() == 0 ? 0 : 1;
}
"""
CLEAN_THREADS = """\
#include <atomic>
#include <thread>
int main() {
    std::atomic<int> n{0};
    std::thread a([&] { for (int i = 0; i < 1000; ++i) { ++n; } });
    std::thread b([&] { for (int i = 0; i < 1000; ++i) { ++n; } });
    a.join();
    b.join();
    return n.load() == 2000 ? 0 : 1;
}
"""
RACY_THREADS = CLEAN_THREADS.replace("std::atomic<int> n{0}", "int n = 0").replace(
    "n.load()", "n",
)
FUZZ_TARGET = """\
#include <cstddef>
#include <cstdint>
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t*, std::size_t) { return 0; }
"""
CORE_SOURCE = "int core() { return 0; }\n"
MAIN_SOURCE = "int core();\nint main() { return core(); }\n"


class MissingEvidenceError(Exception):
    """An input the qualification needs could not be read."""


@dataclass
class Check:
    id: str
    status: str
    expected: str
    observed: str


class System:
    """The facts the qualification reads; tests replace it with fakes."""

    python = sys.version_info

    def run(self, argv, cwd=None, env=None, timeout=1800):
        try:
            done = subprocess.run(
                [str(part) for part in argv], cwd=cwd, capture_output=True,
                text=True, check=False, timeout=timeout,
                env={**os.environ, **(env or {})},
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return 127, str(error)
        return done.returncode, done.stdout + done.stderr

    def which(self, name):
        return shutil.which(name)

    def read(self, path):
        try:
            return Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def read_bytes(self, path):
        try:
            return Path(path).read_bytes()
        except OSError:
            return None

    def size(self, path):
        try:
            return Path(path).stat().st_size
        except OSError:
            return 0

    def write(self, path, text):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")

    def environ(self, name):
        return os.environ.get(name, "")

    def listing(self, path):
        try:
            return sorted(entry.name for entry in Path(path).iterdir())
        except OSError:
            return []


def version_tuple(text):
    found = re.search(r"\d+(?:\.\d+)+|\d+", text)
    return tuple(int(part) for part in found.group(0).split(".")) if found else ()


def at_least(observed, minimum):
    return bool(observed) and version_tuple(observed) >= version_tuple(minimum)


class Pins:
    """Everything the checkout pins, read where its owner keeps it."""

    def __init__(self, system, source):
        self.source = Path(source).resolve()
        self.system = system
        dockerfile = self.text(".devcontainer/Dockerfile")
        self.dockerfile = dockerfile
        self.base = self.match(r"^FROM (\S+)$", dockerfile, "the Dockerfile FROM line")
        self.sdk_path = self.match(
            r"^ENV PICO_SDK_PATH=(\S+)$", dockerfile, "ENV PICO_SDK_PATH",
        )
        self.sdk_version = self.arg("PICO_SDK_VERSION")
        self.sdk_commit = self.arg("PICO_SDK_COMMIT")
        self.picotool = self.arg("PICOTOOL_VERSION")
        self.apt_snapshot = self.arg("APT_SNAPSHOT")
        clang = self.text("house/config/.clang-version")
        words = [line.split("#", 1)[0].split() for line in clang.splitlines()]
        self.clang = next((w[0] for w in words if w and w[0].isdecimal()), "")
        if not self.clang:
            raise MissingEvidenceError("house/config/.clang-version names no major")
        self.ruff = self.match(
            r'^required-version = "==(.*)"', self.text("house/config/ruff.toml"),
            "house/config/ruff.toml required-version",
        )
        self.uv = self.match(
            r"^uv==(\S+)", self.text(".devcontainer/tools.txt"), "uv in tools.txt",
        )
        tools = self.toml("house/toolchains.toml")["tools"]
        family = self.match(
            r'set\(PICO_FAMILY_MINIMUM_CMAKE "([0-9.]+)"\)',
            self.text("cmake/pico_family.cmake"), "PICO_FAMILY_MINIMUM_CMAKE",
        )
        self.cmake = max(tools["cmake"]["minimum"], family, key=version_tuple)
        self.ninja = tools["ninja"]["minimum"]
        self.gxx = tools["gcc"]["minimum"]
        self.doxygen = tools["doxygen"]["minimum"]

    def text(self, relative):
        content = self.system.read(self.source / relative)
        if content is None:
            raise MissingEvidenceError(f"cannot read {relative}")
        return content

    def toml(self, relative):
        try:
            return tomllib.loads(self.text(relative))
        except tomllib.TOMLDecodeError as error:
            raise MissingEvidenceError(f"{relative}: {error}") from error

    @staticmethod
    def match(pattern, content, label):
        found = re.search(pattern, content, re.MULTILINE)
        if not found:
            raise MissingEvidenceError(f"cannot read {label}")
        return found.group(1)

    def arg(self, name):
        return self.match(rf"^ARG {name}=(\S+)$", self.dockerfile, f"ARG {name}")

    def inputs(self):
        names = (
            ".devcontainer/Dockerfile", ".devcontainer/tools.txt",
            ".devcontainer/seccomp.json", ".devcontainer/devcontainer.json",
            "house/config/.clang-version", "house/config/ruff.toml",
            "house/toolchains.toml", "cmake/pico_family.cmake",
        )
        digests = {}
        for name in names:
            data = self.system.read_bytes(self.source / name)
            digests[name] = hashlib.sha256(data).hexdigest() if data else None
        return {
            "base_image": self.base, "pico_sdk_version": self.sdk_version,
            "pico_sdk_commit": self.sdk_commit, "picotool_version": self.picotool,
            "apt_snapshot": self.apt_snapshot,
            "clang_major": self.clang, "ruff": self.ruff, "uv": self.uv,
            "cmake_minimum": self.cmake, "ninja_minimum": self.ninja,
            "gxx_minimum": self.gxx, "doxygen_minimum": self.doxygen,
            "file_sha256": digests,
        }


@dataclass
class Options:
    """What the host run supplies besides the mounted checkout."""

    labels: dict = field(default_factory=dict)
    engine_options: str = ""
    require_network: bool = False
    control: bool = False


class Qualifier:
    def __init__(self, system, pins, work, options, sdk_root):
        self.system = system
        self.pins = pins
        self.sdk_root = Path(sdk_root)
        self.work = Path(work)
        self.options = options
        self.checks = []
        self.facts = {}

    def record(self, check_id, status, expected, observed):
        one_line = " ".join(str(observed).split())
        self.checks.append(Check(check_id, status, str(expected), one_line))

    def expect(self, check_id, expected, observed):
        status = OK if observed == expected else MISMATCH
        self.record(check_id, status, expected, observed)

    def first_line(self, argv):
        _, output = self.system.run(argv)
        return output.strip().splitlines()[0] if output.strip() else ""

    def minimum(self, check_id, minimum, observed):
        status = OK if at_least(observed, minimum) else MISMATCH
        self.record(check_id, status, f">= {minimum}", observed)

    # --- identity and platform ------------------------------------------
    def platform(self):
        text = self.system.read("/etc/os-release") or ""
        release = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', text, re.MULTILINE))
        self.facts["os_release"] = release
        name, _, tag = self.pins.base.partition("@")[0].partition(":")
        self.expect("os-id", name, release.get("ID", ""))
        self.expect("os-version", tag, release.get("VERSION_ID", ""))
        self.expect("architecture", "x86_64", self.first_line(["uname", "-m"]))
        self.expect(
            "user", "agent 1000 /home/agent",
            f"{self.first_line(['id', '-un'])} {self.first_line(['id', '-u'])} "
            f"{self.system.environ('HOME')}",
        )
        interfaces = self.system.listing("/sys/class/net")
        self.facts["network_interfaces"] = interfaces

    def source_revision(self):
        source = self.pins.source
        self.facts["source_head"] = self.first_line(
            ["git", "-C", source, "rev-parse", "HEAD"]) or "unrecorded"
        self.facts["house_gitlink"] = self.first_line(
            ["git", "-C", source, "ls-tree", "HEAD", "house"]) or "unrecorded"

    # --- tools against their pins ---------------------------------------
    def versions(self):
        pins = self.pins
        python = ".".join(str(part) for part in self.system.python[:3])
        self.minimum("python", "3.11", python)
        self.minimum("cmake", pins.cmake, self.found(
            ["cmake", "--version"], r"cmake version (\S+)"))
        self.minimum("ninja", pins.ninja, self.first_line(["ninja", "--version"]))
        self.minimum("g++", pins.gxx, self.first_line(["g++", "-dumpfullversion"]))
        self.minimum("doxygen", pins.doxygen, self.first_line(["doxygen", "--version"]))
        self.expect("ruff", f"ruff {pins.ruff}", self.first_line(["ruff", "--version"]))
        self.expect("uv", pins.uv, self.found(["uv", "--version"], r"uv (\S+)"))
        self.expect("picotool", pins.picotool, self.found(
            ["picotool", "version"], r"picotool v(\S+)"))
        for tool in ("clang", "clang-tidy", "clang-format", "clangd"):
            self.clang_major(f"{tool}-{pins.clang}", f"{tool}-{pins.clang}")
        self.clang_major("clangd", "clangd")
        for tool in PRESENT:
            found = self.system.which(tool)
            self.record(f"present:{tool}", OK if found else MISMATCH, "on PATH",
                        found or "absent")
        code, _ = self.system.run(["python3", "-c", "import serial"])
        self.record("no-pyserial", OK if code else MISMATCH, "pyserial absent",
                    "absent" if code else "importable")
        self.facts["gcc_arm"] = self.first_line(["arm-none-eabi-gcc", "--version"])
        self.facts["gcc"] = self.first_line(["g++", "--version"])

    def found(self, argv, pattern):
        found = re.search(pattern, self.first_line(argv))
        return found.group(1) if found else ""

    def clang_major(self, check_id, tool):
        observed = self.found([tool, "--version"], r"version (\d+)\.")
        self.expect(check_id, self.pins.clang, observed)

    # --- the Pico SDK ----------------------------------------------------
    def sdk(self):
        self.expect(
            "sdk-path", self.pins.sdk_path, self.system.environ("PICO_SDK_PATH"),
        )
        cmake = self.system.read(self.sdk_root / "pico_sdk_version.cmake") or ""
        parts = re.findall(r"set\(PICO_SDK_VERSION_(?:MAJOR|MINOR|REVISION) (\d+)\)",
                           cmake)
        self.expect("sdk-version", self.pins.sdk_version, ".".join(parts))
        commit = self.first_line(["git", "-C", self.sdk_root, "rev-parse", "HEAD"])
        self.expect("sdk-commit", self.pins.sdk_commit, commit)
        code, status = self.system.run(
            ["git", "-C", self.sdk_root, "submodule", "status", "--recursive"])
        rows = [row for row in status.splitlines() if row.strip()]
        self.facts["sdk_submodules"] = [row.strip() for row in rows]
        missing = [row for row in rows if row.startswith("-")]
        healthy = code == 0 and rows and not missing
        self.record("sdk-submodules", OK if healthy else MISMATCH,
                    "every submodule checked out",
                    f"{len(rows)} listed, {len(missing)} missing")

    # --- packages --------------------------------------------------------
    def apt_sources(self):
        text = self.system.read(APT_SOURCES) or ""
        uris = re.findall(r"^URIs: (\S+)$", text, re.MULTILINE)
        wanted = f"https://snapshot.ubuntu.com/ubuntu/{self.pins.apt_snapshot}"
        self.facts["apt_sources"] = uris
        self.record("apt-snapshot", OK if uris and set(uris) == {wanted} else MISMATCH,
                    f"every source at {wanted}", ", ".join(uris) or "unreadable")

    def packages(self):
        code, output = self.system.run(
            ["dpkg-query", "-W", "-f=${Package} ${Version}\\n"])
        listed = dict(row.split(" ", 1) for row in output.splitlines() if " " in row)
        self.facts["installed_package_count"] = len(listed)
        self.facts["installed_packages"] = dict(sorted(listed.items()))
        self.facts["installed_packages_sha256"] = hashlib.sha256(
            output.encode()).hexdigest()
        clang = self.pins.clang
        named = (*PACKAGES, f"clang-{clang}", f"clang-tidy-{clang}",
                 f"clang-format-{clang}", f"clangd-{clang}",
                 f"libclang-rt-{clang}-dev")
        self.facts["toolchain_packages"] = {n: listed.get(n) for n in named}
        absent = [name for name in named if name not in listed]
        self.record("packages", OK if code == 0 and not absent else MISMATCH,
                    "toolchain packages installed", f"missing {absent}" if absent
                    else f"{len(named)} installed")

    # --- the syscall filter and ThreadSanitizer --------------------------
    def seccomp(self):
        path = self.pins.source / ".devcontainer/seccomp.json"
        data = self.system.read_bytes(path)
        self.expect("seccomp-profile-sha256", SECCOMP_SHA256,
                    hashlib.sha256(data).hexdigest() if data else "unreadable")
        self.expect("seccomp-profile-rule", "refuses by default, allows one rule",
                    self.profile_summary(data))
        status = self.system.read("/proc/self/status") or ""
        found = re.search(r"^Seccomp:\s*(\d+)", status, re.MULTILINE)
        self.expect("seccomp-active", "2", found.group(1) if found else "unreadable")
        code, output = self.system.run(["setarch", "-R", "true"])
        self.record("setarch-no-randomize", OK if code == 0 else MISMATCH,
                    "setarch -R true exits 0", f"exit {code} {output.strip()}")

    @staticmethod
    def profile_summary(data):
        try:
            profile = json.loads(data)
            allowed = [
                rule for rule in profile["syscalls"]
                if rule["names"] == ["personality"]
                and rule["action"] == "SCMP_ACT_ALLOW"
                and rule.get("args") == [
                    {"index": 0, "value": ADDR_NO_RANDOMIZE, "op": "SCMP_CMP_EQ"}]
            ]
            refuses = profile["defaultAction"] == "SCMP_ACT_ERRNO"
        except (TypeError, ValueError, KeyError):
            return "unreadable"
        if refuses and len(allowed) == 1:
            return "refuses by default, allows one rule"
        return f"default refuses: {refuses}, ADDR_NO_RANDOMIZE rules: {len(allowed)}"

    def thread_sanitizer(self):
        clang = f"clang++-{self.pins.clang}"
        for name, source in (("clean", CLEAN_THREADS), ("racy", RACY_THREADS)):
            directory = self.work / f"tsan-{name}"
            self.system.write(directory / "main.cpp", source)
            built, output = self.system.run(
                [clang, "-std=c++20", "-fsanitize=thread", "-pthread",
                 directory / "main.cpp", "-o", directory / "main"])
            if built:
                self.record(f"tsan-{name}", MISMATCH, "builds", output.strip()[-300:])
                continue
            code, output = self.system.run([directory / "main"])
            reported = "ThreadSanitizer: data race" in output
            wanted = (name == "racy")
            holds = reported == wanted and (code != 0) == wanted
            self.record(f"tsan-{name}", OK if holds else MISMATCH,
                        "race reported" if wanted else "no report",
                        f"exit {code}, race reported: {reported}")

    # --- util's host prerequisites ---------------------------------------
    def host_library(self):
        module = (self.pins.source / "cmake/pico_family.cmake").as_posix()
        clang = f"clang++-{self.pins.clang}"
        for label, compiler in (("gcc", "g++"), ("clang", clang)):
            directory = self.work / f"host-{label}"
            self.system.write(directory / "CMakeLists.txt",
                              HOST_LIBRARY.format(module=module))
            self.system.write(directory / "core.cpp", CORE_SOURCE)
            self.system.write(directory / "main.cpp", MAIN_SOURCE)
            outcome = self.host_outcome(directory, compiler)
            self.record(f"host-library-{label}", *outcome)

    def host_outcome(self, directory, compiler):
        env = {"CXX": compiler, "PICO_SDK_PATH": self.system.environ("PICO_SDK_PATH")}
        steps = (
            ["cmake", "-S", directory, "-B", directory / "build", "-G", "Ninja",
             f"-DCMAKE_CXX_COMPILER={compiler}"],
            ["cmake", "--build", directory / "build"],
            ["ctest", "--test-dir", directory / "build", "--output-on-failure"],
        )
        for number, argv in enumerate(steps):
            code, output = self.system.run(argv, env=env)
            if code:
                return MISMATCH, "configure, build and run", (
                    f"step {number + 1} exit {code}: {output.strip()[-300:]}")
            if number == 0 and "qual firmware=OFF" not in output:
                return MISMATCH, "portable host configure", "firmware was not OFF"
        return OK, "configure, build and run", "built with -Werror and ran"

    def sanitizer_fuzz(self):
        directory = self.work / "fuzz"
        self.system.write(directory / "fuzz.cpp", FUZZ_TARGET)
        clang = f"clang++-{self.pins.clang}"
        built, output = self.system.run(
            [clang, "-std=c++20", "-fsanitize=fuzzer,address,undefined",
             directory / "fuzz.cpp", "-o", directory / "fuzz"])
        if not built:
            built, output = self.system.run(
                [directory / "fuzz", "-runs=10"],
                env={"ASAN_OPTIONS": "detect_leaks=0"},
            )
        self.record("fuzz-asan-ubsan", OK if built == 0 else MISMATCH,
                    "libFuzzer target runs", f"exit {built} {output.strip()[-200:]}")

    # --- labels, GoogleTest and the default-profile control ---------------
    def image_labels(self):
        labels = self.options.labels
        for key, value in IMAGE_LABELS.items():
            self.expect(f"label:{key.rsplit('.', 1)[1]}", value, labels.get(key))
        for key in OVERRIDDEN_LABELS:
            self.expect(f"label:{key.rsplit('.', 1)[1]}", "", labels.get(key, ""))
        for key in ABSENT_LABELS:
            self.record(f"label:{key.rsplit('.', 1)[1]}",
                        MISMATCH if key in labels else OK, "absent",
                        labels.get(key, "absent"))
        self.facts["image_labels"] = labels

    def googletest(self):
        house = self.pins.source / "house/cxx/cmake/house.cmake"
        text = self.system.read(house) or ""
        url = re.search(r"URL (https://\S+)", text)
        digest = re.search(r"URL_HASH SHA256=(\w+)", text)
        self.facts["googletest"] = {
            "url": url.group(1) if url else None,
            "sha256": digest.group(1) if digest else None,
        }
        interfaces = [n for n in self.system.listing("/sys/class/net") if n != "lo"]
        if not interfaces:
            status = MISMATCH if self.options.require_network else NEEDS
            self.record("googletest", status, "a networked run configures it",
                        "no network interface: needs network")
            return
        directory = self.work / "gtest"
        self.system.write(directory / "CMakeLists.txt",
                          GTEST_PROJECT.format(house=house.as_posix()))
        self.system.write(directory / "test.cpp", GTEST_SOURCE)
        steps = (["cmake", "-S", directory, "-B", directory / "build", "-G", "Ninja"],
                 ["cmake", "--build", directory / "build"],
                 ["ctest", "--test-dir", directory / "build", "--output-on-failure"])
        for number, argv in enumerate(steps, 1):
            code, output = self.system.run(argv)
            if code:
                self.record("googletest", MISMATCH, "configure, build and run",
                            f"step {number} exit {code}: {output.strip()[-300:]}")
                return
        self.record("googletest", OK, "configure, build and run",
                    "fetched by House's pinned URL, built and ran one test")

    def control(self):
        status = self.system.read("/proc/self/status") or ""
        found = re.search(r"^Seccomp:\s*(\d+)", status, re.MULTILINE)
        self.expect("seccomp-active", "2", found.group(1) if found else "unreadable")
        code, output = self.system.run(["setarch", "-R", "true"])
        self.record("setarch-refused", OK if code else MISMATCH,
                    "setarch -R refused under the default profile",
                    f"exit {code} {output.strip()}")
        engine = self.options.engine_options
        self.record("engine-default-profile",
                    OK if BUILTIN_PROFILE in engine else MISMATCH,
                    f"{BUILTIN_PROFILE} among the engine's security options", engine)

    # --- util's firmware prerequisites -----------------------------------
    def firmware(self):
        directory = self.work / "firmware"
        self.system.write(directory / "CMakeLists.txt", FIRMWARE_PROGRAM)
        self.system.write(directory / "main.cpp", FIRMWARE_MAIN)
        importer = (self.sdk_root / "external/pico_sdk_import.cmake")
        self.system.write(directory / "pico_sdk_import.cmake",
                          self.system.read(importer) or "")
        log = ""
        build = directory / "build"
        for argv in (["cmake", "-S", directory, "-B", build, "-G", "Ninja"],
                     ["cmake", "--build", directory / "build"]):
            code, output = self.system.run(argv)
            log += output
            if code:
                self.record("firmware-pico2_w", MISMATCH, "configure and link a .uf2",
                            f"exit {code}: {output.strip()[-300:]}")
                return
        image = directory / "build/qual_fw.uf2"
        fetched = "building from source" in log
        good = self.system.size(image) > 0 and not fetched
        self.record("firmware-pico2_w", OK if good else MISMATCH,
                    "pico2_w .uf2 linked, picotool not fetched",
                    f"uf2 bytes {self.system.size(image)}, picotool fetched: {fetched}")

    def run(self):
        if self.options.control:
            steps = (self.source_revision, self.control)
        else:
            steps = self.full_steps()
        for step in steps:
            step()
        return self.checks

    def full_steps(self):
        return (
            self.platform, self.source_revision, self.image_labels, self.versions,
            self.sdk, self.apt_sources, self.packages, self.seccomp,
            self.thread_sanitizer, self.host_library, self.sanitizer_fuzz,
            self.googletest, self.firmware,
        )


def verdict(checks):
    if any(check.status == MISMATCH for check in checks):
        return 1
    return 2 if any(check.status == MISSING for check in checks) else 0


def render_text(report):
    lines = [f"image: {report['image']['id']} {report['image']['tag'] or ''}".rstrip()]
    for check in report["checks"]:
        label = LABELS[check["status"]]
        detail = "" if check["status"] == OK else f"; expected {check['expected']}"
        lines.append(f"{label} {check['id']}: {check['observed']}{detail}")
    summary = report["summary"]
    ending = f"qualify: {summary['verdict']}"
    if summary["failed"]:
        ending += f" ({', '.join(summary['failed'])})"
    if summary["needs_network"]:
        ending += f"; needs a networked run: {', '.join(summary['needs_network'])}"
    lines.append(ending)
    return "\n".join(lines) + "\n"


def build_report(args, pins, checks):
    code = verdict(checks)
    failed = [check.id for check in checks if check.status in (MISMATCH, MISSING)]
    pending = [check.id for check in checks if check.status == NEEDS]
    return {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "image": {"id": args.image_id, "tag": args.image_tag},
        "inputs": pins.inputs() if pins else {},
        "checks": [asdict(check) for check in checks],
        "summary": {"exit": code, "failed": failed, "needs_network": pending,
                    "verdict": {
            0: "every check holds", 1: "mismatch", 2: "missing evidence"}[code]},
    }


def decode_text(data):
    """Decode a host-written file; tolerate a BOM and Windows PowerShell's UTF-16."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


def read_host_file(system, path, label, checks):
    """Return the text of a file the host run wrote, or record why it is missing."""
    data = system.read_bytes(path) if path else None
    if data is None:
        checks.append(Check(label, MISSING, "file passed by the host command",
                            path or "not passed"))
        return None
    try:
        return decode_text(data)
    except UnicodeDecodeError as error:
        checks.append(Check(label, MISSING, "readable text", str(error)))
        return None


def host_options(system, args, checks):
    options = Options(require_network=args.require_network, control=args.control)
    if args.control:
        text = read_host_file(system, args.engine_security_options,
                              "engine-security-options", checks)
        options.engine_options = text or ""
        return options
    text = read_host_file(system, args.image_labels, "image-labels", checks)
    if text is not None:
        try:
            options.labels = json.loads(text) or {}
        except ValueError as error:
            checks.append(Check("image-labels", MISSING, "JSON object", str(error)))
    return options


def parse(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--image-id", default="")
    parser.add_argument("--image-tag", default="")
    parser.add_argument("--image-labels", default="",
                        help="JSON of the image's labels, written by the host")
    parser.add_argument("--require-network", action="store_true",
                        help="fail the GoogleTest check when the run is offline")
    parser.add_argument("--control", action="store_true",
                        help="the default-profile control: setarch -R must be refused")
    parser.add_argument("--engine-security-options", default="",
                        help="the engine's security options, written by the host")
    return parser.parse_args(argv)


def write_reports(system, args, report):
    out = Path(args.out)
    try:
        system.write(out / "qualification.json", json.dumps(report, indent=2) + "\n")
        system.write(out / "qualification.txt", render_text(report))
    except OSError as error:
        print(f"qualify: cannot write the report: {error}", file=sys.stderr)
        return False
    return True


def main(argv=None, system=None):
    args = parse(argv)
    system = system or System()
    checks, pins, facts = [], None, {}
    if not IMAGE_ID.fullmatch(args.image_id):
        checks.append(Check("image-identity", MISSING, "sha256:<64 hex>",
                            args.image_id or "not passed"))
    sdk_root = system.environ("PICO_SDK_PATH")
    if not sdk_root:
        checks.append(Check("sdk-path", MISSING, "PICO_SDK_PATH set by the image",
                            "not set"))
    elif not system.read(Path(sdk_root) / "pico_sdk_init.cmake"):
        checks.append(Check("inside-image", MISSING, f"{sdk_root} present",
                            "not inside the image"))
    options = host_options(system, args, checks)
    try:
        pins = Pins(system, args.source)
    except MissingEvidenceError as error:
        checks.append(Check("inputs", MISSING, "pins readable", str(error)))
    if pins and not any(check.status == MISSING for check in checks):
        with tempfile.TemporaryDirectory(prefix="qualify-") as work:
            qualifier = Qualifier(system, pins, work, options, sdk_root)
            checks.extend(qualifier.run())
            facts = qualifier.facts
    report = build_report(args, pins, checks)
    report["facts"] = facts
    report["mode"] = "control" if args.control else "qualification"
    written = write_reports(system, args, report)
    print(render_text(report), end="")
    code = report["summary"]["exit"]
    return code if written or code == 1 else 2


if __name__ == "__main__":
    sys.exit(main())
