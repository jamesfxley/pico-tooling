# SPDX-License-Identifier: MIT
"""Owner boundary, repairable outputs and unavailable inputs (AR-1, AR-2)."""

import pytest

from tests.conftest import dev, family, git


def test_missing_edited_and_unindexed_bootstrap(library):
    name = "cmake/pico_family_bootstrap.cmake"
    assert 'set(PICO_FAMILY_INFRA_VERSION "0.1.0")' in (library / name).read_text()
    path = library / name
    original = path.read_text()
    for change, message in ((None, "missing generated output"),
                            (original + "# edit\n", "generated output differs")):
        if change is None:
            path.unlink()
        else:
            path.write_text(change)
        checked = dev(library, "gate", "family-files")
        assert checked.returncode == 1, checked.stdout
        assert f"{name}:0: AR-2: {message}" in checked.stdout
        assert family(library, "sync").returncode == 0
        assert path.read_text() == original
    git(library, "rm", "--cached", "--quiet", name)
    checked = dev(library, "gate", "family-files")
    assert checked.returncode == 1
    assert "generated output is not indexed" in checked.stdout


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("name = [", "cannot read pico.toml"),
        (b"\xff", "cannot read pico.toml"),
        ('name = "x"\n', "pico.toml: infra: is required"),
        ('name = "x"\nextra = 1\n[infra]\nrepository = "r"\n', "unknown keys"),
        ('name = "Bad"\n[infra]\nrepository = "r"\n', "lowercase letters"),
        (
            (
                'name = "x"\n[infra]\nrepository = "r"\n'
                '[dependencies.util]\nrepository = "u"\nrevision = "abc1234"\n'
            ),
            "unknown keys",
        ),
        (
            (
                'name = "x"\n[infra]\nrepository = "r"\n[dependencies.util]\n'
                f'repository = "u"\nrevision = "{"a" * 40}"\nprefixes = "../p.txt"\n'
            ),
            "unknown keys",
        ),
    ],
)
def test_unreadable_or_invalid_input_cannot_run(library, text, expected):
    target = library / "pico.toml"
    if isinstance(text, bytes):
        target.write_bytes(text)
    else:
        target.write_text(text)
    checked = dev(library, "gate", "family-files")
    assert checked.returncode == 2, checked.stdout
    assert expected in checked.stdout
    synced = family(library, "sync")
    assert synced.returncode == 2
    assert expected in synced.stderr


@pytest.mark.parametrize("gate", ["family-files", "family-freshness"])
def test_a_library_without_its_input_cannot_run_but_the_infrastructure_skips(
    library, infra_source, gate,
):
    (library / "pico.toml").unlink()
    checked = dev(library, "gate", gate)
    assert checked.returncode == 2, checked.stdout
    assert "cannot read pico.toml" in checked.stdout
    assert "SKIP" not in checked.stdout
    # The infrastructure repository has neither an input nor an infra pin.
    skipped = dev(infra_source, "gate", gate)
    assert skipped.returncode == 0, skipped.stdout
    assert f"{gate} [" in skipped.stdout
    assert "SKIP" in skipped.stdout
    assert "infrastructure repository: no pico.toml and no infra pin" in skipped.stdout


def test_a_library_without_its_input_fails_the_whole_check(library):
    (library / "pico.toml").unlink()
    for arguments in (("check",), ("check", "--ci")):
        checked = dev(library, *arguments)
        assert checked.returncode == 2, checked.stdout
        assert "cannot read pico.toml" in checked.stdout
