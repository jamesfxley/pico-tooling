# SPDX-License-Identifier: MIT
"""Write or compare the generated CMake bootstrap (AR-2)."""

import subprocess
from pathlib import Path

from .metadata import InputError, load
from .render import SYNC, files


def host_text(root, path):
    target = root / path
    if not target.exists():
        return None
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise InputError(f"cannot read {path}: {error}") from error


def indexed(root):
    try:
        names = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True, text=True, check=True,
        ).stdout.split("\0")
    except (OSError, subprocess.CalledProcessError) as error:
        raise InputError(f"cannot list indexed files: {error}") from error
    return {Path(name) for name in names if name}


def sync(root):
    for path, text in files(root, load(root)).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")


def findings(root, tracked):
    """Return (path, message) for each missing, unindexed or changed output.

    Damaged inputs raise InputError; a missing generated output is a
    repairable finding, never an unavailable result.
    """
    data = load(root)
    found = []
    for path, text in files(root, data).items():
        current = host_text(root, path)
        if current is None:
            found.append((path, f"missing generated output; run {SYNC}"))
        elif current != text:
            found.append((path, f"generated output differs; run {SYNC}"))
        elif Path(path) not in tracked:
            found.append((path, "generated output is not indexed; git add it"))
    return found
