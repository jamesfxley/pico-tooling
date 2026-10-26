# SPDX-License-Identifier: MIT
"""The footprint and symbols gates against synthetic images, nm and size output.

An image or object is a JSON file; the fake arm-none-eabi-size and -nm tools
print what it holds, so no cross toolchain is needed and every number is chosen
by the test (AR-11).
"""

import json
import os
import shutil
from pathlib import Path

import pytest
from house.api import Repo

from pico_tooling.gate_footprint import GATE as FOOTPRINT
from pico_tooling.gate_footprint import sections
from pico_tooling.gate_symbols import GATE as SYMBOLS
from tests.conftest import git

pytestmark = pytest.mark.usefixtures("binutils")
KIB = 1024
PICO = 'name = "sample"\n[infra]\nrepository = "r"\n'
SOURCE = "int main(void) { return 0; }\n"


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    git(root, "init", "--quiet", "--initial-branch=main")
    (root / ".gitignore").write_text("build/\n", encoding="utf-8")
    write(root, "src/main.c", SOURCE)
    write(root, "pico.toml", PICO)
    git(root, "add", "--all")
    return root


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def declare(root, text):
    write(root, "pico.toml", PICO + text)
    return Repo(root, {"house": {"platform": "house"}})


def newer(root, path, *, by=100):
    """Date `path` after every owned source, as a build run afterwards would."""
    stamp = (root / "src/main.c").stat().st_mtime + by
    os.utime(path, (stamp, stamp))


def image(root, *, ram=4096, flash=2048, symbols=(), by=100):
    name = "build/app.elf"
    sections = {".text": flash // 2, ".rodata": flash // 2, ".bss": ram}
    path = write(root, name, json.dumps({"sections": sections, "symbols": symbols}))
    newer(root, path, by=by)
    return name


def owned(root, size=512):
    return [[size, "T", f"{root / 'src/main.c'}:1"], [4096, "T", "/sdk/boot.c:9"]]


def table(**values):
    lines = ["[[footprint]]", 'name = "bench"', 'elf = "build/app.elf"']
    lines += [f"{key} = {value}" for key, value in values.items()]
    return "\n".join(lines) + "\n"


def verdict(gate, repo):
    result = gate.run(repo, ())
    return result.status, result.message, [item.message for item in result.findings]


# -- footprint: the eight cases of the old gate ------------------------------


def test_an_image_within_budget_passes(tree):
    image(tree)
    status, message, _ = verdict(FOOTPRINT, declare(tree, table(ram_kib=8)))
    assert status == 0
    assert "static RAM 4.0 KiB of 8 KiB" in message


@pytest.mark.parametrize("profile", [None, "default", "p8-rp2350"])
def test_footprint_conditions_select_only_matching_rows(tree, monkeypatch, profile):
    """AR-11: unmet rows are reported without being measured or passed."""
    monkeypatch.delenv("HOUSE_MATRIX_PROFILE", raising=False)
    if profile is not None:
        monkeypatch.setenv("HOUSE_MATRIX_PROFILE", profile)
    image(tree)
    base = table(ram_kib=8)
    conditional = table(ram_kib=2, when='{ profile = "p8-rp2350" }')
    conditional = conditional.replace('name = "bench"', 'name = "tight"')
    status, message, found = verdict(FOOTPRINT, declare(tree, base + conditional))
    assert "bench (build/app.elf): static RAM 4.0 KiB of 8 KiB" in message
    if profile == "p8-rp2350":
        assert status == 1
        assert found == ["tight: static RAM 4.0 KiB exceeds its 2 KiB budget"]
        assert "not applicable" not in message
    else:
        assert status == 0
        assert found == []
        assert (
            "tight: not applicable (requires HOUSE_MATRIX_PROFILE='p8-rp2350')"
            in message
        )
        assert "tight (build/app.elf)" not in message


def test_unmet_conditions_are_reported_even_when_another_image_is_missing(
    tree, monkeypatch,
):
    """AR-11: unavailable measurements do not hide informational conditions."""
    monkeypatch.delenv("HOUSE_MATRIX_PROFILE", raising=False)
    conditional = table(ram_kib=2, when='{ profile = "large" }')
    conditional = conditional.replace('name = "bench"', 'name = "tight"')
    status, message, _ = verdict(
        FOOTPRINT, declare(tree, table(ram_kib=8) + conditional),
    )
    assert status == 2
    assert "bench: no image at build/app.elf" in message
    assert "tight: not applicable (requires HOUSE_MATRIX_PROFILE='large')" in message


def test_footprint_conditions_require_every_axis_before_opening_an_image(
    tree, monkeypatch,
):
    """AR-11: a matching profile alone cannot satisfy a second condition."""
    monkeypatch.setenv("HOUSE_MATRIX_PROFILE", "large")
    monkeypatch.delenv("HOUSE_MATRIX_BOARD", raising=False)
    repo = declare(
        tree, table(ram_kib=8, when='{ profile = "large", board = "sample" }'),
    )
    status, message, found = verdict(FOOTPRINT, repo)
    assert status == 0
    assert found == []
    assert "bench: not applicable (requires HOUSE_MATRIX_BOARD='sample')" in message
    monkeypatch.setenv("HOUSE_MATRIX_BOARD", "sample")
    status, message, _ = verdict(FOOTPRINT, repo)
    assert status == 2
    assert "no image at build/app.elf" in message


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        ('"large"', "footprint[1].when: expected a table"),
        ("[]", "footprint[1].when: expected a table"),
        ("{ profile = 1 }", "footprint[1].when.profile: expected a nonempty string"),
        ('{ profile = "" }', "footprint[1].when.profile: expected a nonempty string"),
        ('{ profile = "  " }', "footprint[1].when.profile: expected a nonempty string"),
        (
            '{ Profile = "large" }',
            "footprint[1].when.Profile: expected a valid lowercase axis name",
        ),
        (
            '{ "bad-axis" = "large" }',
            "footprint[1].when.bad-axis: expected a valid lowercase axis name",
        ),
        (
            '{ "" = "large" }',
            "footprint[1].when.: expected a valid lowercase axis name",
        ),
    ],
)
def test_malformed_footprint_conditions_are_refused_by_name(tree, when, expected):
    """AR-11: condition errors cannot silently skip a budget."""
    status, message, _ = verdict(FOOTPRINT, declare(tree, table(ram_kib=8, when=when)))
    assert status == 2
    assert expected in message


def test_an_image_over_its_static_ram_budget_is_refused(tree):
    image(tree)
    status, _, found = verdict(FOOTPRINT, declare(tree, table(ram_kib=2)))
    assert status == 1
    assert found == ["bench: static RAM 4.0 KiB exceeds its 2 KiB budget"]


def test_an_image_over_its_flash_budget_is_refused(tree):
    image(tree)
    repo = declare(tree, table(ram_kib=8, flash_kib=0.01))
    status, _, found = verdict(FOOTPRINT, repo)
    assert status == 1
    assert found == ["bench: flash 2.0 KiB exceeds its 0.01 KiB budget"]


def test_owned_flash_is_attributed_from_debug_information(tree):
    image(tree, symbols=owned(tree))
    repo = declare(tree, table(ram_kib=8, owned_prefix='"src"', owned_kib=4))
    status, message, _ = verdict(FOOTPRINT, repo)
    assert status == 0
    assert "owned flash 0.5 KiB of 4 KiB" in message


def test_owned_flash_over_its_budget_is_refused(tree):
    image(tree, symbols=owned(tree, size=2048))
    repo = declare(tree, table(ram_kib=8, owned_prefix='"src"', owned_kib=1))
    status, _, found = verdict(FOOTPRINT, repo)
    assert status == 1
    assert found == ["bench: owned flash 2.0 KiB exceeds its 1 KiB budget"]


def test_an_image_attributing_nothing_cannot_run(tree):
    image(tree, symbols=[[4096, "T", "/sdk/boot.c:9"]])
    repo = declare(tree, table(ram_kib=8, owned_prefix='"src"', owned_kib=4))
    status, message, _ = verdict(FOOTPRINT, repo)
    assert status == 2
    assert "attributes nothing to src; build it with debug information" in message


@pytest.mark.parametrize("budget", ["0", "-1", "nan", "inf", '"x"', "true"])
def test_a_budget_that_is_not_a_positive_number_cannot_run(tree, budget):
    image(tree)
    status, message, _ = verdict(FOOTPRINT, declare(tree, table(ram_kib=budget)))
    assert status == 2
    assert "ram_kib: expected a positive, finite number of KiB" in message


def test_a_missing_image_cannot_run(tree):
    status, message, _ = verdict(FOOTPRINT, declare(tree, table(ram_kib=1)))
    assert status == 2
    assert "bench: no image at build/app.elf; build the firmware first" in message


# -- footprint: stale builds and unavailable tools ---------------------------


def test_an_image_older_than_an_owned_source_cannot_run(tree):
    image(tree, by=-100)
    status, message, _ = verdict(FOOTPRINT, declare(tree, table(ram_kib=8)))
    assert status == 2
    assert "older than an owned source; rebuild" in message


def test_a_tool_missing_from_path_cannot_run(tree, tmp_path, monkeypatch):
    image(tree)
    repo = declare(tree, table(ram_kib=8))
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "git").symlink_to(shutil.which("git"))
    monkeypatch.setenv("PATH", str(bare))
    status, message, _ = verdict(FOOTPRINT, repo)
    assert status == 2
    assert "arm-none-eabi-objdump is not on PATH" in message


def test_an_unavailable_image_hides_no_other_failure(tree):
    image(tree)
    second = table(ram_kib=1).replace("bench", "other").replace("app.elf", "gone.elf")
    repo = declare(tree, table(ram_kib=1) + "\n" + second)
    status, message, found = verdict(FOOTPRINT, repo)
    assert status == 1
    assert found == ["bench: static RAM 4.0 KiB exceeds its 1 KiB budget"]
    assert "other: no image at build/gone.elf" in message


def test_the_gate_takes_no_arguments(tree):
    result = FOOTPRINT.run(declare(tree, table(ram_kib=1)), ("--x",))
    assert result.status == 2


# -- symbols: the eight cases of the old gate --------------------------------


def objects(root, sources, *, origin=None, by=100):
    """Write one object per source under build/t.dir and a database for them."""
    entries = []
    for name, symbols in sources.items():
        source = (origin or root / "src") / f"{name}.c"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(SOURCE, encoding="utf-8")
        path = write(root, f"build/t.dir/{name}.c.o",
                     json.dumps({"undefined": symbols}))
        stamp = source.stat().st_mtime + by
        os.utime(path, (stamp, stamp))
        entries.append({"directory": str(root), "file": str(source),
                        "output": str(path), "command": "cc"})
    write(root, "build/compile_commands.json", json.dumps(entries))
    return "build/t.dir"


def listed(where, *names, mode="objects"):
    sets = ", ".join(f'"{name}"' for name in names)
    return (f'[[symbols]]\nname = "probe"\nmode = "{mode}"\npath = "{where}"\n'
            f"sets = [{sets}]\n")


def test_an_object_reaching_the_heap_is_refused(tree):
    where = objects(tree, {"a": ["malloc", "printf"]})
    status, _, found = verdict(SYMBOLS, declare(tree, listed(where, "c-heap")))
    assert status == 1
    assert found == ["probe: malloc (c-heap)"]


def test_objects_that_do_not_allocate_pass(tree):
    where = objects(tree, {"a": ["memcpy"]})
    status, message, _ = verdict(SYMBOLS, declare(tree, listed(where, "c-heap")))
    assert status == 0
    assert "1 symbol(s) in 1 file(s), against c-heap" in message


def test_an_sdk_object_is_not_this_repository_s(tree, tmp_path):
    sdk = tmp_path / "sdk"
    where = objects(tree, {"sdk": ["malloc"]}, origin=sdk)
    objects_after = objects(tree, {"own": ["memcpy"]})
    assert where == objects_after
    # Rewrite the database to hold both, as one build tree would.
    first = json.loads((tree / "build/compile_commands.json").read_text())
    objects(tree, {"sdk": ["malloc"]}, origin=sdk)
    second = json.loads((tree / "build/compile_commands.json").read_text())
    write(tree, "build/compile_commands.json", json.dumps(first + second))
    status, message, _ = verdict(SYMBOLS, declare(tree, listed(where, "c-heap")))
    assert status == 0
    assert "1 file(s)" in message


def test_a_tree_holding_none_of_this_repository_s_objects_cannot_run(
    tree, tmp_path,
):
    where = objects(tree, {"sdk": ["malloc"]}, origin=tmp_path / "sdk")
    status, message, _ = verdict(SYMBOLS, declare(tree, listed(where, "c-heap")))
    assert status == 2
    assert "is this repository's" in message


def test_a_set_asked_in_the_wrong_mode_is_refused_when_pico_toml_is_read(tree):
    status, message, _ = verdict(
        SYMBOLS, declare(tree, listed("build", "allocating-formatter")),
    )
    assert status == 2
    assert "allocating-formatter is an image check; mode is 'objects'" in message
    status, message, _ = verdict(
        SYMBOLS, declare(tree, listed("build", "c-heap", mode="image")),
    )
    assert status == 2
    assert "c-heap is an objects check; mode is 'image'" in message


def test_an_unknown_set_and_an_empty_tree_are_errors(tree):
    status, message, _ = verdict(SYMBOLS, declare(tree, listed("build", "nonsense")))
    assert status == 2
    assert "unknown set 'nonsense'" in message
    (tree / "build").mkdir()
    status, message, _ = verdict(SYMBOLS, declare(tree, listed("build", "c-heap")))
    assert status == 2
    assert "no objects under" in message


def test_an_image_defining_a_forbidden_symbol_is_refused(tree):
    write(tree, "build/a.elf", json.dumps({"defined": ["_dtoa_r", "main"]}))
    newer(tree, tree / "build/a.elf")
    repo = declare(tree, listed("build/a.elf", "allocating-formatter", mode="image"))
    status, _, found = verdict(SYMBOLS, repo)
    assert status == 1
    assert found == ["probe: _dtoa_r (allocating-formatter)"]


def test_an_image_free_of_the_set_passes(tree):
    write(tree, "build/a.elf", json.dumps({"defined": ["main"]}))
    newer(tree, tree / "build/a.elf")
    repo = declare(tree, listed("build/a.elf", "allocating-formatter", mode="image"))
    assert verdict(SYMBOLS, repo)[0] == 0


# -- symbols: negative controls ----------------------------------------------


def control(where, *names, mode="objects"):
    return listed(where, *names, mode=mode) + 'expect = "refused"\n'


def test_a_control_the_gate_refuses_passes_and_says_so(tree):
    where = objects(tree, {"a": ["malloc"]})
    status, message, found = verdict(SYMBOLS, declare(tree, control(where, "c-heap")))
    assert status == 0
    assert found == []
    assert "control refused with 1 finding(s)" in message


def test_a_control_the_gate_does_not_refuse_fails_naming_it(tree):
    where = objects(tree, {"a": ["memcpy"]})
    status, _, found = verdict(SYMBOLS, declare(tree, control(where, "c-heap")))
    assert status == 1
    assert found == ["probe: control was not refused by c-heap"]


def test_a_control_refused_only_by_another_set_fails(tree):
    where = objects(tree, {"a": ["malloc"]})
    toml = control(where, "soft-float")
    status, _, found = verdict(SYMBOLS, declare(tree, toml))
    assert status == 1
    assert found == ["probe: control was not refused by soft-float"]


def test_a_control_with_a_missing_input_still_cannot_run(tree):
    status, message, _ = verdict(SYMBOLS, declare(tree, control("absent", "c-heap")))
    assert status == 2
    assert "no object directory at absent" in message


def test_a_control_and_a_real_declaration_are_judged_separately(tree):
    for name, symbol in (("clean", "main"), ("dirty", "_dtoa_r")):
        write(tree, f"build/{name}.elf", json.dumps({"defined": [symbol]}))
        newer(tree, tree / f"build/{name}.elf")
    real = listed("build/clean.elf", "allocating-formatter", mode="image")
    bad = control("build/dirty.elf", "allocating-formatter", mode="image")
    bad = bad.replace('name = "probe"', 'name = "control"')
    status, message, found = verdict(SYMBOLS, declare(tree, real + bad))
    assert status == 0, found
    assert "control: 1 symbol(s) in 1 file(s)" in message
    swapped = real.replace("clean", "dirty") + bad.replace("dirty", "clean")
    status, _, found = verdict(SYMBOLS, declare(tree, swapped))
    assert status == 1
    assert found == [
        "probe: _dtoa_r (allocating-formatter)",
        "control: control was not refused by allocating-formatter",
    ]


def test_expect_accepts_only_refused(tree):
    where = objects(tree, {"a": ["malloc"]})
    toml = listed(where, "c-heap") + 'expect = "passed"\n'
    status, message, _ = verdict(SYMBOLS, declare(tree, toml))
    assert status == 2
    assert "symbols[1].expect: expected 'refused'" in message


# -- symbols: stale builds, unreadable inputs, one mutation per set ----------


def test_an_object_older_than_its_source_cannot_run(tree):
    where = objects(tree, {"a": ["memcpy"]}, by=-100)
    status, message, _ = verdict(SYMBOLS, declare(tree, listed(where, "c-heap")))
    assert status == 2
    assert "is older than its source; rebuild" in message


def test_a_stale_or_stripped_or_missing_image_cannot_run(tree):
    write(tree, "build/a.elf", json.dumps({"defined": ["main"]}))
    newer(tree, tree / "build/a.elf", by=-100)
    toml = listed("build/a.elf", "allocating-formatter", mode="image")
    assert "older than an owned source" in verdict(SYMBOLS, declare(tree, toml))[1]
    write(tree, "build/a.elf", json.dumps({"defined": []}))
    newer(tree, tree / "build/a.elf")
    assert "defines no symbols" in verdict(SYMBOLS, declare(tree, toml))[1]
    (tree / "build/a.elf").unlink()
    assert "no image at build/a.elf" in verdict(SYMBOLS, declare(tree, toml))[1]


def test_a_missing_compile_database_cannot_run(tree):
    where = objects(tree, {"a": ["memcpy"]})
    (tree / "build/compile_commands.json").unlink()
    status, message, _ = verdict(SYMBOLS, declare(tree, listed(where, "c-heap")))
    assert status == 2
    assert "no compile_commands.json above" in message


def test_an_object_absent_from_the_database_cannot_run(tree):
    where = objects(tree, {"a": ["memcpy"]})
    write(tree, "build/compile_commands.json", "[]")
    status, message, _ = verdict(SYMBOLS, declare(tree, listed(where, "c-heap")))
    assert status == 2
    assert "is not in" in message


@pytest.mark.parametrize(
    ("name", "mode", "forbidden", "allowed"),
    [
        ("allocating-formatter", "image", "_Balloc", "_Balloc_x"),
        ("soft-float", "objects", "__aeabi_dadd", "__aeabi"),
        ("c-heap", "objects", "free", "fre"),
        ("c-heap", "objects", "_Znwj", "_Z3newj"),
        ("c-heap-alloc", "objects", "calloc", "free"),
    ],
)
def test_each_set_flags_its_symbol_and_only_its_symbol(
    tree, name, mode, forbidden, allowed,
):
    def run(symbol):
        if mode == "image":
            write(tree, "build/a.elf", json.dumps({"defined": [symbol]}))
            newer(tree, tree / "build/a.elf")
            where = "build/a.elf"
        else:
            where = objects(tree, {"a": [symbol]})
        return verdict(SYMBOLS, declare(tree, listed(where, name, mode=mode)))

    status, _, found = run(forbidden)
    assert status == 1
    assert found == [f"probe: {forbidden} ({name})"]
    assert run(allowed)[0] == 0


# -- pico.toml refusals -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[[footprint]]\nname = 'a'\nelf = 'x'\n", "footprint[1].ram_kib: is required"),
        (table(ram_kib=1, extra="1"), "unknown keys ['extra']"),
        (table(ram_kib=1, owned_kib=1), "owned_prefix and owned_kib are given"),
        (table(ram_kib=1, owned_prefix='"src"'), "given together"),
        (table(ram_kib=1) * 2, "duplicate name 'bench'"),
        (table(ram_kib=1).replace("build/app.elf", "../x"), "inside the dependency"),
        (listed("b", "c-heap", mode="both"), "expected 'objects' or 'image'"),
        (listed("b").replace("sets = []", "sets = []"), "nonempty array"),
        (listed("b", "c-heap", "c-heap"), "distinct set names"),
        ('[[symbols]]\nname = "a"\n', "symbols[1].mode: is required"),
    ],
)
def test_invalid_tables_are_refused_with_their_text(tree, text, expected):
    repo = declare(tree, text)
    for gate in (FOOTPRINT, SYMBOLS):
        result = gate.run(repo, ())
        assert result.status == 2
        assert expected in result.message


def test_a_library_without_tables_is_not_affected(tree):
    repo = declare(tree, "")
    assert FOOTPRINT.applies(repo) == "no [[footprint]] table"
    assert SYMBOLS.applies(repo) == "no [[symbols]] table"
    assert FOOTPRINT.applies(declare(tree, table(ram_kib=1))) is True


def test_findings_name_the_image(tree):
    image(tree)
    result = FOOTPRINT.run(declare(tree, table(ram_kib=1)), ())
    assert [(Path(f.path), f.line, f.rule) for f in result.findings] == [
        (Path("build/app.elf"), 0, "CXX-11.6"),
    ]


def test_a_tool_that_rejects_the_image_cannot_run(tree, tmp_path, monkeypatch):
    image(tree)
    repo = declare(tree, table(ram_kib=8))
    rejecting = tmp_path / "rejecting"
    rejecting.mkdir()
    for name in ("objdump", "nm"):
        tool = rejecting / f"arm-none-eabi-{name}"
        tool.write_text("#!/bin/sh\necho 'file format not recognized' >&2\nexit 1\n")
        tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{rejecting}{os.pathsep}{os.environ['PATH']}")
    status, message, _ = verdict(FOOTPRINT, repo)
    assert status == 2
    assert "arm-none-eabi-objdump could not read" in message
    assert "file format not recognized" in message


PLACED = """Sections:
Idx Name Size VMA LMA File off Algn
  0 .text 00000200 10000000 10000000 00001000 2**2
                  CONTENTS, ALLOC, LOAD, READONLY, CODE
  1 .data 00000010 20000000 10000200 00001200 2**2
                  CONTENTS, ALLOC, LOAD, READONLY, CODE
  2 .bss 00000400 20000010 20000010 00002000 2**2
                  ALLOC
  3 .uninitialized_data 00000020 20000410 20000410 00002000 2**2
                  ALLOC
  4 .ram_vector_table 00000100 20000430 20000430 00002000 2**2
                  ALLOC
  5 .tbss 00000040 20000530 20000530 00002000 2**2
                  ALLOC, THREAD_LOCAL
  6 .heap 00001000 20000570 20000570 00002000 2**2
                  ALLOC
  7 .stack_dummy 00002000 20080000 20080000 00002000 2**2
                  ALLOC
  8 .debug_info 00008000 00000000 00000000 00002000 2**2
                  CONTENTS, READONLY, DEBUGGING
  9 .ram_code 00000040 20000570 10000210 00001210 2**2
                  CONTENTS, ALLOC, LOAD, CODE
 10 .flash_noload 00000080 10000250 10000250 00002000 2**2
                  ALLOC
 11 .other 00000080 30000000 30000000 00002000 2**2
                  ALLOC
"""


def test_sections_follow_placement_and_flags_not_a_name_list(tree):
    path = write(tree, "build/placed.elf", json.dumps({
        "objdump": PLACED,
        "sections": {".text": 512, ".data": 16, ".bss": 1024},
    }))
    assert sections(path) == (1712, 592)


def test_symbols_fault_outranks_an_unavailable_row_and_keeps_reports(tree):
    where = objects(tree, {"a": ["malloc"]})
    missing = listed("gone", "c-heap").replace('name = "probe"', 'name = "missing"')
    status, message, found = verdict(
        SYMBOLS, declare(tree, listed(where, "c-heap") + missing),
    )
    assert status == 1
    assert found == ["probe: malloc (c-heap)"]
    assert "probe: 1 symbol(s) in 1 file(s)" in message
    assert "missing: no object directory at gone" in message


@pytest.mark.parametrize("symbol", ["freeaddrinfo", "malloc_extra", "_free_r_extra"])
def test_heap_sets_do_not_match_unrelated_prefixes(tree, symbol):
    where = objects(tree, {"a": [symbol]})
    assert verdict(SYMBOLS, declare(tree, listed(where, "c-heap")))[0] == 0


@pytest.mark.parametrize("symbol", ["_malloc_r", "_calloc_r", "_realloc_r", "_free_r"])
def test_reentrant_newlib_heap_entries_are_matched(tree, symbol):
    where = objects(tree, {"a": [symbol]})
    assert verdict(SYMBOLS, declare(tree, listed(where, "c-heap")))[0] == 1
    allocating = symbol != "_free_r"
    status, _, _ = verdict(SYMBOLS, declare(tree, listed(where, "c-heap-alloc")))
    assert status == allocating


GENERIC = """Sections:
Idx Name Size VMA LMA File off Algn
 0 .text 00000200 00008000 00008000 00001000 2**2
                  CONTENTS, ALLOC, LOAD, READONLY, CODE
 1 .data 00000010 00008200 00008200 00001200 2**2
                  CONTENTS, ALLOC, LOAD, DATA
 2 .bss 00000400 00008210 00008210 00002000 2**2
                  ALLOC
 3 .uninitialized_data 00000020 00008610 00008610 00002000 2**2
                  ALLOC
 4 .ram_vector_table 00000100 00008630 00008630 00002000 2**2
                  ALLOC
 5 .heap 00001000 00008730 00008730 00002000 2**2
                  ALLOC
 6 .stack_dummy 00002000 00009730 00009730 00002000 2**2
                  ALLOC
"""


def test_generic_sections_have_nonzero_flash_and_ram(tree):
    path = write(tree, "build/generic.elf", json.dumps({"objdump": GENERIC}))
    assert sections(path) == (1328, 528)


def test_all_noload_sections_cannot_run(tree):
    listing = GENERIC.replace("LOAD, ", "")
    write(tree, "build/app.elf", json.dumps({"objdump": listing}))
    newer(tree, tree / "build/app.elf")
    status, message, _ = verdict(FOOTPRINT, declare(tree, table(ram_kib=8)))
    assert status == 2
    assert "no LOAD sections" in message
