# SPDX-License-Identifier: MIT
"""Infra freshness against annotated release tags and warning annotations (AR-3)."""

import pytest

from pico_tooling.gate_freshness import verdict
from pico_tooling.metadata import InputError, validate
from tests.conftest import commit, dev, git


def release(infra_source, tag, *, annotated=True):
    (infra_source / "CHANGELOG.md").write_text(f"# {tag}\n")
    commit(infra_source, f"docs: prepare {tag}")
    if annotated:
        git(infra_source, "tag", "-a", tag, "-m", f"Release {tag}")
    else:
        git(infra_source, "tag", tag)


def freshness(library):
    done = dev(library, "gate", "family-freshness")
    return done.returncode, done.stdout + done.stderr


def test_current_annotated_release_passes(library):
    status, text = freshness(library)
    assert status == 0, text
    assert "infra pin is the current release v0.1.0" in text


def test_stale_pin_warns_and_prereleases_are_ignored(library, infra_source):
    release(infra_source, "v0.2.0")
    release(infra_source, "v0.3.0-rc1")
    release(infra_source, "latest", annotated=False)
    status, text = freshness(library)
    assert status == 0
    assert "infra pin v0.1.0 is behind the current release v0.2.0" in text


def test_unreadable_or_empty_channel_cannot_run(library, tmp_path):
    text = (library / "pico.toml").read_text()
    source = text.split('repository = "')[1].split('"')[0]
    (library / "pico.toml").write_text(text.replace(source, str(tmp_path / "absent")))
    status, output = freshness(library)
    assert status == 2
    assert "cannot read release tags from" in output
    untagged = tmp_path / "untagged"
    untagged.mkdir()
    git(untagged, "init", "--quiet")
    (untagged / "README.md").write_text("# Untagged\n")
    commit(untagged, "docs: start")
    (library / "pico.toml").write_text(text.replace(source, str(untagged)))
    status, output = freshness(library)
    assert status == 2
    assert "no vX.Y.Z release tags at" in output


def test_an_untagged_pin_is_described_as_unreleased():
    found = {(0, 1, 0): ("v0.1.0", "a" * 40)}
    result = verdict("b" * 40, found)
    assert result.status == 0
    assert "unreleased commit bbbbbbbbbbbb is behind" in result.message


def test_versions_compare_numerically_not_lexically(library, infra_source):
    release(infra_source, "v1.9.0")
    release(infra_source, "v1.10.0")
    release(infra_source, "v1.2.0")
    status, text = freshness(library)
    assert status == 0
    assert "infra pin v0.1.0 is behind the current release v1.10.0" in text


def test_a_lightweight_tag_is_not_a_release(library, infra_source, tmp_path):
    release(infra_source, "v0.2.0", annotated=False)
    status, text = freshness(library)
    assert status == 0, text
    assert "infra pin is the current release v0.1.0" in text
    lightweight = tmp_path / "lightweight"
    lightweight.mkdir()
    git(lightweight, "init", "--quiet", "--initial-branch=main")
    (lightweight / "README.md").write_text("# Lightweight\n")
    commit(lightweight, "docs: start")
    git(lightweight, "tag", "v0.1.0")
    pico = (library / "pico.toml").read_text()
    source = pico.split('repository = "')[1].split('"')[0]
    (library / "pico.toml").write_text(pico.replace(source, str(lightweight)))
    status, text = freshness(library)
    assert status == 2
    assert "no vX.Y.Z release tags at" in text



@pytest.mark.parametrize("actions", ["true", "false", ""])
def test_stale_warning_is_printed_at_column_zero(
    library, infra_source, monkeypatch, actions,
):
    monkeypatch.setenv("GITHUB_ACTIONS", actions)
    release(infra_source, "v0.2.0")
    status, output = freshness(library)
    print(output, end="")
    message = "infra pin v0.1.0 is behind the current release v0.2.0; adopt it"
    assert status == 0, output
    assert message in output.splitlines()
    annotation = "::warning title=family-freshness::" + message
    assert (annotation in output.splitlines()) == (actions == "true")


def test_infra_deferral_is_refused_by_name():
    with pytest.raises(InputError, match=r"infra: unknown keys.*deferral"):
        validate({"name": "sample", "infra": {"repository": "r", "deferral": []}})
