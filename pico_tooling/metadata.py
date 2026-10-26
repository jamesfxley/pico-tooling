# SPDX-License-Identifier: MIT
"""Read and validate a library's family input, pico.toml (AR-1)."""

import math
import re
import subprocess
import tomllib
from pathlib import PurePosixPath

from .embedded import SYMBOL_SETS

NAME = re.compile(r"[a-z][a-z0-9-]*")
REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
RELEASE = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
AXIS = re.compile(r"[a-z][a-z0-9_]*")
NOT_A_LIBRARY = "infrastructure repository: no pico.toml and no infra pin"


class InputError(Exception):
    """The family input is unreadable or invalid, so no verdict is possible."""


def problem(label, message):
    raise InputError(f"pico.toml: {label}: {message}")


def keys(value, allowed, required, label):
    """Check a table; an empty label names the document's top level."""
    if not isinstance(value, dict):
        problem(label or "document", "expected a table")
    unknown = value.keys() - allowed
    if unknown:
        problem(
            label or "document",
            f"unknown keys {sorted(unknown)}; supported: {sorted(allowed)}",
        )
    for key in sorted(required - value.keys()):
        problem(f"{label}.{key}" if label else key, "is required")


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        problem(label, "expected a nonempty string")
    return value


def repository(value, label):
    """Return a repository location; one starting with '-' would act as an option."""
    if text(value, label).startswith("-"):
        problem(label, "a repository location must not start with '-'")
    return value


def relative(value, label):
    path = PurePosixPath(text(value, label))
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        problem(label, "expected a forward-slash path inside the dependency")
    return path.as_posix()


def budget(value, label):
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
    ):
        problem(label, "expected a positive, finite number of KiB")


def instance_name(item, seen, label):
    name = text(item.get("name"), label + ".name")
    if name in seen:
        problem(label + ".name", f"duplicate name {name!r}")
    seen.add(name)


def condition(when, label):
    """Validate footprint matrix conditions (AR-11)."""
    if not isinstance(when, dict):
        problem(label, "expected a table")
    for axis, value in when.items():
        if not AXIS.fullmatch(axis):
            problem(f"{label}.{axis}", "expected a valid lowercase axis name")
        text(value, f"{label}.{axis}")


def footprints(rows):
    if not isinstance(rows, list):
        problem("footprint", "expected an array of tables")
    seen = set()
    for number, item in enumerate(rows, 1):
        label = f"footprint[{number}]"
        keys(
            item,
            {
                "name", "elf", "ram_kib", "flash_kib", "owned_prefix", "owned_kib",
                "when",
            },
            {"name", "elf", "ram_kib"},
            label,
        )
        if "when" in item:
            condition(item["when"], label + ".when")
        instance_name(item, seen, label)
        item["elf"] = relative(item["elf"], label + ".elf")
        for key in ("ram_kib", "flash_kib", "owned_kib"):
            if key in item:
                budget(item[key], f"{label}.{key}")
        if ("owned_prefix" in item) != ("owned_kib" in item):
            problem(label, "owned_prefix and owned_kib are given together")
        if "owned_prefix" in item:
            item["owned_prefix"] = relative(
                item["owned_prefix"], label + ".owned_prefix",
            )


def symbols(rows):
    if not isinstance(rows, list):
        problem("symbols", "expected an array of tables")
    seen = set()
    for number, item in enumerate(rows, 1):
        label = f"symbols[{number}]"
        keys(
            item,
            {"name", "mode", "path", "sets", "expect"},
            {"name", "mode", "path", "sets"},
            label,
        )
        instance_name(item, seen, label)
        if item.get("expect", "refused") != "refused":
            problem(label + ".expect", "expected 'refused'")
        mode = item["mode"]
        if mode not in ("objects", "image"):
            problem(label + ".mode", "expected 'objects' or 'image'")
        item["path"] = relative(item["path"], label + ".path")
        names = item["sets"]
        if (
            not isinstance(names, list)
            or not names
            or len(set(names)) != len(names)
            or any(not isinstance(name, str) for name in names)
        ):
            problem(label + ".sets", "expected a nonempty array of distinct set names")
        for name in names:
            if name not in SYMBOL_SETS:
                problem(
                    label + ".sets",
                    f"unknown set {name!r}; known: {sorted(SYMBOL_SETS)}",
                )
            if SYMBOL_SETS[name][0] != mode:
                problem(
                    label + ".sets",
                    f"{name} is an {SYMBOL_SETS[name][0]} check; mode is {mode!r}",
                )


def validate(data):
    keys(
        data,
        {
            "name", "infra", "footprint", "symbols",
        },
        {"name", "infra"},
        "",
    )
    if not NAME.fullmatch(text(data["name"], "name")):
        problem("name", "expected lowercase letters, digits and hyphens")
    infra = data["infra"]
    keys(infra, {"repository"}, {"repository"}, "infra")
    repository(infra["repository"], "infra.repository")

    footprints(data.setdefault("footprint", []))
    symbols(data.setdefault("symbols", []))
    return data


def is_library(root):
    """Return whether root is a library: it holds a family input or pins infra.

    Only the infrastructure repository has neither, so only there are the
    family gates not applicable. A library whose input is missing must still
    load it and report that. When the index cannot be read, assume a library.
    """
    if (root / "pico.toml").is_file():
        return True
    try:
        rows = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--stage", "--", "infra"],
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        return True
    return any(row.split()[0] == "160000" for row in rows)


def load(root):
    """Return the validated family input; raise InputError when it cannot be read."""
    path = root / "pico.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise InputError(f"cannot read {path.name}: {error}") from error
    return validate(data)
