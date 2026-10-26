# SPDX-License-Identifier: MIT
"""CLI importability without POSIX board locks (AR-12)."""

import os
import subprocess
import sys

from tests.conftest import ROOT


def run_isolated(code, **environ):
    """Run `code` with this checkout importable but not House, as a user would."""
    program = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n{code}"
    return subprocess.run(
        [sys.executable, "-I", "-c", program], capture_output=True, text=True,
        check=False, env={"PATH": os.environ["PATH"], **environ}, cwd=ROOT,
    )


def test_the_command_line_finds_the_house_this_checkout_pins(tmp_path):
    done = run_isolated(
        "from pico_tooling.house_path import pico_config_directory\n"
        "print(pico_config_directory())\n",
        HOUSE_CONFIG_HOME=str(tmp_path),
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == str(tmp_path / "pico")


def test_a_host_without_fcntl_refuses_the_device_commands_with_status_two():
    done = run_isolated(
        "sys.modules['fcntl'] = None\n"
        "from pico_tooling.__main__ import main\n"
        "sys.exit(main(['device', 'list']))\n",
    )
    assert done.returncode == 2
    assert "need a POSIX host" in done.stderr
    assert "Traceback" not in done.stderr
    assert done.stdout == ""


def test_a_host_without_fcntl_still_runs_the_other_commands():
    done = run_isolated(
        "sys.modules['fcntl'] = None\n"
        "from pico_tooling.__main__ import parser\n"
        "print(parser().parse_args(['sync', '--check']).command)\n",
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "sync"
