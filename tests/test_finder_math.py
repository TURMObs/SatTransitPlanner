"""Tests for the numerical machinery of the search, without any ephemeris."""

from types import SimpleNamespace

import numpy as np
import pytest

from sattransit.finder import (
    TransitFinder,
    _dilate,
    _golden_section_min,
    _limb_contact,
    _position_angle,
    _wrap_degrees,
)


def test_dilate_grows_mask_by_one_on_each_side():
    mask = np.array([False, False, True, False, False])
    assert list(_dilate(mask)) == [False, True, True, True, False]


def test_dilate_handles_edges_and_empty():
    assert list(_dilate(np.array([True, False, False]))) == [True, True, False]
    assert not _dilate(np.array([False, False, False])).any()


@pytest.mark.parametrize(
    "value,expected", [(0, 0), (180, -180), (181, -179), (359, -1), (-181, 179), (360, 0)]
)
def test_wrap_degrees(value, expected):
    assert _wrap_degrees(value) == pytest.approx(expected)


def test_position_angle_is_measured_east_of_north():
    assert _position_angle(0, 1) == pytest.approx(0)  # north
    assert _position_angle(1, 0) == pytest.approx(90)  # east
    assert _position_angle(0, -1) == pytest.approx(180)  # south
    assert _position_angle(-1, 0) == pytest.approx(270)  # west


def test_golden_section_finds_minimum_of_smooth_function():
    found = _golden_section_min(lambda x: (x - 2.3) ** 2 + 1.0, 0.0, 5.0, 1e-9)
    assert found == pytest.approx(2.3, abs=1e-6)


def test_golden_section_finds_minimum_of_v_shape():
    # A close approach looks like a V, not a parabola, when sampled coarsely.
    found = _golden_section_min(lambda x: abs(x - 1.75), -10.0, 10.0, 1e-9)
    assert found == pytest.approx(1.75, abs=1e-6)


def test_limb_contact_finds_both_crossings():
    # f < 0 inside |x| < 3, > 0 outside: a "disk" of radius 3 centred on 0.
    def f(x):
        return abs(x) - 3.0

    assert _limb_contact(f, 0.0, -1.0, 100.0, 1e-9) == pytest.approx(-3.0, abs=1e-6)
    assert _limb_contact(f, 0.0, +1.0, 100.0, 1e-9) == pytest.approx(3.0, abs=1e-6)


def test_limb_contact_returns_none_when_starting_outside():
    assert _limb_contact(lambda x: abs(x) - 3.0, 10.0, 1.0, 100.0, 1e-9) is None


def test_limb_contact_returns_none_when_crossing_is_beyond_max_span():
    assert _limb_contact(lambda x: abs(x) - 3.0, 0.0, 1.0, 1.0, 1e-9) is None


def _finder(gate_factor=3.0):
    """A TransitFinder stub exposing only what the bracket logic reads."""
    return SimpleNamespace(config=SimpleNamespace(search=SimpleNamespace(gate_factor=gate_factor)))


def _brackets(separation, visible, threshold, gate_factor=3.0):
    jd = np.arange(len(separation), dtype=float)
    return TransitFinder._candidate_brackets(
        _finder(gate_factor), np.array(separation, dtype=float), np.array(visible), jd, threshold
    )


def test_bracket_contains_a_close_minimum():
    separation = [10.0, 5.0, 0.2, 4.0, 9.0]
    brackets = _brackets(separation, [True] * 5, threshold=1.0)
    assert len(brackets) == 1
    lo, mid, hi = brackets[0]
    assert lo == 1.0 and mid == 2.0 and hi == 3.0


def test_distant_minimum_is_gated_out():
    # A minimum 40 deg away that only moved 1 deg per step cannot reach the Sun.
    separation = [42.0, 41.0, 40.0, 41.0, 42.0]
    assert _brackets(separation, [True] * 5, threshold=1.0) == []


def test_fast_satellite_minimum_is_kept_even_when_samples_are_far_away():
    # 30 deg per step: the true minimum can lie anywhere in the bracket, so the
    # gate must not discard it despite the sampled minimum being 20 deg out.
    separation = [80.0, 50.0, 20.0, 50.0, 80.0]
    assert len(_brackets(separation, [True] * 5, threshold=1.0)) == 1


def test_no_candidates_when_nothing_is_visible():
    separation = [10.0, 5.0, 0.2, 4.0, 9.0]
    assert _brackets(separation, [False] * 5, threshold=1.0) == []


def test_candidates_at_the_edge_of_visibility_are_kept_for_checking():
    # The satellite drops out of view around the minimum. Both visible samples
    # still count as candidates; whether the refined minimum is actually
    # observable is decided later, against the real altitude limits.
    separation = [10.0, 5.0, 0.2, 4.0, 9.0]
    brackets = _brackets(separation, [True, True, False, True, True], threshold=1.0)
    assert len(brackets) == 2


def test_minimum_at_edge_of_visibility_still_brackets():
    # The satellite is only visible at index 2; dilation must still give it
    # finite neighbours so a bracket exists.
    separation = np.array([10.0, 5.0, 0.2, 4.0, 9.0])
    visible = _dilate(np.array([False, False, True, False, False]))
    brackets = _brackets(separation, visible, threshold=1.0)
    assert len(brackets) == 1


def test_no_minimum_when_separation_is_monotonic():
    assert _brackets([1.0, 2.0, 3.0, 4.0, 5.0], [True] * 5, threshold=10.0) == []


def test_multiple_passes_yield_multiple_brackets():
    separation = [9.0, 0.5, 9.0, 9.0, 0.3, 9.0]
    assert len(_brackets(separation, [True] * 6, threshold=1.0)) == 2


def test_gate_factor_widens_the_net():
    # Sampled minimum 8 deg out, moving 4 deg per step. One step of travel
    # cannot reach the Sun, so a bare gate rejects it; the safety factor keeps
    # it for a closer look.
    separation = [16.0, 12.0, 8.0, 12.0, 16.0]
    assert _brackets(separation, [True] * 5, threshold=1.0, gate_factor=1.0) == []
    assert len(_brackets(separation, [True] * 5, threshold=1.0, gate_factor=3.0)) == 1


# The apparent-radius formula now lives on Target; see test_target.py.


# --- illumination filter (the config include/exclude) ------------------------

from sattransit.target import Illumination  # noqa: E402


def _illum(sunlit=True, limb="lit"):
    return Illumination(
        phase_deg=90.0, illuminated_fraction=0.5, bright_limb_angle_deg=0.0,
        limb=limb, satellite_sunlit=sunlit,
    )


def _wanted(satellite, limb, illumination):
    finder = SimpleNamespace(config=SimpleNamespace(
        illumination=SimpleNamespace(satellite=satellite, limb=limb)))
    return TransitFinder._illumination_wanted(finder, illumination)


def test_the_sun_has_no_illumination_and_always_passes():
    # A solar event carries illumination None; no filter can exclude it.
    assert _wanted("eclipsed", "dark", None) is True


def test_any_keeps_everything():
    assert _wanted("any", "any", _illum(sunlit=False, limb="dark")) is True
    assert _wanted("any", "any", _illum(sunlit=True, limb="lit")) is True


def test_sunlit_filter_excludes_eclipsed_satellites():
    assert _wanted("sunlit", "any", _illum(sunlit=True)) is True
    assert _wanted("sunlit", "any", _illum(sunlit=False)) is False


def test_eclipsed_filter_excludes_sunlit_satellites():
    assert _wanted("eclipsed", "any", _illum(sunlit=False)) is True
    assert _wanted("eclipsed", "any", _illum(sunlit=True)) is False


def test_limb_filter_keeps_only_the_named_side():
    assert _wanted("any", "lit", _illum(limb="lit")) is True
    assert _wanted("any", "lit", _illum(limb="dark")) is False
    assert _wanted("any", "dark", _illum(limb="dark")) is True


def test_the_filters_combine():
    assert _wanted("sunlit", "dark", _illum(sunlit=True, limb="dark")) is True
    assert _wanted("sunlit", "dark", _illum(sunlit=True, limb="lit")) is False
    assert _wanted("sunlit", "dark", _illum(sunlit=False, limb="dark")) is False
