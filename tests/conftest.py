# SPDX-License-Identifier: MIT
"""Real local infrastructure sources and scaffolded libraries, no network."""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STANDARD_URL = "https://github.com/jamesfxley/engineering-standard.git"
IDENTITY = {
    "GIT_AUTHOR_NAME": "Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}


@pytest.fixture(autouse=True)
def without_hosting_environment(monkeypatch):
    # Hosted CI sets GITHUB_*; fixture repositories must not see the outer run.
    for name in [name for name in os.environ if name.startswith("GITHUB_")]:
        monkeypatch.delenv(name)


def run(*args, cwd, check=True, env=None):
    done = subprocess.run(
        [str(arg) for arg in args], cwd=cwd, capture_output=True, text=True,
        check=False, env={**os.environ, **IDENTITY, **(env or {})},
    )
    if check and done.returncode:
        raise AssertionError(
            f"{' '.join(str(arg) for arg in args)} exited {done.returncode}:\n"
            f"{done.stdout}{done.stderr}",
        )
    return done


def git(root, *args, check=True):
    return run("git", "-c", "protocol.file.allow=always", *args, cwd=root,
               check=check).stdout.strip()


def commit(root, summary):
    git(root, "add", "--all")
    git(root, "commit", "--quiet", "-m", summary)
    return git(root, "rev-parse", "HEAD")


def tracked_copy(source, destination):
    names = git(source, "ls-files", "--cached", "--others", "--exclude-standard",
                "-z").split("\0")
    for name in names:
        path = source / name
        if not name or name == ".gitmodules" or not path.is_file():
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def make_house_source(source):
    """Create a clean committed House with its standard as a local pin."""
    source.mkdir()
    git(source, "init", "--quiet", "--initial-branch=main")
    tracked_copy(ROOT / "house", source)
    git(source, "submodule", "add", "--quiet", str(ROOT / "house/standard"), "standard")
    # The published URL is what the pinned chain records; the local path that
    # served the add stays only in this clone's configuration.
    git(source, "config", "-f", ".gitmodules", "submodule.standard.url",
        STANDARD_URL)
    commit(source, "house: copy the pinned platform")
    return source


def make_infra_source(source, house_source):
    """Create a committed, tagged copy of this repository as a release source."""
    source.mkdir()
    git(source, "init", "--quiet", "--initial-branch=main")
    tracked_copy(ROOT, source)
    git(source, "submodule", "add", "--quiet", str(house_source), "house")
    git(source / "house", "config", "submodule.standard.url",
        str(ROOT / "house/standard"))
    git(source / "house", "submodule", "update", "--init", "--quiet", "standard")
    commit(source, "tooling: copy the family layer")
    git(source, "tag", "-a", "v0.1.0", "-m", "Release 0.1.0")
    return source


@pytest.fixture
def house_source(tmp_path):
    return make_house_source(tmp_path / "house source")


@pytest.fixture
def infra_source(tmp_path, house_source):
    return make_infra_source(tmp_path / "infra source", house_source)


def scaffold(infra_source, destination, *languages, name="sample-library"):
    arguments = [sys.executable, "-m", "pico_tooling", "scaffold", destination,
                 "--name", name, "--infra-repository", str(infra_source)]
    for language in languages or ("cxx",):
        arguments.extend(["--lang", language])
    run(*arguments, cwd=infra_source)
    return destination


@pytest.fixture
def library(tmp_path, infra_source):
    root = scaffold(infra_source, tmp_path / "library")
    # Host fixture: SDK builds are covered by the real_sdk cases separately.
    path = root / "house.toml"
    path.write_text(path.read_text().replace(
        "skip = {}",
        'skip = {"build:firmware"="fixture has no SDK", '
        '"lint:firmware"="fixture has no SDK"}',
    ))
    git(root, "add", "house.toml")
    git(root, "commit", "--amend", "--no-edit", "--quiet")
    return root


def dev(root, *args):
    return run(
        sys.executable, "dev.py", *args, cwd=root, check=False,
        env={"PICO_SDK_PATH": "", "HOUSE_MATRIX_SANITIZE": "ON"},
    )


def family(root, *args):
    return run(sys.executable, "-m", "infra.pico_tooling", *args, cwd=root,
               check=False)


FAKE_BINUTILS = """\
#!{python}
import json
import os
import sys

arguments = sys.argv[1:]
data = json.load(open(arguments[-1], encoding="utf-8"))
kind = os.path.basename(sys.argv[0]).rsplit("-", 1)[1]
if kind == "size":
    print(arguments[-1], ":")
    print("section   size   addr")
    for name, size in data["sections"].items():
        print(name, size, 0)
    print("Total", sum(data["sections"].values()))
elif kind == "objdump":
    if "objdump" in data:
        print(data["objdump"])
    else:
        print("Sections:\\nIdx Name Size VMA LMA File off Algn")
        for index, (name, size) in enumerate(data["sections"].items()):
            flash = name in (".text", ".rodata")
            address = 0x10000000 if flash else 0x20000000
            flags = "CONTENTS, ALLOC, LOAD, READONLY" if flash else "ALLOC"
            print("%d %s %08x %08x %08x 00000000 2**2" %
                  (index, name, size, address, address))
            print("                  " + flags)
elif "--print-size" in arguments:
    for size, kind, where in data["symbols"]:
        print(f"0000000000000000 {{size:016d}} {{kind}} name\\t{{where}}")
else:
    key = "defined" if "--defined-only" in arguments else "undefined"
    for symbol in data[key]:
        print("                 U", symbol)
"""


@pytest.fixture
def binutils(tmp_path, monkeypatch):
    """Put fake size and nm first on PATH."""
    directory = tmp_path / "binutils"
    directory.mkdir()
    for name in ("size", "objdump", "nm"):
        tool = directory / f"arm-none-eabi-{name}"
        tool.write_text(FAKE_BINUTILS.format(python=sys.executable), encoding="utf-8")
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{directory}{os.pathsep}{os.environ['PATH']}")
    return directory
