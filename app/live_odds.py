"""
Fetch and parse Preakness live odds from Horse Racing Nation's odds article.

The article embeds a field table (#, Horse, Jockey, Current, Fair odds). We read the
``Current`` column as fractional win odds and rank implied probabilities into
``market_strength``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup

LIVE_ODDS_URL = (
    "https://www.horseracingnation.com/news/"
    "Preakness_betting_odds_Great_White_among_favorites_early_123"
)

_FRACTIONAL_ODDS = re.compile(r"^\s*(\d+)\s*[-/]\s*(\d+)\s*$")

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def normalize_horse_name(name: str) -> str:
    """Uppercase and collapse whitespace for matching to prediction CSV names."""
    s = " ".join(name.strip().split())
    return s.upper()


def parse_fractional_odds(s: str) -> tuple[int, int] | None:
    """Parse '5/1' or '5-1' -> (5, 1). Returns None if invalid."""
    m = _FRACTIONAL_ODDS.match(s.strip())
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if a < 0 or b <= 0:
        return None
    return a, b


def implied_win_probability(frac: tuple[int, int]) -> float:
    """UK fractional a/b: implied win probability = b / (a + b)."""
    a, b = frac
    return b / (a + b)


def add_market_strength(rows: list[dict[str, Any]]) -> None:
    """
    In-place: set market_strength in [0, 1] — higher = stronger market (shorter odds).
    """
    n = len(rows)
    if n == 0:
        return
    if n == 1:
        rows[0]["market_strength"] = 1.0
        return

    probs = [r["implied_probability"] for r in rows]
    order = sorted(range(n), key=lambda i: probs[i], reverse=True)
    ranks = [0.0] * n
    pos = 0
    while pos < n:
        end = pos
        v = probs[order[pos]]
        while end + 1 < n and probs[order[end + 1]] == v:
            end += 1
        r_avg = (pos + 1 + end + 1) / 2.0
        for k in range(pos, end + 1):
            ranks[order[k]] = r_avg
        pos = end + 1

    for idx in range(n):
        rows[idx]["market_strength"] = (n - ranks[idx]) / (n - 1)


def _header_indices(cells: list[str]) -> dict[str, int] | None:
    lowered = [c.lower() for c in cells]
    if "horse" not in lowered or "current" not in lowered:
        return None
    return {name: lowered.index(name) for name in ("#", "horse", "current") if name in lowered}


def _cell_text(td) -> str:
    return td.get_text(" ", strip=True)


def find_preakness_odds_table(soup: BeautifulSoup):
    """Return the HRN article odds table, or None."""
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header_cells = [_cell_text(td) for td in rows[0].find_all(["th", "td"])]
        if _header_indices(header_cells) is not None:
            return table
    return None


def parse_preakness_entries_from_html(html: str) -> list[dict[str, Any]]:
    """
    Parse Preakness horse rows from HRN article HTML.

    Each row: program_number, horse_name, odds_str, implied_probability,
    market_strength, profile_url (optional).
    """
    soup = BeautifulSoup(html, "html.parser")
    table = find_preakness_odds_table(soup)
    if not table:
        raise ValueError("Preakness odds table (# / Horse / Current) not found in HTML")

    rows: list[dict[str, Any]] = []
    trs = table.find_all("tr")
    if not trs:
        raise ValueError("Preakness odds table has no rows")

    header_cells = [_cell_text(td) for td in trs[0].find_all(["th", "td"])]
    idx = _header_indices(header_cells)
    if not idx:
        raise ValueError("Could not locate Horse and Current columns in odds table")

    horse_i = idx["horse"]
    current_i = idx["current"]
    num_i = idx.get("#")

    for tr in trs[1:]:
        tds = tr.find_all("td")
        if len(tds) <= max(horse_i, current_i):
            continue
        horse_td = tds[horse_i]
        raw_name = _cell_text(horse_td)
        if not raw_name:
            continue
        odds_raw = _cell_text(tds[current_i])
        frac = parse_fractional_odds(odds_raw)
        if not frac:
            continue

        program_number = -1
        if num_i is not None and num_i < len(tds):
            num_text = _cell_text(tds[num_i])
            try:
                program_number = int(num_text)
            except ValueError:
                program_number = -1

        link = horse_td.find("a", href=True)
        profile_url = link["href"].strip() if link else None
        if profile_url and profile_url.startswith("/"):
            profile_url = f"https://www.horseracingnation.com{profile_url}"

        odds_str = odds_raw.strip().replace(" ", "")
        if "/" not in odds_str and "-" in odds_str:
            odds_str = odds_str.replace("-", "/", 1)

        p = implied_win_probability(frac)
        rows.append(
            {
                "program_number": program_number,
                "horse_name": raw_name,
                "horse_name_normalized": normalize_horse_name(raw_name),
                "odds_str": odds_str,
                "implied_probability": round(p, 6),
                "profile_url": profile_url,
            }
        )

    if not rows:
        raise ValueError("No horse rows parsed from Preakness odds table")

    add_market_strength(rows)
    return rows


# Legacy Kentucky Derby widget parser (tests / fallback).
def find_kentucky_derby_widget(soup: BeautifulSoup):
    for widget in soup.select("div.race-entry-widget"):
        h2 = widget.select_one("h2.race-widget-title")
        if not h2:
            continue
        title = h2.get_text()
        if "Kentucky Derby" in title and "Oaks" not in title:
            return widget
    return None


def parse_derby_entries_from_html(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    widget = find_kentucky_derby_widget(soup)
    if not widget:
        raise ValueError("Kentucky Derby race widget not found in HTML")

    rows: list[dict[str, Any]] = []
    for entry in widget.select(".race-horse-entry"):
        num_el = entry.select_one(".horse-number")
        name_el = entry.select_one(".race-horse-column.horse")
        odds_el = entry.select_one(".odds")
        if not num_el or not name_el or not odds_el:
            continue
        raw_name = name_el.get_text(" ", strip=True)
        odds_str = odds_el.get_text(" ", strip=True)
        frac = parse_fractional_odds(odds_str)
        if not frac:
            continue
        try:
            program_number = int(num_el.get_text(strip=True))
        except ValueError:
            program_number = -1

        p = implied_win_probability(frac)
        rows.append(
            {
                "program_number": program_number,
                "horse_name": raw_name,
                "horse_name_normalized": normalize_horse_name(raw_name),
                "odds_str": odds_str.strip(),
                "implied_probability": round(p, 6),
                "profile_url": None,
            }
        )

    if not rows:
        raise ValueError("No race-horse-entry rows found in Kentucky Derby widget")

    add_market_strength(rows)
    return rows


async def fetch_live_odds_html(*, timeout_s: float = 25.0) -> str:
    async with httpx.AsyncClient(
        headers=_DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(timeout_s),
    ) as client:
        r = await client.get(LIVE_ODDS_URL)
        r.raise_for_status()
        return r.text


def fetch_live_odds_html_sync(*, timeout_s: float = 25.0) -> str:
    with httpx.Client(
        headers=_DEFAULT_HEADERS,
        follow_redirects=True,
        timeout=timeout_s,
    ) as client:
        r = client.get(LIVE_ODDS_URL)
        r.raise_for_status()
        return r.text


@dataclass
class LiveOddsResult:
    fetched_at_iso: str
    source_url: str
    horses: list[dict[str, Any]]


async def fetch_and_parse_preakness_odds(*, timeout_s: float = 25.0) -> LiveOddsResult:
    from datetime import datetime, timezone

    html = await fetch_live_odds_html(timeout_s=timeout_s)
    horses = parse_preakness_entries_from_html(html)
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return LiveOddsResult(fetched_at_iso=ts, source_url=LIVE_ODDS_URL, horses=horses)


def fetch_and_parse_preakness_odds_sync(*, timeout_s: float = 25.0) -> LiveOddsResult:
    from datetime import datetime, timezone

    html = fetch_live_odds_html_sync(timeout_s=timeout_s)
    horses = parse_preakness_entries_from_html(html)
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return LiveOddsResult(fetched_at_iso=ts, source_url=LIVE_ODDS_URL, horses=horses)


# Back-compat aliases for existing imports.
fetch_and_parse_derby_odds = fetch_and_parse_preakness_odds
fetch_and_parse_derby_odds_sync = fetch_and_parse_preakness_odds_sync
