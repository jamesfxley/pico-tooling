# SPDX-License-Identifier: MIT
"""A scaffold refers to real pinned family modules and House (AR-2, AR-7)."""

import json
import re
import sys
import tomllib

from pico_tooling import __version__
from pico_tooling.render import version
from tests.conftest import dev, family, run, scaffold


def test_real_family_layers_work_without_adapters(tmp_path, infra_source):
    root = scaffold(infra_source, tmp_path / "layered library", "cxx")
    assert not (root / "tools").exists()
    assert not (root / "tests/.clang-tidy").exists()
    assert 'family = "infra"' in (root / "house.toml").read_text()
    assert "house_cxx_enable_sanitizers(SAMPLE_LIBRARY)" in (
        (root / "CMakeLists.txt").read_text()
    )
    assert "Before work, read `infra/agents/AGENTS.md`;" in (
        (root / "AGENTS.md").read_text()
    )
    script = (
        "import json; from pathlib import Path; from house.api import Repo; "
        "from house.config import load; from house.cli import runner; "
        "from house.trees import trees; "
        "r=Repo(Path.cwd(),load(Path.cwd())); e=runner(r); "
        "print(json.dumps({'gates':[g.name for g in e.gates], "
        "'trees':[t.name for t in trees(r)]}))"
    )
    loaded = run(
        sys.executable, "-c", script, cwd=root,
        env={"PYTHONPATH": str(root / "infra/house"),
             "HOUSE_MATRIX_SANITIZE": "ON", "PICO_SDK_PATH": "/sdk"},
    )
    result = json.loads(loaded.stdout)
    assert set(result["gates"]) >= {
        "family-files", "footprint", "symbols", "family-freshness",
        "build:firmware", "lint:firmware", "build:sanitize", "lint:sanitize",
    }
    assert result["trees"] == ["host", "firmware", "sanitize"]
    container = json.loads((root / ".devcontainer/devcontainer.json").read_text())
    assert container["name"] == "pico family"
    assert container["build"] == {
        "dockerfile": "../infra/.devcontainer/Dockerfile", "context": "../infra",
    }
    assert container["runArgs"] == [
        "--security-opt",
        "seccomp=${localWorkspaceFolder}/infra/.devcontainer/seccomp.json",
    ]
    vscode = container["customizations"]["vscode"]
    assert vscode["settings"]["editor.formatOnSave"] is True
    assert "llvm-vs-code-extensions.vscode-clangd" in vscode["extensions"]
    workflow = (root / ".github/workflows/ci.yml").read_text()
    assert "Prepare lint input 1" in workflow
    assert "Prepare firmware input 2" in workflow
    assert "python3 dev.py gate build-warnings" in workflow
    with (root / "house.toml").open("a") as stream:
        stream.write('\n[[ci.require]]\ngroup="lint"\nprepare=["python3 local.py"]\n')
    assert dev(root, "sync").returncode == 0
    workflow = (root / ".github/workflows/ci.yml").read_text()
    assert '"run": "python3 local.py"' in workflow
    config = run(
        sys.executable, "-c",
        "from pathlib import Path; from house.config import load; "
        "print([r for r in load(Path.cwd())['ci']['require'] if r['group']=='lint'])",
        cwd=root, env={"PYTHONPATH": str(root / "infra/house")},
    ).stdout
    assert "python3 dev.py build" not in config
    target = root / "cmake/pico_family_bootstrap.cmake"
    target.write_text(target.read_text() + "# edited\n")
    checked = dev(root, "gate", "family-files")
    assert checked.returncode == 1
    assert "cmake/pico_family_bootstrap.cmake:0: AR-2: generated output differs" in (
        checked.stdout
    )
    assert family(root, "sync").returncode == 0
    assert dev(root, "gate", "family-files").returncode == 0


def test_release_version_matches_build_metadata():
    assert __version__ == version()


def workflow_model(library):
    script = (
        "import json; from pathlib import Path; from house.api import Repo; "
        "from house.config import load; from house.workflow import model; "
        "print(json.dumps(model(Repo(Path.cwd(),load(Path.cwd())))))"
    )
    return json.loads(run(
        sys.executable, "-c", script, cwd=library,
        env={"PYTHONPATH": str(library / "infra/house")},
    ).stdout)


def test_library_jobs_inherit_the_pinned_family_image(library):
    # AR-2: hosted library CI runs in the family image pinned by digest.
    family_config = tomllib.loads((library / "infra/family.toml").read_text())
    image = family_config["ci"]["container"]
    assert re.fullmatch(r"ghcr\.io/jamesfxley/pico-tooling@sha256:[0-9a-f]{64}", image)
    data = workflow_model(library)
    containers = [job["container"] for job in data["jobs"].values()]
    assert containers
    assert all(container["image"] == image for container in containers)


def test_family_container_user_survives_repository_job_overrides(library):
    # AR-2: the inherited user applies even when repository require rows replace
    # family rows, including a group that already declares container options.
    config = library / "house.toml"
    declaration = 'container = "example.invalid/ci@sha256:' + "a" * 64 + '"\n'
    text = config.read_text().replace("[ci]\n", "[ci]\n" + declaration)
    config.write_text(
        text + '\n[[ci.require]]\ngroup="lint"\n'
        'container_options="--security-opt seccomp=unconfined"\n',
    )
    data = workflow_model(library)
    containers = [job["container"] for job in data["jobs"].values()]
    assert containers
    assert all(container["options"].endswith("--user 0") for container in containers)
    assert data["jobs"]["check_lint"]["container"]["options"] == (
        "--security-opt seccomp=unconfined --user 0"
    )
