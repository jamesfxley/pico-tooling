# SPDX-License-Identifier: MIT
"""Gate: static RAM and flash of a firmware image stay within budget (AR-11).

Each [[footprint]] table in pico.toml names one image. Static RAM is
allocated sections except read-only load images at their load address, heap
and stack reservations; flash is every loaded section. Owned flash counts
symbols from files under owned_prefix that git tracks or does not
ignore, so the SDK or a sibling fetched inside the checkout is never the
library's. An image attributing nothing to that prefix was built without debug
information and cannot satisfy an owned budget.

A missing image, an image older than an owned source, a missing binutils tool
and an unreadable table are CANNOT_RUN, never a pass.
"""

import os
from itertools import pairwise
from pathlib import Path

from house.api import Finding, Result

from .embedded import UnavailableError, owned_paths, require_fresh, tool
from .metadata import NOT_A_LIBRARY, InputError, is_library, load

KIB = 1024
RULE = "CXX-11.6"


def sections(elf):
    """Return placement-based (static RAM, flash) bytes from objdump -h."""
    ram = flash = 0
    lines = tool("objdump", "-h", str(elf)).splitlines()
    for header, detail in pairwise(lines):
        parts = header.split()
        if len(parts) < 7 or not parts[0].isdigit():
            continue
        name = parts[1]
        size, vma, lma = (int(value, 16) for value in parts[2:5])
        flags = set(detail.replace(",", " ").split())
        if "LOAD" in flags:
            flash += size
        if (
            "ALLOC" in flags
            and not ({"LOAD", "READONLY"} <= flags and vma == lma)
            and name != ".heap" and not name.startswith(".stack")
        ):
            ram += size
    return ram, flash


def owned_flash(elf, under, owned):
    """Return the bytes of code and read-only data defined under `under`."""
    total = 0
    listing = tool("nm", "--print-size", "--radix=d", "--line-numbers", str(elf))
    for line in listing.splitlines():
        fields, _, where = line.partition("\t")
        parts = fields.split()
        source = where.rsplit(":", 1)[0] if where else None
        if len(parts) != 4 or parts[2] not in "tTrR" or source is None:
            continue
        path = Path(source).resolve()
        if path in owned and under in (path, *path.parents):
            total += int(parts[1])
    return total


def measure(repo, item, owned):
    """Return (label, bytes, budget) rows for one image; raise UnavailableError."""
    elf = repo.root / item["elf"]
    if not elf.is_file():
        raise UnavailableError(f"no image at {item['elf']}; build the firmware first")
    require_fresh(elf, owned)
    ram, flash = sections(elf)
    if flash == 0:
        raise UnavailableError(f"{item['elf']} has no LOAD sections; no flash measured")
    rows = [
        ("static RAM", ram, item["ram_kib"]),
        ("flash", flash, item.get("flash_kib")),
    ]
    if "owned_kib" in item:
        under = (repo.root / item["owned_prefix"]).resolve()
        rows.append(("owned flash", owned_flash(elf, under, owned), item["owned_kib"]))
        if rows[-1][1] == 0:
            raise UnavailableError(
                f"{item['elf']} attributes nothing to {item['owned_prefix']}; "
                "build it with debug information",
            )
    return rows


def describe(item, rows):
    text = ", ".join(
        f"{label} {size / KIB:.1f} KiB" + (f" of {budget} KiB" if budget else "")
        for label, size, budget in rows
    )
    return f"{item['name']} ({item['elf']}): {text}"


class Footprint:
    name = "footprint"
    group = "firmware"
    rules = (RULE,)

    def applies(self, repo):
        if not is_library(repo.root):
            return NOT_A_LIBRARY
        try:
            return True if load(repo.root)["footprint"] else "no [[footprint]] table"
        except InputError:
            return True

    def run(self, repo, argv):
        if argv:
            return Result.cannot_run("footprint accepts no arguments")
        try:
            data = load(repo.root)
            owned = owned_paths(repo.root)
        except (InputError, UnavailableError) as error:
            return Result.cannot_run(f"family inputs unavailable: {error}")
        findings, reports, unavailable = [], [], []
        for item in data["footprint"]:
            unmet = [
                f"HOUSE_MATRIX_{axis.upper()}={value!r}"
                for axis, value in item.get("when", {}).items()
                if os.environ.get(f"HOUSE_MATRIX_{axis.upper()}") != value
            ]
            if unmet:
                reports.append(
                    f"{item['name']}: not applicable (requires {', '.join(unmet)})",
                )
                continue
            try:
                rows = measure(repo, item, owned)
            except UnavailableError as error:
                unavailable.append(f"{item['name']}: {error}")
                continue
            reports.append(describe(item, rows))
            findings.extend(
                Finding(
                    item["elf"],
                    0,
                    RULE,
                    f"{item['name']}: {label} {size / KIB:.1f} KiB exceeds its "
                    f"{budget} KiB budget",
                )
                for label, size, budget in rows
                if budget and size > budget * KIB
            )
        message = "; ".join([*reports, *unavailable])
        if findings:
            return Result.fail(*findings, message=message)
        if unavailable:
            return Result.cannot_run(message)
        return Result.ok("; ".join(reports))


GATE = Footprint()
