# SPDX-License-Identifier: MIT
"""Read-only family report: infrastructure pins (AR-5).

Inputs name each library explicitly as name=local-repository[@ref];
a URL is refused and no library list is built in.
"""

import re
import subprocess
import tomllib

from .metadata import InputError, validate


def committed(repository, revision, path):
    done = subprocess.run(
        ["git", "-C", str(repository), "show", f"{revision}:{path}"],
        capture_output=True, text=True, check=False,
    )
    return done.stdout if done.returncode == 0 else None


def library(repository, revision):
    """Return (pico.toml data, infra pin) committed at revision, or None if absent."""
    text = committed(repository, revision, "pico.toml")
    if text is None:
        return None
    try:
        data = validate(tomllib.loads(text))
    except tomllib.TOMLDecodeError as error:
        raise InputError(f"{repository}@{revision}: pico.toml: {error}") from error
    row = subprocess.run(
        ["git", "-C", str(repository), "ls-tree", revision, "infra"],
        capture_output=True, text=True, check=False,
    ).stdout.split()
    return data, (row[2] if len(row) >= 3 and row[1] == "commit" else None)


REMOTE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://|[^/@\s]+@[^/\s:]+:")


def local_repository(location):
    """Return a repository path and ref; refuse anything but a local repository."""
    refusal = InputError(f"sources must be local repository paths, got {location!r}")
    if REMOTE.match(location):
        raise refusal
    repository, _, ref = location.partition("@")
    done = subprocess.run(
        ["git", "-C", repository, "rev-parse", "--git-dir"],
        capture_output=True, text=True, check=False,
    )
    if done.returncode:
        raise refusal
    return repository, ref or "HEAD"


def parse(arguments):
    sources = {}
    for argument in arguments:
        name, separator, location = argument.partition("=")
        if not separator or not name or not location:
            raise InputError(f"expected name=repository[@ref], got {argument!r}")
        sources[name] = local_repository(location)
    return sources


def report(arguments):
    """Return (lines, status); invalid inputs raise InputError."""
    sources = parse(arguments)
    lines = ["library | infra", "---|---"]
    pins = {}
    for name, (repository, ref) in sources.items():
        found = library(repository, ref)
        if found is None:
            raise InputError(f"{repository}@{ref} has no committed pico.toml")
        _, pin = found
        lines.append(f"{name} | {(pin or 'absent')[:12]}")
        pins.setdefault(pin, []).append(name)
    lines.append("")
    lines.append(
        "infrastructure pins: "
        + "; ".join(
            f"{(pin or 'absent')[:12]} ({', '.join(names)})"
            for pin, names in sorted(pins.items(), key=lambda row: str(row[0]))
        ),
    )
    return lines, 0
