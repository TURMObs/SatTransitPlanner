"""Tests for the favourites list."""

import json
from pathlib import Path

import pytest

from sattransit.favorites import FavoritesError, load_favorites


def write(tmp_path, data) -> Path:
    path = tmp_path / "favorites.json"
    path.write_text(json.dumps(data) if not isinstance(data, str) else data)
    return path


# --- accepted shapes ---------------------------------------------------------


def test_reads_the_generated_shape(tmp_path):
    path = write(
        tmp_path,
        {
            "name": "Largest objects",
            "satellites": [
                {"norad_id": 25544, "name": "ISS (ZARYA)", "max_m": 23.9},
                {"norad_id": 27424, "name": "AQUA", "max_m": 17.0},
            ],
        },
    )
    favorites = load_favorites(path)
    assert favorites.norad_ids == [25544, 27424]
    assert favorites.name == "Largest objects"


def test_reads_a_bare_list_of_ids(tmp_path):
    assert load_favorites(write(tmp_path, [25544, 27424])).norad_ids == [25544, 27424]


def test_reads_a_list_of_objects_without_a_wrapper(tmp_path):
    path = write(tmp_path, [{"norad_id": 25544}, {"norad_id": 27424}])
    assert load_favorites(path).norad_ids == [25544, 27424]


def test_reads_ids_without_a_name(tmp_path):
    assert load_favorites(write(tmp_path, {"satellites": [25544]})).name is None


def test_order_is_kept_and_repeats_are_dropped(tmp_path):
    # A repeated id would otherwise search the same satellite twice.
    assert load_favorites(write(tmp_path, [27424, 25544, 27424])).norad_ids == [27424, 25544]


def test_extra_fields_are_ignored(tmp_path):
    path = write(tmp_path, {"satellites": [{"norad_id": 25544, "whatever": "ignored"}]})
    assert load_favorites(path).norad_ids == [25544]


# --- rejected --------------------------------------------------------------


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(FavoritesError, match="could not read"):
        load_favorites(tmp_path / "absent.json")


def test_invalid_json_is_reported(tmp_path):
    with pytest.raises(FavoritesError, match="not valid JSON"):
        load_favorites(write(tmp_path, "{oops"))


def test_an_object_without_satellites_is_reported(tmp_path):
    with pytest.raises(FavoritesError, match="'satellites' list"):
        load_favorites(write(tmp_path, {"name": "no list here"}))


def test_an_empty_list_is_reported(tmp_path):
    with pytest.raises(FavoritesError, match="no satellites listed"):
        load_favorites(write(tmp_path, []))


def test_an_entry_without_an_id_is_reported(tmp_path):
    with pytest.raises(FavoritesError, match="no 'norad_id'"):
        load_favorites(write(tmp_path, [{"name": "AQUA"}]))


@pytest.mark.parametrize("bad", ["25544", 25544.5, -1, 0, None, True])
def test_a_value_that_is_not_a_norad_id_is_reported(tmp_path, bad):
    # "25544" and True are the interesting ones: a string looks close enough to
    # pass unnoticed, and bool is an int in Python.
    with pytest.raises(FavoritesError):
        load_favorites(write(tmp_path, [bad]))


# --- the file that ships -----------------------------------------------------

SHIPPED = Path("favorites.json")


@pytest.mark.skipif(not SHIPPED.exists(), reason="run from the repository root")
def test_the_shipped_favorites_file_is_usable():
    favorites = load_favorites(SHIPPED)
    assert len(favorites.norad_ids) >= 50
    assert len(set(favorites.norad_ids)) == len(favorites.norad_ids)
    # The two best-known targets, under the ids people actually track.
    assert 25544 in favorites.norad_ids  # ISS
    assert 48274 in favorites.norad_ids  # CSS (Tianhe)


@pytest.mark.skipif(not SHIPPED.exists(), reason="run from the repository root")
def test_the_shipped_favorites_file_is_sorted_largest_first():
    entries = json.loads(SHIPPED.read_text())["satellites"]
    sizes = [e["max_m"] for e in entries]
    assert sizes == sorted(sizes, reverse=True)
    assert all(e.get("name") for e in entries)  # readable without a lookup
