# SPDX-License-Identifier: MIT
"""Scaffold a library: House init at the nested pin, then family sync (AR-7).

House renders templates through its public init command with the pin and
platform path options. The family adds its input, CMake calls and bootstrap.
"""

import re
import subprocess
import sys
from pathlib import Path

from .metadata import NAME, InputError
from .sync import sync

# EN-07.2: the scaffold writes a whole repository (sources, docs, workflow and
# family files), so its area is the fixed one for repository tooling.
SUBJECT = "tooling: scaffold the library from the pico family template"


def run(*args, cwd):
    done = subprocess.run(
        [str(arg) for arg in args], cwd=cwd, capture_output=True, text=True,
        check=False,
    )
    if done.returncode:
        raise InputError(
            f"{' '.join(str(arg) for arg in args)}: "
            f"{(done.stdout + done.stderr).strip()}",
        )
    return done.stdout


def scaffold(destination, name, infra_repository, languages):
    """Create a committed library at destination pinned to this checkout."""
    if not NAME.fullmatch(name):
        raise InputError(
            "--name must use lowercase letters, digits and hyphens",
        )
    identifier = name.replace("-", "_")
    prefix = identifier.upper()
    languages = languages or ["cxx"]
    infra = Path(__file__).resolve().parents[1]
    destination = Path(destination).absolute()
    command = [
        sys.executable, infra / "dev.py", "init", destination, "--kind", "family",
        "--platform-source", infra, "--pin-path", "infra",
        "--platform-path", "infra/house",
    ]
    for language in dict.fromkeys(languages):
        command.extend(["--lang", language])
    run(*command, cwd=infra)
    run(
        "git", "config", "-f", ".gitmodules", "submodule.infra.url", infra_repository,
        cwd=destination,
    )
    (destination / "pico.toml").write_text(
        f'name = "{name}"\n\n[infra]\nrepository = "{infra_repository}"\n',
        encoding="utf-8", newline="\n",
    )
    if "cxx" in languages:
        cmake = destination / "CMakeLists.txt"
        text = cmake.read_text(encoding="utf-8").replace("VERSION 3.24", "VERSION 3.26")
        text = text.replace(
            "project(",
            "include(cmake/pico_family_bootstrap.cmake)\n"
            f"pico_family_bootstrap({prefix})\nproject(",
            1,
        )
        text = text.replace(
            "house_cxx_common_settings(OFF)",
            f"house_cxx_common_settings(OFF)\nhouse_cxx_enable_sanitizers({prefix})",
        )
        cmake.write_text(text, encoding="utf-8", newline="\n")
        for path in destination.rglob("CMakeLists.txt"):
            if (destination / "infra") in path.parents:
                continue
            text = re.sub(
                r"\bsample(?=\b|_)", identifier, path.read_text(encoding="utf-8"),
            )
            path.write_text(text, encoding="utf-8", newline="\n")
    readme = destination / "README.md"
    text = readme.read_text(encoding="utf-8")
    readme.write_text(
        f"# {name}\n" + text.split("\n", 1)[1], encoding="utf-8", newline="\n",
    )
    agents = destination / "AGENTS.md"
    text = agents.read_text(encoding="utf-8").replace(
        "# Product family", f"# {name}",
    ).replace(
        "This repository owns a product family's packages, dependency graph, profiles\n"
        "and target-specific behavior.",
        "This repository is a library in a product family.",
    )
    agents.write_text(text, encoding="utf-8", newline="\n")
    sync(destination)
    run("git", "add", "--all", cwd=destination)
    run(
        "git", "commit", "--amend", "--quiet", "-m", SUBJECT,
        cwd=destination,
    )
