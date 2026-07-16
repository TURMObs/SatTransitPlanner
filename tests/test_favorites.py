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


# --- generating a list -------------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from sattransit.favorites import build_favorites, family, write_favorites  # noqa: E402
from sattransit.sizes import Size  # noqa: E402

EARTH_RADIUS_KM = 6378.135


def _entry(norad, name, apogee_km=500.0):
    """A stand-in for a CatalogEntry: only the id, name and orbit are read."""
    model = SimpleNamespace(alta=apogee_km / EARTH_RADIUS_KM)
    return SimpleNamespace(norad_id=norad, satellite=SimpleNamespace(name=name, model=model))


@pytest.mark.parametrize(
    "name,expected",
    [
        ("STARLINK-11072 [DTC]", "STARLINK"),
        ("STARLINK-30107", "STARLINK"),
        ("ISS (ZVEZDA)", "ISS"),
        ("ISS (ZARYA)", "ISS"),
        ("CSS (WENTIAN)", "CSS"),
        ("SENTINEL-1A", "SENTINEL"),
        ("AQUA", "AQUA"),
        ("SL-16 R/B", "SL-16 R/B"),  # rocket bodies share a name already
    ],
)
def test_family_groups_constellation_members(name, expected):
    assert family(name) == expected


def test_largest_first_one_per_family():
    entries = [_entry(1, "STARLINK-1"), _entry(2, "STARLINK-2"), _entry(3, "ENVISAT")]
    sizes = {1: Size(0.2, 29.0, "gcat", "Box + pan"),
             2: Size(0.2, 29.0, "gcat", "Box + pan"),
             3: Size(4.0, 26.0, "gcat", "Box + Pan")}
    picked = build_favorites(entries, sizes)["satellites"]
    assert [s["name"] for s in picked] == ["STARLINK-1", "ENVISAT"]  # one Starlink, not two


def test_a_span_from_a_tether_or_antenna_is_not_a_silhouette():
    # TSS-1R's 19.7 km is a wire; RAE's booms are wire too. Nothing to see.
    entries = [_entry(1, "TSS-1R"), _entry(2, "RAE 1"), _entry(3, "AQUA")]
    sizes = {1: Size(0.5, 19695.0, "gcat", "Box+box+tether"),
             2: Size(1.0, 228.0, "gcat", "Cyl + 4 Ant"),
             3: Size(4.0, 17.0, "gcat", "Box + Pan")}
    assert [s["name"] for s in build_favorites(entries, sizes)["satellites"]] == ["AQUA"]


def test_objects_above_low_earth_orbit_are_left_out():
    # A big satellite in geostationary orbit subtends less than an arcsecond.
    entries = [_entry(1, "APSTAR-6E", apogee_km=35799.0), _entry(2, "AQUA", apogee_km=700.0)]
    sizes = {1: Size(3.0, 30.0, "gcat", "Box+ 2 pan"), 2: Size(4.0, 17.0, "gcat", "Box + Pan")}
    assert [s["name"] for s in build_favorites(entries, sizes)["satellites"]] == ["AQUA"]


def test_the_orbit_comes_from_the_elements_not_the_size_catalogue():
    # GCAT records the orbit at the epoch of its entry: for APSTAR-6E that is a
    # transfer orbit with a 228 km perigee, long since raised to geostationary.
    entries = [_entry(1, "APSTAR-6E", apogee_km=35799.0)]
    sizes = {1: Size(3.0, 30.0, "gcat", "Box+ 2 pan")}
    assert build_favorites(entries, sizes)["satellites"] == []


def test_a_station_is_listed_once_under_the_id_people_track():
    entries = [_entry(26400, "ISS (ZVEZDA)"), _entry(25544, "ISS (ZARYA)"), _entry(3, "AQUA")]
    sizes = {26400: Size(4.2, 29.7, "gcat", "Step Cyl + 2 Pan"),
             25544: Size(4.2, 23.9, "gcat", "Cyl + 2 Pan"),
             3: Size(4.0, 17.0, "gcat", "Box + Pan")}
    picked = build_favorites(entries, sizes)["satellites"]
    ids = [s["norad_id"] for s in picked]
    assert 25544 in ids and 26400 not in ids  # Zarya's id, not Zvezda's
    assert "note" in next(s for s in picked if s["norad_id"] == 25544)


def test_a_station_family_is_skipped_when_the_canonical_id_is_untracked():
    entries = [_entry(26400, "ISS (ZVEZDA)"), _entry(3, "AQUA")]
    sizes = {26400: Size(4.2, 29.7, "gcat", "Step Cyl + 2 Pan"),
             3: Size(4.0, 17.0, "gcat", "Box + Pan")}
    assert [s["name"] for s in build_favorites(entries, sizes)["satellites"]] == ["AQUA"]


def test_the_result_stays_sorted_after_a_station_substitution():
    # A family enters on its largest member's rank but reports the canonical
    # entry, which may be smaller, so the order has to be restored.
    entries = [_entry(26400, "ISS (ZVEZDA)"), _entry(25544, "ISS (ZARYA)"), _entry(3, "ENVISAT")]
    sizes = {26400: Size(4.2, 29.7, "gcat", "Cyl"), 25544: Size(4.2, 23.9, "gcat", "Cyl"),
             3: Size(4.0, 26.0, "gcat", "Box")}
    sizes_out = [s["max_m"] for s in build_favorites(entries, sizes)["satellites"]]
    assert sizes_out == sorted(sizes_out, reverse=True) == [26.0, 23.9]


def test_satellites_without_a_size_are_left_out():
    entries = [_entry(1, "MYSTERY"), _entry(2, "AQUA")]
    assert [s["name"] for s in build_favorites(entries, {2: Size(4.0, 17.0, "gcat", "Box")})[
        "satellites"]] == ["AQUA"]


def test_count_limits_the_list():
    entries = [_entry(i, f"SAT-{i}-X") for i in range(1, 11)]
    sizes = {i: Size(1.0, float(30 - i), "gcat", "Box") for i in range(1, 11)}
    assert len(build_favorites(entries, sizes, count=4)["satellites"]) == 4


def test_the_document_records_where_it_came_from():
    doc = build_favorites([_entry(3, "AQUA")], {3: Size(4.0, 17.0, "gcat", "Box")})
    assert "GCAT" in doc["source"]
    assert doc["generated_utc"].endswith("Z")
    assert doc["name"] and doc["description"]


def test_a_generated_document_reloads(tmp_path):
    doc = build_favorites([_entry(3, "AQUA"), _entry(4, "ENVISAT")],
                          {3: Size(4.0, 17.0, "gcat", "Box"), 4: Size(4.0, 26.0, "gcat", "Box")})
    path = tmp_path / "f.json"
    write_favorites(path, doc)
    assert load_favorites(path).norad_ids == [4, 3]
