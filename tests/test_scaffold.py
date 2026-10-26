# SPDX-License-Identifier: MIT
"""Scaffold through public init and refer to family routes (AR-2, AR-7)."""

import json
import re
import sys

from tests.conftest import commit, dev, git, run, scaffold

ROUTES = [
    ("Flashing a board", "infra/guides/device.md"),
    (
        "Firmware, footprint, allocation and sizing profiles",
        "infra/guides/constrained-targets/SKILL.md",
    ),
    ("Building, the family bootstrap and firmware gates", "infra/docs/build.md"),
    ("Starting a new library", "infra/docs/new-library.md"),
]
ROWS = [f"| {work} | `{path}` |" for work, path in ROUTES]
ROUTE = ROWS[0]


def test_scaffold_passes_ci_with_the_family_route(library, infra_source):
    checked = dev(library, "check", "--ci")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "family-files [standards/repository/default]: PASS" in checked.stdout
    text = (library / "AGENTS.md").read_text()
    assert "Before work, read `infra/agents/AGENTS.md`;" in text
    assert all(row in (library / "infra/agents/AGENTS.md").read_text() for row in ROWS)
    assert len(text.encode()) < 4096  # the instruction file stays under 4 KiB
    assert git(library, "status", "--porcelain") == ""
    assert git(library / "infra", "rev-parse", "HEAD") == git(
        infra_source, "rev-parse", "HEAD",
    )
    modules = (library / ".gitmodules").read_text()
    assert f"url = {infra_source}" in modules
    context = json.loads(dev(library, "context", "--json").stdout)
    assert any(
        "infra/house/guides/engineering-standard" in str(value).replace("\\", "/")
        for value in json.dumps(context).split('"')
    )


def test_a_hardcoded_platform_template_refuses_the_scaffold(tmp_path, infra_source):
    agents = infra_source / "house/templates/family/AGENTS.md"
    agents.write_text(agents.read_text() + "| Extra | `platform/extra.md` |\n")
    commit(infra_source / "house", "docs: add a route")
    commit(infra_source, "deps: move the platform pin")
    refused = run(
        sys.executable, "-m", "pico_tooling", "scaffold", tmp_path / "refused",
        "--name", "refused", "--infra-repository", str(infra_source),
        cwd=infra_source, check=False,
    )
    assert refused.returncode == 2
    assert "AGENTS.md hardcodes platform/" in refused.stderr


def test_the_scaffold_commit_subject_follows_the_commit_rule(library):
    # EN-07.2: <area>: <summary>, a listed area, imperative lowercase, 72 or
    # fewer characters, no final full stop. The commits gate also passes in
    # test_scaffold_passes_ci_with_the_family_route.
    subject = git(library, "log", "-1", "--format=%s")
    assert subject == "tooling: scaffold the library from the pico family template"
    assert len(subject) <= 72
    assert re.fullmatch(
        r"(?:build|ci|deps|docs|examples|release|tests|tooling): [a-z][^.]*[^.]",
        subject,
    )
    assert "Co-Authored-By" not in git(library, "log", "-1", "--format=%B")


def test_scaffold_history_records_only_the_distribution_url(tmp_path, infra_source):
    # AR-7: the local checkout path must never enter committed pin metadata.
    url = "https://example.invalid/distribution/pico-tooling.git"
    destination = tmp_path / "history library"
    run(sys.executable, "-m", "pico_tooling", "scaffold", destination,
        "--name", "pico-drv8833", "--infra-repository", url, cwd=infra_source)
    for revision in git(destination, "rev-list", "HEAD").splitlines():
        modules = git(destination, "show", f"{revision}:.gitmodules")
        assert f"url = {url}" in modules
        assert str(infra_source) not in modules


def test_scaffold_name_defines_the_cmake_package_and_targets(tmp_path, infra_source):
    # AR-7: distribution names map to CMake identifiers and option prefixes.
    destination = scaffold(
        infra_source, tmp_path / "named library", name="pico-drv8833",
    )
    cmake = (destination / "CMakeLists.txt").read_text()
    assert "project(pico_drv8833 VERSION" in cmake
    assert "pico_family_bootstrap(PICO_DRV8833)" in cmake
    assert "house_cxx_enable_sanitizers(PICO_DRV8833)" in cmake
    assert "house_cxx_add_strict_target(pico_drv8833_strict" in cmake
    assert "PACKAGE pico_drv8833 VERSION" in cmake
    assert (
        "NAMESPACE pico_drv8833 TARGETS pico_drv8833_value pico_drv8833_strict" in cmake
    )
    consumer = (destination / "tests/consumer/CMakeLists.txt").read_text()
    assert "find_package(pico_drv8833 0.1 CONFIG REQUIRED)" in consumer
    assert "pico_drv8833::value" in consumer
    assert (destination / "README.md").read_text().startswith("# pico-drv8833\n")


def test_scaffold_instructions_describe_a_library(library):
    # AR-2, AR-7: root instructions describe the consumer's repository role.
    text = (library / "AGENTS.md").read_text()
    assert "This repository is a library in a product family." in text
    assert "owns a product family's packages" not in text
