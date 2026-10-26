# SPDX-License-Identifier: MIT
"""What the footprint and symbols gates share: binutils, owned files, freshness.

A gate that cannot read its artefact raises UnavailableError; the gate reports
it as CANNOT_RUN, never as a pass (AR-11).
"""

import shutil
import subprocess

PREFIX = "arm-none-eabi-"
# Sources whose change makes an earlier build stale.
BUILT_FROM = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".s", ".S")

SYMBOL_SETS = {
    "allocating-formatter": ("image", r"^(_dtoa_r|_dtoa|_Balloc|_ldtoa_r)$"),
    "soft-float": ("objects", r"^__aeabi_[df]"),
    "c-heap": (
        "objects",
        (
            r"^(?:(?:m|c|re)alloc|free|_(?:(?:m|c|re)alloc|free)_r|"
            r"_Zn[aw][jmy](?:St11align_val_t)?(?:RKSt9nothrow_t)?|"
            r"_Zd[al]Pv[jmy]?(?:St11align_val_t)?(?:RKSt9nothrow_t)?)$"
        ),
    ),
    "c-heap-alloc": (
        "objects",
        (
            r"^(?:(?:m|c|re)alloc|_(?:m|c|re)alloc_r|"
            r"_Zn[aw][jmy](?:St11align_val_t)?(?:RKSt9nothrow_t)?)$"
        ),
    ),
}


class UnavailableError(Exception):
    """The artefact or a tool needed to read it is missing or unreadable."""


def tool(name, *args):
    """Run one binutils tool, found on PATH with the cross prefix, and return stdout."""
    found = shutil.which(PREFIX + name)
    if found is None:
        raise UnavailableError(f"{PREFIX}{name} is not on PATH")
    done = subprocess.run(
        [found, *args], capture_output=True, text=True, check=False,
    )
    if done.returncode:
        raise UnavailableError(
            f"{PREFIX}{name} could not read {args[-1]}: {done.stderr.strip()}",
        )
    return done.stdout


def owned_paths(root):
    """Return the resolved paths git tracks or does not ignore.

    They are this repository's own files, a staged one included, but not an SDK
    or a sibling fetched inside the checkout.
    """
    try:
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise UnavailableError(f"cannot list owned files: {error}") from error
    return frozenset((root / name).resolve() for name in listed.split("\0") if name)


def modified(path):
    try:
        return path.stat().st_mtime_ns
    except OSError as error:
        raise UnavailableError(f"cannot read {path}: {error}") from error


def newest_source(owned):
    """Return the newest modification time among the owned built-from sources."""
    return max(
        (modified(path) for path in owned if path.suffix in BUILT_FROM
         and path.is_file()),
        default=0,
    )


def require_fresh(artefact, owned):
    """Refuse an artefact older than an owned source, which its build did not see."""
    newest = newest_source(owned)
    if modified(artefact) < newest:
        raise UnavailableError(
            f"{artefact} is older than an owned source; rebuild before this gate",
        )
