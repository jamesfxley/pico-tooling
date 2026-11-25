# SPDX-License-Identifier: MIT
"""These tests check that the wheel holds one self-contained Python package (AR-18).

No case builds a wheel or reaches the network. The wheel build and the import
in a clean environment are checked before each release (AR-18 verification).
"""

import os
import shutil
import subprocess
import sys
import tomllib

from tests.conftest import ROOT

PYPROJECT = ROOT / "pyproject.toml"
IMPORT = "import pico_tooling.device_proxy, pico_tooling.device_errors"


def copied_package(root):
    """Copy only the package's Python sources into a directory."""
    target = root / "pico_tooling"
    target.mkdir()
    for source in (ROOT / "pico_tooling").glob("*.py"):
        shutil.copyfile(source, target / source.name)
    return target


def import_package(root):
    """Run the import with no site packages, user site or inherited paths."""
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }
    code = f"import sys; sys.path.insert(0, {str(root)!r}); {IMPORT}"
    return subprocess.run(
        [sys.executable, "-I", "-S", "-c", code],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_the_build_settings_name_one_module_and_no_other():
    settings = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    backend = settings["build-system"]
    assert backend["build-backend"] == "uv_build"
    module = settings["tool"]["uv"]["build-backend"]
    assert module["module-name"] == "pico_tooling"
    assert module["module-root"] == ""
    assert "modules" not in module


def test_the_proxy_and_errors_import_with_the_standard_library_alone(tmp_path):
    copied_package(tmp_path)
    done = import_package(tmp_path)
    assert done.returncode == 0, done.stderr


def test_the_import_fails_when_a_module_needs_house(tmp_path):
    package = copied_package(tmp_path)
    errors = package / "device_errors.py"
    errors.write_text(errors.read_text(encoding="utf-8") + "\nimport house\n")
    done = import_package(tmp_path)
    assert done.returncode != 0, done.stdout
    assert "ModuleNotFoundError" in done.stderr, done.stderr
    assert "house" in done.stderr, done.stderr
