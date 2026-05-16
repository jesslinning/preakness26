"""Tests for live odds HTML parsing (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.live_odds import (
    implied_win_probability,
    normalize_horse_name,
    parse_derby_entries_from_html,
    parse_fractional_odds,
    parse_preakness_entries_from_html,
)

_FIXTURE_DERBY = Path(__file__).resolve().parent / "fixtures" / "live_odds_derby_widget.html"
_FIXTURE_HRN = Path(__file__).resolve().parent / "fixtures" / "live_odds_hrn_preakness.html"


def test_normalize_horse_name():
    assert normalize_horse_name("  Right  To  Party ") == "RIGHT TO PARTY"


def test_parse_fractional_odds():
    assert parse_fractional_odds("5/1") == (5, 1)
    assert parse_fractional_odds(" 9/2 ") == (9, 2)
    assert parse_fractional_odds("5-1") == (5, 1)
    assert parse_fractional_odds("bad") is None


def test_implied_win_probability():
    assert implied_win_probability((5, 1)) == pytest.approx(1 / 6)


def test_parse_fixture_derby_widget():
    html = _FIXTURE_DERBY.read_text(encoding="utf-8")
    rows = parse_derby_entries_from_html(html)
    assert len(rows) == 2
    assert rows[0]["horse_name"] == "Renegade"
    assert rows[0]["horse_name_normalized"] == "RENEGADE"
    assert rows[0]["odds_str"] == "5/1"
    assert rows[0]["implied_probability"] == pytest.approx(0.166667, abs=1e-6)
    assert rows[0]["market_strength"] == 1.0
    assert rows[1]["horse_name"] == "Albus"
    assert rows[1]["market_strength"] == 0.0


def test_parse_fixture_hrn_preakness_table():
    html = _FIXTURE_HRN.read_text(encoding="utf-8")
    rows = parse_preakness_entries_from_html(html)
    assert len(rows) == 2
    taj = rows[0]
    assert taj["horse_name"] == "Taj Mahal"
    assert taj["horse_name_normalized"] == "TAJ MAHAL"
    assert taj["program_number"] == 1
    assert taj["odds_str"] == "5/1"
    assert taj["profile_url"] == "https://www.horseracingnation.com/horse/Taj_Mahal_4"
    assert taj["market_strength"] == 1.0
    gw = rows[1]
    assert gw["horse_name"] == "Great White"
    assert gw["odds_str"] == "7/1"
    assert gw["market_strength"] == 0.0
