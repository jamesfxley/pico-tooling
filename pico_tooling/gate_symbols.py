# SPDX-License-Identifier: MIT
"""Gate: an image or the library's objects reach no forbidden symbol (AR-11).

Each [[symbols]] table in pico.toml names one directory of objects or one
image, and the sets to check:

    mode = "image"     what the image defines (allocating-formatter)
    mode = "objects"   what the library's own objects leave undefined
                       (soft-float, c-heap, c-heap-alloc)

An object is the library's when the compile database above its directory
records it as compiled from a source git tracks or does not ignore, so an SDK
source compiled into a target is not. A set asked in the mode that cannot see it
is refused when pico.toml is read: it would pass whatever the answer. A missing
input, a stale build and an unreadable database are CANNOT_RUN.

A table with expect = "refused" is a negative control. It names a fixture the
gate must refuse, and passes only when one of its own sets finds a symbol there;
a fixture that is clean, or refused only by another set, fails, because a
declaration that points at the wrong build output would otherwise pass for ever.
"""

import json
import re
from pathlib import Path

from house.api import Finding, Result

from .embedded import (
    SYMBOL_SETS,
    UnavailableError,
    modified,
    owned_paths,
    require_fresh,
    tool,
)
from .metadata import NOT_A_LIBRARY, InputError, is_library, load

RULE = "CXX-11.1"


def database_for(directory):
    above = (d / "compile_commands.json" for d in (directory, *directory.parents))
    database = next((path for path in above if path.is_file()), None)
    if database is None:
        raise UnavailableError(f"no compile_commands.json above {directory}")
    return database


def origins(database):
    try:
        entries = json.loads(database.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise UnavailableError(f"cannot read {database}: {error}") from error
    origin = {}
    for entry in entries:
        base = Path(entry.get("directory", database.parent))
        if "output" in entry:
            output = (base / entry["output"]).resolve()
            origin[output] = (base / entry["file"]).resolve()
    return origin


def own_objects(directory, owned):
    """Return the library's objects under `directory`, each fresh against its source."""
    objects = sorted(
        path for path in directory.rglob("*.o*")
        if path.suffix in (".o", ".obj") and ".dir" in path.as_posix()
    )
    if not objects:
        raise UnavailableError(
            f"no objects under {directory}; build the firmware first",
        )
    database = database_for(directory)
    origin = origins(database)
    unknown = [path for path in objects if path.resolve() not in origin]
    if unknown:
        raise UnavailableError(f"{unknown[0]} is not in {database}")
    mine = [path for path in objects if origin[path.resolve()] in owned]
    if not mine:
        raise UnavailableError(f"no object under {directory} is this repository's")
    for path in mine:
        if modified(path) < modified(origin[path.resolve()]):
            raise UnavailableError(
                f"{path} is older than its source; rebuild before this gate",
            )
    return mine


def inspect(repo, item, owned):
    """Return (files, symbols found); raise UnavailableError."""
    target = repo.root / item["path"]
    if item["mode"] == "image":
        if not target.is_file():
            raise UnavailableError(
                f"no image at {item['path']}; build the firmware first",
            )
        require_fresh(target, owned)
        files, option = [target], "--defined-only"
    else:
        if not target.is_dir():
            raise UnavailableError(
                f"no object directory at {item['path']}; build first",
            )
        files, option = own_objects(target, owned), "--undefined-only"
    symbols = [
        (path, line.split()[-1])
        for path in files
        for line in tool("nm", option, str(path)).splitlines()
        if line.strip()
    ]
    if item["mode"] == "image" and not symbols:
        raise UnavailableError(f"{item['path']} defines no symbols; it is stripped")
    return files, symbols


class Symbols:
    name = "symbols"
    group = "firmware"
    rules = (RULE,)

    def applies(self, repo):
        if not is_library(repo.root):
            return NOT_A_LIBRARY
        try:
            return True if load(repo.root)["symbols"] else "no [[symbols]] table"
        except InputError:
            return True

    def run(self, repo, argv):
        if argv:
            return Result.cannot_run("symbols accepts no arguments")
        try:
            data = load(repo.root)
            owned = owned_paths(repo.root)
        except (InputError, UnavailableError) as error:
            return Result.cannot_run(f"family inputs unavailable: {error}")
        findings, reports, unavailable = [], [], []
        for item in data["symbols"]:
            try:
                files, symbols = inspect(repo, item, owned)
            except UnavailableError as error:
                unavailable.append(f"{item['name']}: {error}")
                continue
            found = [
                Finding(
                    path.relative_to(repo.root) if path.is_relative_to(repo.root)
                    else path,
                    0, RULE, f"{item['name']}: {symbol} ({name})",
                )
                for name in item["sets"]
                for path, symbol in symbols
                if re.search(SYMBOL_SETS[name][1], symbol)
            ]
            report = (
                f"{item['name']}: {len(symbols)} symbol(s) in {len(files)} file(s), "
                f"against {', '.join(item['sets'])}"
            )
            if item.get("expect") == "refused":
                report += f"; control refused with {len(found)} finding(s)"
                if not found:
                    found = [
                        Finding(
                            item["path"], 0, RULE,
                            f"{item['name']}: control was not refused by "
                            f"{', '.join(item['sets'])}",
                        ),
                    ]
                else:
                    found = []
            reports.append(report)
            findings.extend(found)
        message = "; ".join([*reports, *unavailable])
        if findings:
            return Result.fail(*findings, message=message)
        if unavailable:
            return Result.cannot_run(message)
        return Result.ok("; ".join(reports))


GATE = Symbols()
