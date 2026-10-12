import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from kairos.settle import parse_scores, score_forecasts, settle_bets, sports_to_check
from kairos.store import new_state

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)


def bet(**kw):
    base = {"id": "b1", "date": "2026-10-17", "event_id": "evt-brighton-villa", "sport_key": "soccer_epl",
            "home": "Brighton and Hove Albion", "away": "Aston Villa", "commence_time": "2026-10-18T14:00:00Z",
            "selection": "1", "odds_median": 2.30, "odds_sim": 2.18, "stake_cents": 300, "p_kairos": 0.5,
            "p_market": 0.42, "status": "open", "payout_cents": None, "closing_odds": None, "settled_date": None, "reasoning": ""}
    base.update(kw)
    return base


def test_parse_scores_only_completed():
    outcomes = parse_scores(json.loads((FIX / "scores_soccer_epl.json").read_text()))
    assert outcomes == {"evt-brighton-villa": 0}


def test_settle_won_lost_and_void():
    s = new_state(date(2026, 10, 13))
    s["bankroll_cents"] = 9000
    bets = [bet(), bet(id="b2", selection="2"), bet(id="b3", event_id="evt-old", commence_time="2026-10-14T14:00:00Z")]
    log = settle_bets(s, bets, {"evt-brighton-villa": 0}, NOW, date(2026, 10, 19))
    assert [b["status"] for b in bets] == ["won", "lost", "void"]
    assert bets[0]["payout_cents"] == 654
    assert bets[2]["payout_cents"] == 300
    assert s["bankroll_cents"] == 9000 + 654 + 300
    assert len(log) == 3 and bets[0]["settled_date"] == "2026-10-19"


def test_score_forecasts_sets_rps_and_voids_stale():
    fc = [
        {"event_id": "evt-brighton-villa", "commence_time": "2026-10-18T14:00:00Z", "p_kairos": [0.5, 0.3, 0.2],
         "p_market": [0.42, 0.28, 0.30], "p_model": None, "outcome": None},
        {"event_id": "evt-old", "commence_time": "2026-10-14T14:00:00Z", "p_kairos": [0.4, 0.3, 0.3],
         "p_market": [0.4, 0.3, 0.3], "p_model": None, "outcome": None},
    ]
    assert score_forecasts(fc, {"evt-brighton-villa": 0}, NOW) == 1
    assert fc[0]["outcome"] == 0
    assert fc[0]["rps_kairos"] < fc[0]["rps_market"]
    assert fc[0]["rps_model"] is None
    assert fc[1]["void"] is True


def test_sports_to_check_only_started_items():
    bets = [bet(), bet(id="b9", sport_key="soccer_italy_serie_a", commence_time="2026-10-25T14:00:00Z")]
    assert sports_to_check(bets, [], NOW) == {"soccer_epl"}


# Tests complementaires : branches non verrouillees par la liste du brief.


def test_parse_scores_skips_unusable_games():
    payload = [
        {"id": "evt-no-scores", "completed": True, "home_team": "Arsenal", "away_team": "Chelsea", "scores": None},
        {"id": "evt-other-names", "completed": True, "home_team": "Arsenal", "away_team": "Chelsea",
         "scores": [{"name": "Arsenal", "score": "1"}, {"name": "Spurs", "score": "0"}]},
    ]
    assert parse_scores(payload) == {}


def test_settle_skips_already_settled_bets():
    s = new_state(date(2026, 10, 13))
    s["bankroll_cents"] = 9000
    b = bet(status="won", payout_cents=654, settled_date="2026-10-18")
    assert settle_bets(s, [b], {"evt-brighton-villa": 0}, NOW, date(2026, 10, 19)) == []
    assert b["status"] == "won" and b["payout_cents"] == 654
    assert s["bankroll_cents"] == 9000


def test_settle_leaves_recent_unfinished_bets_open():
    s = new_state(date(2026, 10, 13))
    s["bankroll_cents"] = 9000
    b = bet(commence_time="2026-10-18T14:00:00Z")
    assert settle_bets(s, [b], {}, NOW, date(2026, 10, 19)) == []
    assert b["status"] == "open" and b["payout_cents"] is None
    assert s["bankroll_cents"] == 9000


def test_void_after_exactly_three_days():
    s = new_state(date(2026, 10, 13))
    at_limit = bet(id="edge", event_id="evt-x", commence_time="2026-10-16T08:00:00Z")
    just_over = bet(id="late", event_id="evt-y", commence_time="2026-10-16T07:59:00Z")
    settle_bets(s, [at_limit, just_over], {}, NOW, date(2026, 10, 19))
    assert at_limit["status"] == "open"
    assert just_over["status"] == "void"


def test_score_forecasts_skips_void_and_already_scored():
    voided = {"event_id": "evt-brighton-villa", "p_kairos": [0.5, 0.3, 0.2], "p_market": [0.42, 0.28, 0.30],
              "p_model": None, "outcome": None, "void": True}
    scored = {"event_id": "evt-brighton-villa", "p_kairos": [0.5, 0.3, 0.2], "p_market": [0.42, 0.28, 0.30],
              "p_model": None, "outcome": 1}
    assert score_forecasts([voided, scored], {"evt-brighton-villa": 0}, NOW) == 0
    assert voided["outcome"] is None and "rps_kairos" not in voided
    assert scored["outcome"] == 1 and "rps_kairos" not in scored


def test_score_forecasts_scores_model_when_present():
    fc = [{"event_id": "evt-brighton-villa", "commence_time": "2026-10-18T14:00:00Z", "p_kairos": [0.5, 0.3, 0.2],
           "p_market": [0.42, 0.28, 0.30], "p_model": [0.6, 0.25, 0.15], "outcome": None}]
    assert score_forecasts(fc, {"evt-brighton-villa": 0}, NOW) == 1
    assert fc[0]["rps_model"] == pytest.approx(0.09125)


def test_score_forecasts_leaves_upcoming_forecast_alone():
    f = {"event_id": "evt-future", "commence_time": "2026-10-25T14:00:00Z", "p_kairos": [0.5, 0.3, 0.2],
         "p_market": [0.42, 0.28, 0.30], "p_model": None, "outcome": None}
    assert score_forecasts([f], {}, NOW) == 0
    assert f["outcome"] is None and not f.get("void")


def test_sports_to_check_ignores_settled_and_void_items():
    bets = [bet(id="b5", sport_key="soccer_germany_bundesliga", status="won")]
    forecasts = [
        {"sport_key": "soccer_spain_la_liga", "commence_time": "2026-10-18T14:00:00Z", "outcome": None, "void": False},
        {"sport_key": "soccer_france_ligue_one", "commence_time": "2026-10-18T14:00:00Z", "outcome": None, "void": True},
        {"sport_key": "soccer_italy_serie_a", "commence_time": "2026-10-18T14:00:00Z", "outcome": 2, "void": False},
    ]
    assert sports_to_check(bets, forecasts, NOW) == {"soccer_spain_la_liga"}
