"""Tests for the physical-size catalogue and the overrides that refine it."""

import io
import math
from pathlib import Path

import pytest

from sattransit.sizes import Size, parse_gcat, parse_overrides, resolve

# GCAT's real column names, with the columns the parser reads.
HEADER = "#JCAT\tSatcat\tName\tMass\tLength\tLFlag\tDiameter\tDFlag\tSpan\tSpanFlag\tShape"


def _tsv(*rows: str) -> io.StringIO:
    return io.StringIO("\n".join([HEADER, "# Updated 2026 Jul 14 1035:47", *rows]) + "\n")


def _row(satcat, name, length, diameter, span, shape="Box"):
    return f"S1\t{satcat}\t{name}\t100\t{length}\t\t{diameter}\t\t{span}\t\t{shape}"


# --- parsing -----------------------------------------------------------------


def test_parses_dimensions():
    catalogue = parse_gcat(_tsv(_row("44713", "STARLINK-1007", "0.2", "2.8", "9.0", "Box + pan")))
    size = catalogue[44713]
    assert (size.min_m, size.max_m) == (0.2, 9.0)
    assert size.shape == "Box + pan"
    assert size.source == "gcat"


def test_comment_and_separator_lines_are_ignored():
    # GCAT puts an update stamp on the second line.
    catalogue = parse_gcat(_tsv(_row("25544", "ISS", "12.6", "4.2", "23.9")))
    assert set(catalogue) == {25544}


def test_unnumbered_and_analyst_objects_are_skipped():
    catalogue = parse_gcat(_tsv(_row("-", "UNNUMBERED", "1", "1", "1"), _row("A123", "X", "1", "1", "1")))
    assert catalogue == {}


@pytest.mark.parametrize("value", ["<2.8", ">2.8", "~2.8", "?2.8", "*2.8"])
def test_qualified_values_are_read(value):
    # GCAT flags uncertain figures with a leading symbol.
    catalogue = parse_gcat(_tsv(_row("1", "X", value, "1.0", "3.0")))
    assert catalogue[1].max_m == 3.0


def test_rows_without_any_dimension_are_skipped_not_guessed():
    catalogue = parse_gcat(_tsv(_row("1", "NO DATA", "", "", ""), _row("2", "OK", "", "", "5.0")))
    assert set(catalogue) == {2}
    assert catalogue[2].max_m == 5.0


def test_zero_and_junk_dimensions_are_ignored():
    catalogue = parse_gcat(_tsv(_row("1", "X", "0", "n/a", "4.0"), _row("2", "Y", "0", "-", "")))
    assert set(catalogue) == {1}
    assert (catalogue[1].min_m, catalogue[1].max_m) == (4.0, 4.0)


# --- angular size ------------------------------------------------------------


def test_angular_size_at_a_known_range():
    # 9 m at 1000 km subtends 2 arctan(4.5/1e6) ~ 1.86 arcsec.
    size = Size(min_m=0.2, max_m=9.0, source="gcat")
    low, high = size.angular_arcsec(1000.0)
    assert high == pytest.approx(math.degrees(2 * math.atan2(4.5, 1e6)) * 3600, rel=1e-9)
    assert high == pytest.approx(1.856, abs=0.01)
    assert low < high


def test_angular_size_shrinks_with_range():
    size = Size(min_m=1.0, max_m=9.0, source="gcat")
    assert size.angular_arcsec(2000.0)[1] < size.angular_arcsec(1000.0)[1]


# --- overrides ---------------------------------------------------------------


def test_override_accepts_a_single_number():
    (pattern, size), = parse_overrides({"25544": 109.0})
    assert pattern == "25544"
    assert (size.min_m, size.max_m) == (109.0, 109.0)
    assert size.source == "config"


def test_override_accepts_a_min_max_pair():
    (_, size), = parse_overrides({"25544": [73.0, 109.0]})
    assert (size.min_m, size.max_m) == (73.0, 109.0)


def test_override_orders_the_pair():
    (_, size), = parse_overrides({"X": [109.0, 73.0]})
    assert (size.min_m, size.max_m) == (73.0, 109.0)


@pytest.mark.parametrize("value", ["big", [1, 2, 3], [], {"min": 1}, -5, [0, 3]])
def test_bad_overrides_are_rejected(value):
    with pytest.raises(ValueError, match="satellite_sizes_m"):
        parse_overrides({"25544": value})


# --- resolution --------------------------------------------------------------

CATALOGUE = {25544: Size(4.2, 23.9, "gcat", "Cyl + 2 Pan"), 44713: Size(0.2, 9.0, "gcat")}


def test_catalogue_is_used_when_nothing_overrides_it():
    size = resolve(44713, "STARLINK-1007", [], CATALOGUE)
    assert (size.min_m, size.max_m, size.source) == (0.2, 9.0, "gcat")


def test_an_override_by_norad_id_wins_over_the_catalogue():
    # GCAT's 25544 is the Zarya module, not the assembled station.
    overrides = parse_overrides({"25544": [73.0, 109.0]})
    size = resolve(25544, "ISS (ZARYA)", overrides, CATALOGUE)
    assert (size.min_m, size.max_m, size.source) == (73.0, 109.0, "config")


def test_an_override_can_match_a_name_glob():
    overrides = parse_overrides({"STARLINK-*": [2.8, 9.0]})
    size = resolve(44713, "STARLINK-1007", overrides, CATALOGUE)
    assert size.source == "config"
    assert resolve(25544, "ISS (ZARYA)", overrides, CATALOGUE).source == "gcat"


def test_name_globs_are_matched_case_insensitively():
    overrides = parse_overrides({"starlink-*": 9.0})
    assert resolve(44713, "STARLINK-1007", overrides, CATALOGUE).source == "config"


def test_the_first_matching_override_wins():
    overrides = parse_overrides({"44713": 1.0, "STARLINK-*": 2.0})
    assert resolve(44713, "STARLINK-1007", overrides, CATALOGUE).max_m == 1.0


def test_an_unknown_satellite_has_no_size():
    assert resolve(99999, "MYSTERY", [], CATALOGUE) is None
    assert resolve(99999, None, [], CATALOGUE) is None


# --- against the real catalogue ----------------------------------------------

REAL = Path("cache/gcat_satcat.tsv")


@pytest.mark.skipif(not REAL.exists(), reason="no GCAT downloaded yet")
def test_the_real_catalogue_parses_and_matches_published_dimensions():
    with REAL.open(encoding="utf-8", errors="replace") as handle:
        catalogue = parse_gcat(handle)
    assert len(catalogue) > 10000

    # Hubble is 13.2 m long and 4.2 m across; GCAT should agree closely.
    hubble = catalogue[20580]
    assert hubble.min_m == pytest.approx(4.2, abs=0.3)
    assert hubble.max_m == pytest.approx(13.2, abs=0.3)
