# SPDX-License-Identifier: MIT
"""The family image definition is pinned, strict and free of agent files (AR-9)."""

import hashlib
import json
import re
import subprocess
import textwrap

import pytest

from tests.conftest import ROOT

DEVCONTAINER = ROOT / ".devcontainer"
DOCKERFILE = (DEVCONTAINER / "Dockerfile").read_text(encoding="utf-8")
BRANDS = re.compile(r"claude|anthropic|codex|copilot|openai", re.IGNORECASE)
PERSONALITY = {"index": 0, "value": 0x40000, "op": "SCMP_CMP_EQ"}
# Docker Engine 29.8.2's default filter plus the one personality rule.
SECCOMP_SHA256 = "64a3e3aa3f3077d448633fc08b046b173959a3c211529a08e426f1e6a0a6c1cd"


def tracked():
    done = subprocess.run(
        ["git", "ls-files", "-s"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [row.split(maxsplit=3) for row in done.stdout.splitlines()]


def test_the_devcontainer_configuration_is_strict_json_that_builds_the_dockerfile():
    configuration = json.loads((DEVCONTAINER / "devcontainer.json").read_text())
    build = configuration["build"]
    assert (DEVCONTAINER / build["dockerfile"]).is_file()
    assert (DEVCONTAINER / build["context"]).resolve() == ROOT
    assert "image" not in configuration


def test_the_configuration_loads_the_carried_profile_and_asks_for_no_device():
    text = (DEVCONTAINER / "devcontainer.json").read_text()
    configuration = json.loads(text)
    assert configuration["runArgs"] == [
        "--security-opt",
        "seccomp=${localWorkspaceFolder}/.devcontainer/seccomp.json",
    ]
    assert not {"mounts", "privileged", "capAdd"} & set(configuration)
    assert not re.search(r"--device|/dev/", text)


def test_the_base_is_pinned_by_digest_and_the_architecture_is_not_chosen_by_it():
    [base] = re.findall(r"^FROM (\S+)$", DOCKERFILE, re.MULTILINE)
    assert re.fullmatch(r"ubuntu:26\.04@sha256:[0-9a-f]{64}", base)
    assert "--platform" not in DOCKERFILE


def test_apt_installs_from_one_dated_snapshot_and_nothing_else():
    [stamp] = re.findall(r"^ARG APT_SNAPSHOT=(\S+)$", DOCKERFILE, re.MULTILINE)
    assert re.fullmatch(r"\d{8}T\d{6}Z", stamp)
    assert "snapshot.ubuntu.com/ubuntu/${APT_SNAPSHOT}" in DOCKERFILE
    assert "archive.ubuntu.com" not in DOCKERFILE.replace("\\.ubuntu\\.com", "")
    assert "apt-get upgrade" in DOCKERFILE


def run_steps():
    """Return the Dockerfile's RUN instructions, continuation lines joined."""
    joined = DOCKERFILE.replace("\\\n", " ")
    return [line[4:] for line in joined.splitlines() if line.startswith("RUN ")]


def retry_loops():
    return [
        step[step.index("for attempt") : step.index("done") + 4]
        for step in run_steps()
        if "for attempt" in step
    ]


def test_every_apt_update_fails_on_any_error_inside_the_bounded_retry_loop():
    updates = [s for s in run_steps() if re.search(r"apt-get\b[^;&|]*\bupdate\b", s)]
    assert len(updates) == 2
    for step in updates:
        [loop] = [loop for loop in retry_loops() if loop in step]
        [update] = re.findall(r"apt-get\b[^;&|]*\bupdate\b", step)
        assert "--error-on=any" in update
        assert update in loop
        assert "for attempt in 1 2 3 4 5;" in loop
        assert "sleep 30" in loop
        assert '"${attempt}" == 5' in loop
        assert 'exit "${status}"' in loop


def test_the_apt_options_are_the_documented_ones():
    [config] = [s for s in run_steps() if "80-retries" in s]
    options = re.findall(r"'(Acquire::[^ ]+) \"(\d+)\";'", config)
    assert options == [
        ("Acquire::Retries", "10"),
        ("Acquire::http::Timeout", "30"),
        ("Acquire::https::Timeout", "30"),
    ]


def run_loop(tmp_path, loop, failures):
    """Run one loop with a stub apt-get that fails `failures` times first."""
    tmp_path.joinpath("count").write_text("0", encoding="utf-8")
    stub = textwrap.dedent(
        f"""\
        #!/bin/bash
        echo "$*" >> {tmp_path}/calls
        n=$(( $(cat {tmp_path}/count) + 1 ))
        echo "$n" > {tmp_path}/count
        case " $* " in *" update "*) [[ $n -gt {failures} ]] || exit 100 ;; esac
        """,
    )
    tmp_path.joinpath("bin").mkdir()
    nap = f'#!/bin/bash\necho "$1" >> {tmp_path}/naps\n'
    for name, body in (("apt-get", stub), ("sleep", nap)):
        path = tmp_path / "bin" / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    script = f"clang=20; set -euo pipefail; {loop}; echo finished"
    env = {"PATH": f"{tmp_path}/bin:/usr/bin:/bin"}
    return subprocess.run(
        ["/bin/bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("index", [0, 1])
def test_a_loop_retries_a_failed_update_until_the_service_recovers(tmp_path, index):
    done = run_loop(tmp_path, retry_loops()[index], failures=2)
    assert done.returncode == 0
    assert done.stdout.strip() == "finished"
    assert tmp_path.joinpath("naps").read_text(encoding="utf-8").split() == ["30", "30"]
    assert done.stderr.count("retrying in 30 s") == 2


@pytest.mark.parametrize("index", [0, 1])
def test_a_loop_gives_up_after_five_attempts_with_the_last_status(tmp_path, index):
    done = run_loop(tmp_path, retry_loops()[index], failures=99)
    assert done.returncode == 100
    assert "finished" not in done.stdout
    assert "apt failed after 5 attempts" in done.stderr
    assert len(tmp_path.joinpath("naps").read_text(encoding="utf-8").split()) == 4
    calls = tmp_path.joinpath("calls").read_text(encoding="utf-8").splitlines()
    assert all("--error-on=any" in call for call in calls if " update" in call)


def test_the_sdk_and_picotool_are_cloned_by_tag_and_checked_against_a_commit():
    for name in ("PICO_SDK", "PICOTOOL"):
        version = re.search(rf"^ARG {name}_VERSION=(\S+)$", DOCKERFILE, re.MULTILINE)
        commit = re.search(rf"^ARG {name}_COMMIT=(\S+)$", DOCKERFILE, re.MULTILINE)
        assert version.group(1) == "2.3.0"
        assert re.fullmatch(r"[0-9a-f]{40}", commit.group(1))
    clones = len(re.findall(r"git clone .*?--branch", DOCKERFILE.replace("\\\n", "")))
    checks = len(re.findall(r'rev-parse HEAD\)" == "\$\{PICO', DOCKERFILE))
    assert clones == checks == 2


def test_every_wheel_is_installed_by_hash():
    requirements = (DEVCONTAINER / "tools.txt").read_text()
    pins = re.findall(r"^(\w+)==\S+ \\$", requirements, re.MULTILINE)
    assert set(pins) == {"uv", "ruff"}
    assert requirements.count("--hash=sha256:") >= len(pins)
    assert "--require-hashes" in DOCKERFILE
    assert "--only-binary :all:" in DOCKERFILE


def test_the_image_downloads_nothing_else():
    run_lines = " ".join(DOCKERFILE.replace("\\\n", "").splitlines())
    assert not re.search(r"\b(curl|wget)\b[^&]*-o|\| *(ba)?sh\b", run_lines)
    assert "shellcheck" not in DOCKERFILE.lower()


def test_the_image_installs_no_serial_package():
    assert "serial" not in DOCKERFILE
    assert "serial" not in (DEVCONTAINER / "tools.txt").read_text()


def test_no_agent_tool_file_mount_or_extension_is_in_the_image_definition():
    for path in DEVCONTAINER.iterdir():
        assert not BRANDS.search(path.name), path
        assert not BRANDS.search(path.read_text(encoding="utf-8")), path
    assert "BASH_ENV" not in DOCKERFILE


def test_the_build_context_allows_exactly_the_files_the_dockerfile_copies():
    copied = re.findall(r"^COPY (\S+) ", DOCKERFILE, re.MULTILINE)
    allowed = (DEVCONTAINER / "Dockerfile.dockerignore").read_text().split()
    assert allowed[0] == "*"
    assert sorted(path.removeprefix("!") for path in allowed[1:]) == sorted(copied)
    for path in copied:
        assert (ROOT / path).is_file(), path


UPSTREAM = ROOT / "tests/data/moby-docker-v29.8.2-seccomp-default.json"
# moby/moby tag docker-v29.8.2, vendor/github.com/moby/profiles/seccomp/default.json
UPSTREAM_SHA256 = "536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74"


def test_the_upstream_copy_is_the_pinned_file():
    assert hashlib.sha256(UPSTREAM.read_bytes()).hexdigest() == UPSTREAM_SHA256


def test_the_carried_profile_is_the_pinned_digest_and_laid_out_like_upstream():
    path = DEVCONTAINER / "seccomp.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == SECCOMP_SHA256
    text = path.read_text(encoding="utf-8")
    assert json.dumps(json.loads(text), indent="\t", ensure_ascii=False) == text


def test_the_only_difference_from_upstream_is_the_no_randomize_rule():
    upstream = json.loads(UPSTREAM.read_text(encoding="utf-8"))
    carried = json.loads((DEVCONTAINER / "seccomp.json").read_text(encoding="utf-8"))
    added = [rule for rule in carried["syscalls"] if rule not in upstream["syscalls"]]
    assert added == [
        {"names": ["personality"], "action": "SCMP_ACT_ALLOW", "args": [PERSONALITY]},
    ]
    assert [r for r in upstream["syscalls"] if r not in carried["syscalls"]] == []
    assert len(carried["syscalls"]) == len(upstream["syscalls"]) + 1
    assert {k: v for k, v in carried.items() if k != "syscalls"} == {
        k: v for k, v in upstream.items() if k != "syscalls"
    }
    assert carried["defaultAction"] == "SCMP_ACT_ERRNO"


@pytest.mark.parametrize("suffix", [".bash", ".bat"])
def test_the_repository_owns_no_shell_script(suffix):
    assert [row[3] for row in tracked() if row[3].endswith(suffix)] == []


def test_only_the_distro_setup_is_a_posix_shell_script():
    # AR-15: provisioning runs inside WSL, outside the Python container runner.
    assert [row[3] for row in tracked() if row[3].endswith(".sh")] == [
        "host/in-dev-distro.sh",
    ]


def test_only_the_declared_host_proxy_scripts_are_powershell():
    # AR-15 owns the proxy entry points and their no-device CI test.
    assert [row[3] for row in tracked() if row[3].endswith(".ps1")] == [
        "host/device-proxy.ps1",
        "host/setup-dev-distro.ps1",
        "host/setup-device-proxy.ps1",
        "host/start-device-proxy.ps1",
        "host/test-device-proxy.ps1",
    ]


def test_the_repository_owns_no_symlink():
    assert [row[3] for row in tracked() if row[0] == "120000"] == []


def test_the_image_label_asks_for_no_host_device():
    [label] = re.findall(r"devcontainer\.metadata='(.*)'", DOCKERFILE)
    metadata = json.loads(label)
    assert metadata == [
        {"remoteUser": "agent", "containerUser": "agent", "updateRemoteUserUID": True},
    ]
    assert not re.search(r"runArgs|privileged|capAdd|--device|/dev/", label)


def test_the_image_sets_its_own_labels_and_does_not_inherit_the_bases():
    pairs = re.findall(r'(org\.opencontainers\.image\.\w+)="([^"]*)"', DOCKERFILE)
    labels = dict(pairs)
    assert labels["org.opencontainers.image.title"] == "pico family development image"
    assert labels["org.opencontainers.image.licenses"] == "MIT"
    assert labels["org.opencontainers.image.description"]
    assert "org.opencontainers.image.revision" not in labels
    # The base sets title, version, created and description; the last three are
    # overridden, so none of the base's values survives.
    assert labels["org.opencontainers.image.version"] == ""
    assert labels["org.opencontainers.image.created"] == ""
    assert "org.opencontainers.image.source" not in labels


def test_no_image_revision_argument_is_required():
    assert "PICO_TOOLING_REVISION" not in DOCKERFILE


def test_the_distro_setup_inputs_are_pinned_and_the_shell_is_carried():
    # AR-15: no Desktop export or additional source-repository dependency.
    setup = (ROOT / "host/setup-dev-distro.ps1").read_text(encoding="utf-8")
    [url] = re.findall(r'^\$ImageUrl = "([^"]+)"$', setup, re.MULTILINE)
    assert re.fullmatch(
        r"https://releases\.ubuntu\.com/26\.04\.1/ubuntu-26\.04\.1-wsl-amd64\.wsl",
        url,
    )
    [digest] = re.findall(r'^\$ImageSha256 = "([^"]+)"$', setup, re.MULTILINE)
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert '$DockerVersion = "29.8.2"' in setup
    assert (ROOT / "host/in-dev-distro.sh").is_file()
    assert 'Join-Path $PSScriptRoot "in-dev-distro.sh"' in setup
    assert "[IO.File]::WriteAllText($installed, $content," in setup
