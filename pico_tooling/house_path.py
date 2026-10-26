# SPDX-License-Identifier: MIT
"""Reach the public API of the House this checkout pins, from a command line.

`dev.py` puts the pinned platform on the import path before a gate runs. A
command run as `python3 -m pico_tooling` has no such step, so it asks here.
"""

import importlib
import sys
from pathlib import Path


class ConfigDirectoryError(Exception):
    """The per-user configuration directory could not be resolved."""


def house_api():
    """Return the `house.api` module of the House pinned beside this package."""
    platform = Path(__file__).resolve().parent.parent / "house"
    if (platform / "house/__init__.py").is_file() and str(platform) not in sys.path:
        sys.path.append(str(platform))
    return importlib.import_module("house.api")


def pico_config_directory():
    """Return this user's pico configuration directory; House refuses a bad base."""
    api = house_api()
    try:
        return api.user_config_dir("pico")
    except api.CannotRunError as error:
        raise ConfigDirectoryError(str(error)) from error
