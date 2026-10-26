# SPDX-License-Identifier: MIT
"""The image qualification names every mismatch and every gap, offline (AR-10).

The script runs inside the image; here a fake system answers its commands, so
no tool, SDK or container is involved. Pins come from this checkout.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

from pico_tooling import qualify
from pico_tooling.qualify import Pins, System, main
from tests.conftest import ROOT

IMAGE_ID = "sha256:" + "ab" * 32
SDK_VERSION_CMAKE = (
    "set(PICO_SDK_VERSION_MAJOR 2)\nset(PICO_SDK_VERSION_MINOR 3)\n"
    "set(PICO_SDK_VERSION_REVISION 0)\n"
)
OS_RELEASE = 'ID=ubuntu\nVERSION_ID="26.04"\nPRETTY_NAME="Ubuntu 26.04 LTS"\n'
CLANG = Pins(System(), ROOT).clang
LABELS_PATH = "/out/image-labels.json"
LABELS_ARG = ["--image-labels", LABELS_PATH]
ENGINE_PATH = "/out/engine.txt"


def good_labels():
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
        text=True, check=True,
    ).stdout.strip()
    return {
        **qualify.IMAGE_LABELS,
        "org.opencontainers.image.revision": head,
        "org.opencontainers.image.version": "",
        "org.opencontainers.image.created": "",
        "devcontainer.metadata": "[]",
    }


class FakeSystem(System):
    """Answers each command from a table keyed by the command's text."""

    def __init__(self, source, **replace):
        pins = Pins(System(), source)
        clang = pins.clang
        self.answers = {
            "uname -m": "x86_64", "id -un": "agent", "id -u": "1000",
            "cmake --version": "cmake version 3.31.0",
            "ninja --version": "1.12.1", "g++ -dumpfullversion": "15.2.0",
            "g++ --version": "g++ (Ubuntu 15.2.0) 15.2.0",
            "doxygen --version": "1.12.0", "ruff --version": f"ruff {pins.ruff}",
            "uv --version": f"uv {pins.uv} (x86_64-unknown-linux-gnu)",
            "picotool version": f"picotool v{pins.picotool} (Linux, GNU-15.2.0)",
            "arm-none-eabi-gcc --version": "arm-none-eabi-gcc 14.2.1",
            "clangd --version": f"Ubuntu clangd version {clang}.1.2",
            "git -C /opt/pico-sdk rev-parse HEAD": pins.sdk_commit,
            f"git -C {pins.source} rev-parse HEAD": good_labels()[
                "org.opencontainers.image.revision"
            ],
            "git -C /opt/pico-sdk submodule status --recursive": (
                " 0123456789abcdef lib/lwip (STABLE-2_2_0)\n"
            ),
            "setarch -R true": "",
        }
        for tool in ("clang", "clang-tidy", "clang-format", "clangd"):
            self.answers[f"{tool}-{clang} --version"] = (
                f"Ubuntu {tool} version {clang}.1.2"
            )
        self.failing = []
        self.codes = {"python3 -c import serial": 1}
        self.package_names = [
            *qualify.PACKAGES, f"clang-{clang}", f"clang-tidy-{clang}",
            f"clang-format-{clang}", f"clangd-{clang}", f"libclang-rt-{clang}-dev",
        ]
        self.tools = {*qualify.PRESENT}
        self.files = {
            LABELS_PATH: json.dumps(good_labels()),
            ENGINE_PATH: '["name=seccomp,profile=builtin","name=cgroupns"]',
            "/etc/os-release": OS_RELEASE,
            qualify.APT_SOURCES: (
                f"URIs: https://snapshot.ubuntu.com/ubuntu/{pins.apt_snapshot}\n"
                "Suites: resolute\n\n"
                f"URIs: https://snapshot.ubuntu.com/ubuntu/{pins.apt_snapshot}\n"
            ),
            "/opt/pico-sdk/pico_sdk_init.cmake": "# sdk",
            "/opt/pico-sdk/pico_sdk_version.cmake": SDK_VERSION_CMAKE,
            "/opt/pico-sdk/external/pico_sdk_import.cmake": "# import",
            "/proc/self/status": "Name:\tpython3\nSeccomp:\t2\nSeccomp_filters:\t2\n",
        }
        self.sizes = {"uf2": 25600}
        self.out_log = ""
        self.python = (3, 14, 4)
        self.env = {"PICO_SDK_PATH": "/opt/pico-sdk", "HOME": "/home/agent"}
        self.interfaces = ["lo"]
        self.source = Path(source)
        for key, value in replace.items():
            if isinstance(value, dict):
                getattr(self, key).update(value)
            else:
                setattr(self, key, value)

    def run(self, argv, *_ignored, **_named):
        text = " ".join(str(part) for part in argv)
        return self.dispatch(text)

    def dispatch(self, text):
        if any(part in text for part in self.failing):
            return 1, "failed"
        if text.startswith("dpkg-query"):
            return 0, "".join(f"{name} 1.0\n" for name in self.package_names)
        program = " " not in text
        if text.endswith("/tsan-racy/main") and program:
            return self.codes.get("tsan-racy", 66), self.answers.get(
                "tsan-racy", "WARNING: ThreadSanitizer: data race")
        if text.endswith("/tsan-clean/main") and program:
            return self.codes.get("tsan-clean", 0), ""
        if text.startswith("cmake -S") and "host-" in text:
            return self.codes.get(text, 0), "-- qual firmware=OFF\n"
        return self.codes.get(text, 0), self.answers.get(text, "")

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.tools else None

    def read(self, path):
        if str(path) in self.files:
            return self.files[str(path)]
        return super().read(path) if Path(path).is_relative_to(self.source) else None

    def read_bytes(self, path):
        if str(path) in self.files:
            return self.files[str(path)].encode("utf-8")
        if Path(path).is_relative_to(self.source):
            return super().read_bytes(path)
        return None

    def size(self, path):
        return self.sizes["uf2"] if str(path).endswith(".uf2") else 0

    def write(self, path, text):
        self.files[str(path)] = text

    def environ(self, name):
        return self.env.get(name, "")

    def listing(self, _path):
        return self.interfaces


def run_main(system, out, source, image_id, *extra):
    argv = ["--source", str(source), "--out", str(out), "--image-id", image_id]
    argv += [*LABELS_ARG, *extra]
    return main(argv, system=system)


def qualify_with(tmp_path, **replace):
    system = FakeSystem(ROOT, **replace)
    out = tmp_path / "out"
    code = main(
        ["--source", str(ROOT), "--out", str(out), "--image-id", IMAGE_ID,
         "--image-tag", "pico-family-dev:test", *LABELS_ARG],
        system=system,
    )
    report = json.loads(system.files[str(out / "qualification.json")])
    return code, report, system.files[str(out / "qualification.txt")]


def statuses(report):
    return {check["id"]: check["status"] for check in report["checks"]}


def test_a_conforming_image_exits_zero_and_records_its_identity(tmp_path):
    code, report, text = qualify_with(tmp_path)
    assert code == 0, text
    assert report["image"] == {"id": IMAGE_ID, "tag": "pico-family-dev:test"}
    assert report["summary"] == {
        "exit": 0, "failed": [], "needs_network": ["googletest"],
        "verdict": "every check holds",
    }
    assert IMAGE_ID in text
    assert "qualify: every check holds" in text


def test_the_report_records_the_inputs_that_reproduce_the_build(tmp_path):
    _, report, _ = qualify_with(tmp_path)
    inputs = report["inputs"]
    assert re.fullmatch(r"ubuntu:\d+\.\d+@sha256:[0-9a-f]{64}", inputs["base_image"])
    assert re.fullmatch(r"[0-9a-f]{40}", inputs["pico_sdk_commit"])
    assert inputs["clang_major"].isdecimal()
    assert all(inputs["file_sha256"].values()), inputs["file_sha256"]
    assert report["facts"]["installed_package_count"] > 0


@pytest.mark.parametrize(
    ("check", "replace"),
    [
        (
            f"clang-tidy-{CLANG}",
            {"answers": {f"clang-tidy-{CLANG} --version": "clang version 19.1.0"}},
        ),
        ("cmake", {"answers": {"cmake --version": "cmake version 3.25.1"}}),
        ("ninja", {"answers": {"ninja --version": "1.9.0"}}),
        ("g++", {"answers": {"g++ -dumpfullversion": "10.2.0"}}),
        ("ruff", {"answers": {"ruff --version": "ruff 0.15.0"}}),
        ("picotool", {"answers": {"picotool version": "picotool v2.2.0 (Linux)"}}),
        ("sdk-commit", {"answers": {"git -C /opt/pico-sdk rev-parse HEAD": "0" * 40}}),
        ("python", {"python": (3, 10, 0)}),
        (
            "present:arm-none-eabi-gcc",
            {"tools": set(qualify.PRESENT) - {"arm-none-eabi-gcc"}},
        ),
        ("architecture", {"answers": {"uname -m": "aarch64"}}),
        (
            "os-version",
            {"files": {"/etc/os-release": 'ID=ubuntu\nVERSION_ID="24.04"\n'}},
        ),
    ],
)
def test_a_tool_off_its_pin_exits_one_and_names_itself(tmp_path, check, replace):
    code, report, text = qualify_with(tmp_path, **replace)
    assert code == 1, text
    assert statuses(report)[check] == "mismatch"
    assert check in report["summary"]["failed"]
    assert re.search(rf"^MISMATCH {re.escape(check)}:", text, re.MULTILINE)


def test_cmake_must_meet_the_family_floor_not_only_houses(tmp_path):
    code, report, _ = qualify_with(
        tmp_path, answers={"cmake --version": "cmake version 3.24.9"},
    )
    assert code == 1
    [cmake] = [c for c in report["checks"] if c["id"] == "cmake"]
    assert cmake["expected"] == ">= 3.26"


def test_an_uninitialised_sdk_submodule_is_a_mismatch(tmp_path):
    code, report, _ = qualify_with(tmp_path, answers={
        "git -C /opt/pico-sdk submodule status --recursive": "-abc lib/lwip\n",
    })
    assert code == 1
    assert statuses(report)["sdk-submodules"] == "mismatch"


def test_a_missing_toolchain_package_is_a_mismatch(tmp_path):
    system_names = qualify.PACKAGES[:-1]
    code, report, _ = qualify_with(tmp_path, package_names=list(system_names))
    assert code == 1
    assert statuses(report)["packages"] == "mismatch"


@pytest.mark.parametrize(
    ("replace", "failed"),
    [
        ({"files": {"/proc/self/status": "Seccomp:\t0\n"}}, "seccomp-active"),
        ({"codes": {"setarch -R true": 1}}, "setarch-no-randomize"),
    ],
)
def test_a_container_without_the_syscall_filter_is_a_mismatch(
    tmp_path, replace, failed,
):
    code, report, _ = qualify_with(tmp_path, **replace)
    assert code == 1
    assert statuses(report)[failed] == "mismatch"


def test_a_profile_that_differs_from_its_pin_is_a_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(qualify, "SECCOMP_SHA256", "0" * 64)
    code, report, _ = qualify_with(tmp_path)
    assert code == 1
    assert statuses(report)["seccomp-profile-sha256"] == "mismatch"
    assert statuses(report)["seccomp-profile-rule"] == "ok"


def test_thread_sanitizer_must_report_a_race_and_pass_a_clean_program(tmp_path):
    code, report, _ = qualify_with(
        tmp_path, codes={"tsan-racy": 0}, answers={"tsan-racy": ""},
    )
    assert code == 1
    assert statuses(report)["tsan-racy"] == "mismatch"
    assert statuses(report)["tsan-clean"] == "ok"
    code, report, _ = qualify_with(tmp_path, codes={"tsan-clean": 66})
    assert code == 1
    assert statuses(report)["tsan-clean"] == "mismatch"


def test_a_host_configure_that_turns_firmware_on_is_a_mismatch(tmp_path):
    class Firmware(FakeSystem):
        def dispatch(self, text):
            if text.startswith("cmake -S") and "host-" in text:
                return 0, "-- qual firmware=ON\n"
            return super().dispatch(text)

    system = Firmware(ROOT)
    out = tmp_path / "out"
    code = run_main(system, out, ROOT, IMAGE_ID)
    report = json.loads(system.files[str(out / "qualification.json")])
    assert code == 1
    assert statuses(report)["host-library-gcc"] == "mismatch"


def test_a_firmware_that_fetches_picotool_is_a_mismatch(tmp_path):
    class Fetching(FakeSystem):
        def dispatch(self, text):
            if "firmware" in text and text.startswith("cmake --build"):
                return 0, "building from source"
            return super().dispatch(text)

    system = Fetching(ROOT)
    out = tmp_path / "out"
    code = run_main(system, out, ROOT, IMAGE_ID)
    report = json.loads(system.files[str(out / "qualification.json")])
    assert code == 1
    assert statuses(report)["firmware-pico2_w"] == "mismatch"


def test_a_firmware_link_that_produces_no_image_is_a_mismatch(tmp_path):
    code, report, _ = qualify_with(tmp_path, sizes={"uf2": 0})
    assert code == 1
    assert statuses(report)["firmware-pico2_w"] == "mismatch"


@pytest.mark.parametrize("identity", ["", "latest", "sha256:abc"])
def test_a_missing_or_malformed_image_identity_is_missing_evidence(tmp_path, identity):
    system = FakeSystem(ROOT)
    out = tmp_path / "out"
    code = run_main(system, out, ROOT, identity)
    report = json.loads(system.files[str(out / "qualification.json")])
    assert code == 2
    assert statuses(report) == {"image-identity": "missing"}


def test_running_outside_the_image_is_missing_evidence(tmp_path):
    system = FakeSystem(ROOT)
    del system.files["/opt/pico-sdk/pico_sdk_init.cmake"]
    out = tmp_path / "out"
    code = run_main(system, out, ROOT, IMAGE_ID)
    report = json.loads(system.files[str(out / "qualification.json")])
    assert code == 2
    assert statuses(report) == {"inside-image": "missing"}


def test_an_unset_sdk_path_is_not_qualified_and_nothing_is_guessed(tmp_path):
    system = FakeSystem(ROOT)
    del system.env["PICO_SDK_PATH"]
    out = tmp_path / "out"
    code = run_main(system, out, ROOT, IMAGE_ID)
    report = json.loads(system.files[str(out / "qualification.json")])
    assert code == 2
    assert statuses(report) == {"sdk-path": "missing"}
    text = system.files[str(out / "qualification.txt")]
    assert "PICO_SDK_PATH set by the image" in text


def test_the_sdk_is_read_from_the_variable_not_from_a_built_in_location(tmp_path):
    system = FakeSystem(ROOT)
    system.env["PICO_SDK_PATH"] = "/srv/sdk"
    for name in ("pico_sdk_init.cmake", "pico_sdk_version.cmake"):
        system.files[f"/srv/sdk/{name}"] = system.files.pop(f"/opt/pico-sdk/{name}")
    system.answers["git -C /srv/sdk rev-parse HEAD"] = system.answers[
        "git -C /opt/pico-sdk rev-parse HEAD"
    ]
    out = tmp_path / "out"
    run_main(system, out, ROOT, IMAGE_ID)
    found = statuses(json.loads(system.files[str(out / "qualification.json")]))
    assert found["sdk-path"] == "mismatch"
    assert found["sdk-version"] == "ok"
    assert found["sdk-commit"] == "ok"


def test_an_unreadable_pin_is_missing_evidence_naming_the_file(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    system = FakeSystem(ROOT)
    system.source = bare
    out = tmp_path / "out"
    code = run_main(system, out, bare, IMAGE_ID)
    report = json.loads(system.files[str(out / "qualification.json")])
    assert code == 2
    [inputs] = report["checks"]
    assert inputs["status"] == "missing"
    assert "cannot read .devcontainer/Dockerfile" in inputs["observed"]


def test_a_mismatch_outranks_missing_evidence():
    checks = [
        qualify.Check("a", qualify.MISSING, "x", "y"),
        qualify.Check("b", qualify.MISMATCH, "x", "y"),
    ]
    assert qualify.verdict(checks) == 1
    assert qualify.verdict(checks[:1]) == 2
    assert qualify.verdict([]) == 0


def test_a_downgraded_pin_in_the_checkout_is_a_mismatch(tmp_path):
    source = tmp_path / "source"
    for relative in (".devcontainer", "house/config", "cmake"):
        (source / relative).mkdir(parents=True)
    for relative in (
        ".devcontainer/Dockerfile", ".devcontainer/tools.txt",
        ".devcontainer/seccomp.json", ".devcontainer/devcontainer.json",
        "house/config/.clang-version", "house/config/ruff.toml",
        "house/toolchains.toml", "cmake/pico_family.cmake",
    ):
        (source / relative).write_bytes((ROOT / relative).read_bytes())
    docker = source / ".devcontainer/Dockerfile"
    docker.write_text(
        docker.read_text().replace(
            "ARG PICOTOOL_VERSION=2.3.0", "ARG PICOTOOL_VERSION=2.2.0",
        ),
    )
    system = FakeSystem(ROOT)
    system.source = source
    out = tmp_path / "out"
    code = run_main(system, out, source, IMAGE_ID)
    report = json.loads(system.files[str(out / "qualification.json")])
    assert code == 1
    assert statuses(report)["picotool"] == "mismatch"


def test_an_importable_pyserial_is_a_mismatch(tmp_path):
    code, report, _ = qualify_with(tmp_path, codes={"python3 -c import serial": 0})
    assert code == 1
    assert statuses(report)["no-pyserial"] == "mismatch"


def test_apt_sources_off_the_pinned_snapshot_are_a_mismatch(tmp_path):
    for wrong in (
        "URIs: http://archive.ubuntu.com/ubuntu/\n",
        "URIs: https://snapshot.ubuntu.com/ubuntu/20200101T000000Z\n",
        "",
    ):
        code, report, _ = qualify_with(
            tmp_path, files={qualify.APT_SOURCES: wrong},
        )
        assert code == 1
        assert statuses(report)["apt-snapshot"] == "mismatch"


def with_labels(tmp_path, labels):
    return qualify_with(tmp_path, files={LABELS_PATH: json.dumps(labels)})


@pytest.mark.parametrize(
    ("change", "failed"),
    [
        ({"org.opencontainers.image.title": "ubuntu"}, "label:title"),
        ({"org.opencontainers.image.version": "26.04"}, "label:version"),
        ({"org.opencontainers.image.created": "2026-10-06T21:25:30Z"},
         "label:created"),
        ({"org.opencontainers.image.source": "https://example.invalid"},
         "label:source"),
        ({"org.opencontainers.image.licenses": "Apache-2.0"}, "label:licenses"),
    ],
)
def test_an_inherited_or_wrong_label_is_a_mismatch(tmp_path, change, failed):
    code, report, _ = with_labels(tmp_path, {**good_labels(), **change})
    assert code == 1
    assert statuses(report)[failed] == "mismatch"
    assert report["facts"]["source_head"]


def test_the_label_file_may_carry_a_bom_or_be_utf_16():
    assert qualify.decode_text(b"\xef\xbb\xbf{}") == "{}"
    assert qualify.decode_text("{}".encode("utf-16")) == "{}"


def test_a_missing_label_file_is_missing_evidence(tmp_path):
    system = FakeSystem(ROOT)
    out = tmp_path / "out"
    code = main(["--source", str(ROOT), "--out", str(out), "--image-id", IMAGE_ID],
                system=system)
    report = json.loads(system.files[str(out / "qualification.json")])
    assert code == 2
    assert statuses(report) == {"image-labels": "missing"}


def test_the_full_package_list_is_recorded(tmp_path):
    _, report, _ = qualify_with(tmp_path)
    listed = report["facts"]["installed_packages"]
    assert listed["cmake"] == "1.0"
    assert len(listed) == report["facts"]["installed_package_count"]


def test_googletest_needs_network_offline_without_failing(tmp_path):
    code, report, text = qualify_with(tmp_path)
    assert code == 0, text
    assert statuses(report)["googletest"] == "needs-network"
    assert re.search(r"^needs    googletest:", text, re.MULTILINE)
    assert report["facts"]["googletest"]["url"].startswith("https://github.com/google")
    assert len(report["facts"]["googletest"]["sha256"]) == 64


def test_googletest_runs_when_networked_and_names_a_failure(tmp_path):
    code, report, _ = qualify_with(tmp_path, interfaces=["lo", "eth0"])
    assert code == 0
    assert statuses(report)["googletest"] == "ok"
    code, report, _ = qualify_with(
        tmp_path, interfaces=["lo", "eth0"], failing=["gtest/build"],
    )
    assert code == 1
    assert statuses(report)["googletest"] == "mismatch"


def test_a_required_network_run_that_is_offline_is_a_mismatch(tmp_path):
    system = FakeSystem(ROOT)
    out = tmp_path / "out"
    code = run_main(system, out, ROOT, IMAGE_ID, "--require-network")
    report = json.loads(system.files[str(out / "qualification.json")])
    assert code == 1
    assert statuses(report)["googletest"] == "mismatch"


def control(tmp_path, **replace):
    system = FakeSystem(ROOT, **replace)
    out = tmp_path / "out"
    code = main(["--source", str(ROOT), "--out", str(out), "--image-id", IMAGE_ID,
                 "--control", "--engine-security-options", ENGINE_PATH],
                system=system)
    report = json.loads(system.files[str(out / "qualification.json")])
    return code, report


def test_the_default_profile_control_expects_the_refusal(tmp_path):
    code, report = control(tmp_path, codes={"setarch -R true": 1})
    assert code == 0
    assert report["mode"] == "control"
    assert statuses(report) == {
        "seccomp-active": "ok", "setarch-refused": "ok", "engine-default-profile": "ok",
    }


def test_a_control_where_setarch_succeeds_or_the_profile_is_custom_is_a_mismatch(
    tmp_path,
):
    code, report = control(tmp_path)
    assert code == 1
    assert statuses(report)["setarch-refused"] == "mismatch"
    code, report = control(
        tmp_path, codes={"setarch -R true": 1},
        files={ENGINE_PATH: '["name=seccomp,profile=/x/custom.json"]'},
    )
    assert code == 1
    assert statuses(report)["engine-default-profile"] == "mismatch"


def test_a_control_without_the_engine_options_is_missing_evidence(tmp_path):
    system = FakeSystem(ROOT)
    out = tmp_path / "out"
    code = main(["--source", str(ROOT), "--out", str(out), "--image-id", IMAGE_ID,
                 "--control"], system=system)
    assert code == 2
