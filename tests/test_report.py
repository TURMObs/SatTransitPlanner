"""Tests for the result document."""

import json
import math
from datetime import datetime, timezone

import pytest

from sattransit.config import load_config
from sattransit.elements import Catalog
from sattransit.report import build_report

START = datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc)
END = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"observatory": {"name": "T", "latitude_deg": 48.0, "longitude_deg": 11.0},'
        ' "celestrak": {"groups": ["stations"]}}'
    )
    return load_config(path)


def _report(config):
    catalog = Catalog(entries=[], sources=[], skipped_stale=0)
    return build_report(config, catalog, [], START, END, 1.0)


def test_the_age_limit_is_recorded(config):
    assert _report(config)["search"]["max_element_age_days"] == 14.0


def test_an_ignored_age_limit_is_recorded_as_null(config):
    # --ignore-element-age lifts the limit to infinity internally.
    config.search.max_element_age_days = math.inf
    assert _report(config)["search"]["max_element_age_days"] is None


def test_the_document_stays_valid_json_when_the_limit_is_ignored(config):
    # json.dumps writes infinity as the bare token Infinity, which is not in
    # the JSON spec: a strict reader elsewhere would reject the whole file.
    config.search.max_element_age_days = math.inf
    text = json.dumps(_report(config))
    assert "Infinity" not in text
    json.loads(
        text,
        parse_constant=lambda name: (_ for _ in ()).throw(ValueError(name)),
    )
