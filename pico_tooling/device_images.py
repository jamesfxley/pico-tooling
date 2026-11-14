# SPDX-License-Identifier: MIT
"""Image selection uses the supplied paths without accessing a board (AR-12)."""

import re
from pathlib import Path

from .device_errors import AMBIGUOUS, FAILED, RefusalError

SSID = re.compile(r"^PICO_[A-Z0-9_]+_WIFI_SSID", re.MULTILINE)
CACHE_LEVELS = 4


def built_images(build_dir, want=None):
    """Return the images in a build tree; a name narrows them to its directory.

    A name is the directory holding the image: an examples/ subdirectory, or one
    directly under the tree. Three depths are read, so no image is matched twice.
    """
    build_dir = Path(build_dir)
    if want:
        patterns = (f"examples/{want}/*.uf2", f"{want}/*.uf2")
    else:
        patterns = ("examples/*/*.uf2", "*.uf2", "*/*.uf2")
    found = []
    for pattern in patterns:
        found.extend(sorted(build_dir.glob(pattern)))
    return found


def resolve_uf2(build_dir, want=None):
    """Return the image to flash, or None when there is none.

    A path to an existing file wins. Several images, named or not, are listed
    and rejected as ambiguous.
    """
    if want and Path(want).is_file():
        return Path(want)
    found = built_images(build_dir, want)
    if len(found) > 1:
        listing = "".join(f"\n  {path}" for path in found)
        raise RefusalError(
            AMBIGUOUS, f"several images are built; name one of:{listing}",
        )
    return found[0] if found else None


def check_credentials(uf2):
    """Refuse an image built with an empty Wi-Fi SSID; return a warning or None.

    An empty PICO_<REPO>_WIFI_SSID in the build cache identifies firmware that
    cannot join Wi-Fi. A cache without the variable identifies an image that
    does not use Wi-Fi. A missing cache produces a warning.
    """
    uf2 = Path(uf2)
    probe = uf2.resolve().parent
    cache = None
    for _ in range(CACHE_LEVELS):
        if (probe / "CMakeCache.txt").is_file():
            cache = probe / "CMakeCache.txt"
            break
        probe = probe.parent
    if cache is None:
        return f"no CMakeCache.txt above {uf2}; cannot verify Wi-Fi credentials"
    text = cache.read_text(encoding="utf-8", errors="replace")
    found = SSID.search(text)
    if found is None or re.search(
        rf"^{found.group()}:STRING=.+", text, re.MULTILINE,
    ):
        return None
    variable = found.group()
    raise RefusalError(
        FAILED,
        f"{uf2} was built with an empty {variable} and cannot join a network.\n"
        "       Flashing it spends a cycle on an image nothing can talk to.\n\n"
        f"       Reconfigure its tree with credentials, then rebuild:\n"
        f"         cmake -B {cache.parent} -D{variable}='my-ssid' "
        f"-D{variable.removesuffix('_SSID')}_PASSWORD='my-password'",
    )
