import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kairos.market import no_vig
from kairos.odds import event_prices, simulated, summarize_event, within_lookahead

FIX = json.loads((Path(__file__).parent / "fixtures" / "odds_soccer_epl.json").read_text())


def test_event_prices_maps_home_draw_away():
    p = event_prices(FIX[0])
    assert p["1"] == [2.30, 2.25, 2.40]
    assert p["X"] == [3.50, 3.40, 3.55]
    assert p["2"] == [3.20, 3.10, 3.30]


def test_simulated_applies_haircut_and_floor():
    assert simulated(2.30) == 2.18
    assert simulated(1.03) == 1.01


def test_summarize_event_uses_median():
    s = summarize_event(FIX[0], "soccer_epl")
    assert s["median"] == {"1": 2.30, "X": 3.50, "2": 3.20}
    assert s["sim"] == {"1": 2.18, "X": 3.32, "2": 3.04}
    assert s["n_books"] == 3
    assert s["home"] == "Brighton and Hove Albion"


def test_summarize_event_skips_incomplete_market():
    assert summarize_event(FIX[1], "soccer_epl") is None


def test_within_lookahead_keeps_next_48h():
    now = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
    summaries = [s for s in (summarize_event(e, "soccer_epl") for e in FIX) if s]
    kept = within_lookahead(summaries, now)
    assert [s["event_id"] for s in kept] == ["evt-brighton-villa"]


def test_no_vig_sums_to_one_and_keeps_order():
    p = no_vig({"1": 2.30, "X": 3.50, "2": 3.20})
    assert sum(p) == pytest.approx(1.0, abs=1e-3)
    assert p[0] > p[2] > p[1]


def _summary(event_id, commence_time):
    return {"event_id": event_id, "commence_time": commence_time}


def test_within_lookahead_keeps_exactly_48h_and_drops_one_second_later():
    now = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
    summaries = [
        _summary("at-48h", "2026-10-19T09:00:00Z"),
        _summary("48h-plus-1s", "2026-10-19T09:00:01Z"),
    ]
    kept = within_lookahead(summaries, now)
    assert [s["event_id"] for s in kept] == ["at-48h"]


def test_within_lookahead_drops_kickoff_now_and_past_matches():
    now = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
    summaries = [
        _summary("at-now", "2026-10-17T09:00:00Z"),
        _summary("past", "2026-10-17T08:00:00Z"),
        _summary("next-hour", "2026-10-17T10:00:00Z"),
    ]
    kept = within_lookahead(summaries, now)
    assert [s["event_id"] for s in kept] == ["next-hour"]


def test_event_prices_ignores_non_h2h_markets():
    event = {
        "id": "evt-spreads",
        "home_team": "Brighton and Hove Albion",
        "away_team": "Aston Villa",
        "bookmakers": [
            {"key": "pinnacle", "markets": [
                {"key": "spreads", "outcomes": [
                    {"name": "Brighton and Hove Albion", "price": 9.99},
                    {"name": "Aston Villa", "price": 9.98},
                    {"name": "Draw", "price": 9.97}]},
                {"key": "h2h", "outcomes": [
                    {"name": "Brighton and Hove Albion", "price": 2.30},
                    {"name": "Aston Villa", "price": 3.20},
                    {"name": "Draw", "price": 3.50}]}]}
        ],
    }
    assert event_prices(event) == {"1": [2.30], "X": [3.50], "2": [3.20]}
