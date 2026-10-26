# SPDX-License-Identifier: MIT
"""Image and credentials decisions, against fixtures (AR-12).

No case touches a board.
"""

import pytest

from pico_tooling.device_errors import AMBIGUOUS, FAILED, RefusalError
from pico_tooling.device_images import (
    built_images,
    check_credentials,
    resolve_uf2,
)


def touch(root, *names):
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).touch()


# -- image (10) ----------------------------------------------------------------


@pytest.fixture
def trees(tmp_path):
    touch(
        tmp_path,
        "t/examples/bench/bench.uf2",
        "t/examples/minimal/minimal.uf2",
        "t/padcheck/padcheck.uf2",
        "one/examples/bench/bench.uf2",
        "solo/padcheck/padcheck.uf2",
        "loose.uf2",
        "twice/examples/x/a.uf2",
        "twice/x/b.uf2",
    )
    (tmp_path / "empty").mkdir()
    return tmp_path


def test_the_one_example_built_is_the_answer(trees):
    assert resolve_uf2(trees / "one") == trees / "one/examples/bench/bench.uf2"


def test_an_image_directly_under_the_tree_is_found(trees):
    assert resolve_uf2(trees / "solo") == trees / "solo/padcheck/padcheck.uf2"


def test_several_images_are_listed_not_guessed(trees):
    with pytest.raises(RefusalError) as refused:
        resolve_uf2(trees / "t")
    assert refused.value.status == AMBIGUOUS
    assert "several images are built; name one of:" in str(refused.value)
    assert "t/examples/bench/bench.uf2" in str(refused.value)


def test_an_example_is_named_by_its_directory(trees):
    assert resolve_uf2(trees / "t", "bench") == trees / "t/examples/bench/bench.uf2"


def test_an_image_under_the_tree_is_named_by_its_directory(trees):
    assert resolve_uf2(trees / "t", "padcheck") == trees / "t/padcheck/padcheck.uf2"


def test_a_name_with_no_image_answers_nothing(trees):
    assert resolve_uf2(trees / "t", "nosuch") is None


def test_a_name_matching_several_images_is_refused_not_guessed(trees):
    with pytest.raises(RefusalError) as refused:
        resolve_uf2(trees / "twice", "x")
    assert refused.value.status == AMBIGUOUS
    assert "several images are built" in str(refused.value)


def test_a_uf2_path_wins(trees, monkeypatch):
    monkeypatch.chdir(trees)
    assert str(resolve_uf2(trees / "t", "loose.uf2")) == "loose.uf2"


def test_every_image_is_counted_once(trees):
    assert len(built_images(trees / "t")) == 3


def test_an_empty_tree_counts_none(trees):
    assert built_images(trees / "empty") == []


# -- credentials (4) -----------------------------------------------------------


@pytest.fixture
def caches(tmp_path):
    for name, cache in {
        "empty": "PICO_NET_WIFI_SSID:STRING=\nPICO_NET_WIFI_PASSWORD:STRING=\n",
        "set": "PICO_NET_WIFI_SSID:STRING=home\n",
        "none": "CMAKE_BUILD_TYPE:STRING=Release\n",
    }.items():
        touch(tmp_path, f"c/{name}/examples/net/net.uf2")
        (tmp_path / f"c/{name}/CMakeCache.txt").write_text(cache)
    touch(tmp_path, "c/nocache/net.uf2")
    return tmp_path / "c"


def test_an_empty_ssid_is_refused_naming_it(caches):
    with pytest.raises(RefusalError) as refused:
        check_credentials(caches / "empty/examples/net/net.uf2")
    assert refused.value.status == FAILED
    assert "empty PICO_NET_WIFI_SSID" in str(refused.value)
    assert "-DPICO_NET_WIFI_PASSWORD=" in str(refused.value)


def test_a_set_ssid_passes(caches):
    assert check_credentials(caches / "set/examples/net/net.uf2") is None


def test_a_tree_declaring_no_ssid_passes(caches):
    assert check_credentials(caches / "none/examples/net/net.uf2") is None


def test_an_image_with_no_cache_passes_warned(caches):
    # The temporary directory holds no cache above it either.
    warning = check_credentials(caches / "nocache/net.uf2")
    assert "cannot verify Wi-Fi credentials" in warning
