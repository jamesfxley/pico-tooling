# SPDX-License-Identifier: MIT
"""A repository value in pico.toml is data and never a git option (AR-1, AR-3)."""

import pytest

from pico_tooling.releases import ChannelError, releases
from tests.conftest import commit, dev, family, git


def hostile(marker):
    return f"--upload-pack=touch {marker}"


def test_an_option_shaped_repository_is_refused_before_git_runs(library, tmp_path):
    marker = tmp_path / "marker"
    original = (library / "pico.toml").read_text()
    infra = original.replace(
        original.split('repository = "')[1].split('"')[0], hostile(marker),
    )
    expected = "a repository location must not start with '-'"
    for text, label in ((infra, "infra.repository"),):
        (library / "pico.toml").write_text(text)
        for done in (
            dev(library, "gate", "family-freshness"),
            dev(library, "gate", "family-files"),
            family(library, "sync"),
        ):
            output = done.stdout + done.stderr
            assert done.returncode == 2, output
            assert f"{label}: {expected}" in output
    assert not marker.exists()


def test_git_receives_the_repository_after_an_option_terminator(tmp_path, monkeypatch):
    marker = tmp_path / "marker"
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "--quiet", "--initial-branch=main")
    (origin / "README.md").write_text("# Origin\n")
    commit(origin, "docs: start")
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "--quiet", "--initial-branch=main")
    git(work, "remote", "add", "origin", str(origin))
    # Without the terminator git would read the value as --upload-pack and run
    # it against the working directory's own remote.
    monkeypatch.chdir(work)
    with pytest.raises(ChannelError):
        releases(hostile(marker))
    assert not marker.exists()
