# SPDX-License-Identifier: MIT
"""Report committed infrastructure pins without product graph machinery (AR-5)."""

import pytest

from pico_tooling.metadata import InputError
from pico_tooling.report import report
from tests.conftest import git


def test_report_keeps_infra_pin_and_refuses_remote_inputs(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    git(root, "init", "--quiet", "--initial-branch=main")
    (root / "pico.toml").write_text('name="sample"\n[infra]\nrepository="r"\n')
    git(root, "add", "pico.toml")
    pin = "1" * 40
    git(root, "update-index", "--add", "--cacheinfo", f"160000,{pin},infra")
    git(root, "commit", "--quiet", "-m", "deps: pin the family")
    lines, problems = report([f"sample={root}"])
    assert problems == 0
    assert lines[0] == "library | infra"
    assert f"sample | {pin[:12]}" in lines
    with pytest.raises(InputError, match="local repository paths"):
        report(["sample=https://example.invalid/sample.git"])
