import json
from datetime import date, datetime, timezone

from kairos.site import build_site_data, health, mood, write_site
from kairos.store import new_state

NOW = datetime(2026, 10, 17, 9, 5, tzinfo=timezone.utc)


def test_mood_and_health():
    s = new_state(date(2026, 10, 1))
    assert mood(s, [{"status": "open"}], 10_000) == "En chasse"
    assert mood(s, [], 10_420) == "En forme"
    assert mood(s, [], 4_000) == "Affamé"
    assert round(health(s, 10_420), 3) == 0.868
    s["alive"] = False
    assert mood(s, [], 50) == "Éteint" and health(s, 50) == 0.0


def test_build_site_data_shape(tmp_root):
    s = new_state(date(2026, 10, 1))
    s["bankroll_cents"] = 10_110
    s["last_message"] = "Bonjour <b>monde</b>"
    s["history"] = [{"date": "2026-10-16", "equity_cents": 10_000}]
    bets = [{"status": "open", "stake_cents": 310, "sport_key": "soccer_epl", "commence_time": "2026-10-18T14:00:00Z",
             "home": "Brighton", "away": "Villa", "selection": "1", "odds_sim": 2.18, "odds_median": 2.30, "payout_cents": None,
             "p_kairos": 0.5, "p_market": 0.42, "closing_odds": None, "date": "2026-10-17", "settled_date": None}]
    data = build_site_data(s, bets, [], {"compos": {"description": "Compos", "status": "kept", "uses": 12, "score": 0.01}},
                           "# Leçons de Kairos\n\n- une leçon (3 cas)\n", date(2026, 10, 17), NOW)
    assert data["equity_cents"] == 10_420 and data["delta_cents"] == 420
    assert data["day"] == 17 and data["diploma_in"] == 39
    assert data["bets"][0]["league"] == "Premier League"
    assert data["lessons"] == ["une leçon (3 cas)"]
    assert data["sources"][0]["id"] == "compos"
    assert data["message"] == "Bonjour <b>monde</b>"
    assert [t["id"] for t in data["trophies"]][0] == "premier_gain"
    write_site(data)
    assert json.loads((tmp_root / "site" / "data.json").read_text())["name"] == "Kairos"
    assert (tmp_root / "site" / "index.html").exists()


def _bet(**over) -> dict:
    base = {"status": "open", "stake_cents": 200, "sport_key": "soccer_epl", "commence_time": "2026-10-18T14:00:00Z",
            "home": "Brighton", "away": "Villa", "selection": "1", "odds_sim": 2.0, "odds_median": 2.1, "payout_cents": None,
            "p_kairos": 0.5, "p_market": 0.45, "closing_odds": None, "date": "2026-10-17", "settled_date": None}
    base.update(over)
    return base


def test_mood_branches_and_boundaries():
    s = new_state(date(2026, 10, 1))
    assert mood(s, [{"status": "won"}, {"status": "open"}], 4_000) == "En chasse"
    assert mood(s, [{"status": "won"}], 4_000) == "Affamé"
    assert mood(s, [], 7_000) == "Sous pression"
    assert mood(s, [], 5_000) == "Sous pression"
    assert mood(s, [], 4_999) == "Affamé"
    assert mood(s, [], 9_999) == "Sous pression"
    assert mood(s, [], 10_000) == "En forme"
    s["diploma"] = "obtenu"
    assert mood(s, [], 4_000) == "Diplômé"
    assert mood(s, [{"status": "open"}], 4_000) == "Diplômé"
    s["diploma"] = "manqué"
    assert mood(s, [], 4_000) == "Affamé"
    assert mood(s, [], 10_420) == "En forme"
    s["diploma"] = "obtenu"
    s["alive"] = False
    assert mood(s, [], 10_420) == "Éteint"


def test_health_is_clamped_to_unit_interval():
    s = new_state(date(2026, 10, 1))
    assert health(s, 20_000) == 1.0
    assert health(s, 12_000) == 1.0
    assert health(s, 0) == 0.0
    assert health(s, -500) == 0.0


def test_build_site_data_rounds_health_and_floors_countdown():
    s = new_state(date(2026, 10, 1))
    s["bankroll_cents"] = 10_110
    data = build_site_data(s, [_bet(stake_cents=310)], [], {}, "", date(2026, 10, 17), NOW)
    assert data["health"] == 0.868
    for today, left in ((date(2026, 11, 24), 1), (date(2026, 11, 25), 0), (date(2026, 11, 26), 0)):
        assert build_site_data(s, [], [], {}, "", today, NOW)["diploma_in"] == left


def test_recent_bets_latest_first_capped_at_eight():
    s = new_state(date(2026, 10, 1))
    bets = [_bet(home=f"J{d}", date=f"2026-10-{d:02d}", commence_time=f"2026-10-{d:02d}T14:00:00Z") for d in range(1, 10)]
    bets.append(_bet(home="J10 midi", date="2026-10-10", commence_time="2026-10-10T14:00:00Z"))
    bets.append(_bet(home="J10 soir", date="2026-10-10", commence_time="2026-10-10T20:00:00Z"))
    data = build_site_data(s, bets, [], {}, "", date(2026, 10, 10), NOW)
    assert [b["home"] for b in data["bets"]] == ["J10 soir", "J10 midi", "J9", "J8", "J7", "J6", "J5", "J4"]
    assert data["bets"][0]["kickoff"] == "2026-10-10T20:00:00Z"
    assert set(data["bets"][0]) == {"league", "kickoff", "home", "away", "selection", "odds_sim", "odds_median",
                                    "stake_cents", "payout_cents", "status", "p_kairos", "p_market", "closing_odds"}


def test_sources_sorted_and_trophies_dated():
    s = new_state(date(2026, 10, 1))
    s["trophies"] = {"premier_gain": "2026-10-16"}
    sources = {"zeta": {"description": "Z", "status": "test", "uses": 1, "score": None},
               "alpha": {"description": "A", "status": "dropped", "uses": 12, "score": -0.02}}
    data = build_site_data(s, [], [], sources, "", date(2026, 10, 17), NOW)
    assert data["sources"] == [{"id": "alpha", "description": "A", "status": "dropped", "uses": 12, "score": -0.02},
                               {"id": "zeta", "description": "Z", "status": "test", "uses": 1, "score": None}]
    assert data["trophies"][0]["date"] == "2026-10-16" and data["trophies"][1]["date"] is None


def test_lessons_keep_dash_space_bullets_and_trim():
    s = new_state(date(2026, 10, 1))
    text = "# Leçons de Kairos\n\n- Première\n-   deuxième  \n-sans espace\n* autre\nTexte libre\n"
    data = build_site_data(s, [], [], {}, text, date(2026, 10, 17), NOW)
    assert data["lessons"] == ["Première", "deuxième"]


def test_write_site_copies_template_verbatim(tmp_root):
    from kairos.site import TEMPLATE
    write_site({"name": "Kairos"})
    assert (tmp_root / "site" / "index.html").read_bytes() == TEMPLATE.read_bytes()


def test_data_json_contract_fully_populated():
    from kairos.metrics import current_streak, rank, stats

    s = new_state(date(2026, 9, 26))
    s.update(generation=3, bankroll_cents=9_900, hunger_total_cents=1_375, last_message="Message de test",
             last_message_date="2026-10-16", trophies={"premier_gain": "2026-10-14"},
             history=[{"date": "2026-10-15", "equity_cents": 10_050}, {"date": "2026-10-16", "equity_cents": 10_210}])
    bets = [
        _bet(date="2026-10-17", commence_time="2026-10-18T14:00:00Z", home="Brighton", away="Villa", selection="1",
             odds_sim=2.18, odds_median=2.30, stake_cents=310, status="open", p_kairos=0.5, p_market=0.42, closing_odds=None),
        _bet(sport_key="soccer_spain_la_liga", date="2026-10-15", commence_time="2026-10-15T20:00:00Z", settled_date="2026-10-16",
             home="Séville", away="Betis", selection="X", odds_sim=3.10, odds_median=3.30, stake_cents=400, payout_cents=1240,
             status="won", p_kairos=0.36, p_market=0.31, closing_odds=3.20),
        _bet(sport_key="soccer_germany_bundesliga", date="2026-10-13", commence_time="2026-10-13T18:00:00Z", settled_date="2026-10-14",
             home="Bayern", away="Dortmund", selection="2", odds_sim=1.90, odds_median=2.00, stake_cents=200, payout_cents=380,
             status="won", p_kairos=0.55, p_market=0.50, closing_odds=2.10),
        _bet(sport_key="soccer_italy_serie_a", date="2026-10-12", commence_time="2026-10-12T15:00:00Z", settled_date="2026-10-13",
             home="Inter", away="Milan", selection="1", odds_sim=2.50, odds_median=2.40, stake_cents=250, payout_cents=0,
             status="lost", p_kairos=0.45, p_market=0.42, closing_odds=2.30),
        _bet(date="2026-10-11", commence_time="2026-10-11T12:00:00Z", settled_date="2026-10-12", home="Arsenal", away="Chelsea",
             selection="X", odds_sim=3.00, odds_median=3.10, stake_cents=150, payout_cents=150, status="void",
             p_kairos=0.30, p_market=0.28, closing_odds=None),
    ]
    forecasts = [
        {"outcome": 1, "rps_market": 0.20, "rps_kairos": 0.15},
        {"outcome": 0, "rps_market": 0.22, "rps_kairos": 0.30},
        {"outcome": None, "rps_market": 0.10, "rps_kairos": 0.05},
    ]
    sources = {"compos": {"description": "Compos", "status": "kept", "uses": 12, "score": 0.01}}
    lessons = "# Leçons de Kairos\n\n- une leçon (3 cas)\n- seconde leçon\n"
    assert rank(forecasts, bets) != rank([], bets)  # the forecast part must change the rank, or the probe proves nothing

    data = build_site_data(s, bets, forecasts, sources, lessons, date(2026, 10, 17), NOW)
    assert data["name"] == "Kairos" and data["generation"] == 3
    assert data["day"] == 22 and data["diploma_day"] == 56 and data["diploma_in"] == 34
    assert data["alive"] is True and data["death_date"] is None and data["diploma"] is None
    assert data["equity_cents"] == 10_210 and data["bankroll_cents"] == 9_900 and data["delta_cents"] == 210
    assert data["hunger_total_cents"] == 1_375 and data["health"] == 0.851
    assert data["mood"] == "En chasse"
    assert data["last_run"] == NOW.isoformat() and data["updated_at"] == NOW.isoformat()
    assert data["message"] == "Message de test" and data["message_date"] == "2026-10-16"
    assert data["history"] == [{"date": "2026-10-15", "equity_cents": 10_050}, {"date": "2026-10-16", "equity_cents": 10_210}]
    assert data["clv"] == {"beats": 2, "total": 3}
    assert data["streak"] == current_streak(bets) == 2
    assert data["rank"] == rank(forecasts, bets)
    assert data["stats"] == {k: stats(bets)[k] for k in ("bets", "won", "roi", "clv_avg")}
    assert data["bets"] == [
        {"league": "Premier League", "kickoff": "2026-10-18T14:00:00Z", "home": "Brighton", "away": "Villa", "selection": "1",
         "odds_sim": 2.18, "odds_median": 2.30, "stake_cents": 310, "payout_cents": None, "status": "open",
         "p_kairos": 0.5, "p_market": 0.42, "closing_odds": None},
        {"league": "LaLiga", "kickoff": "2026-10-15T20:00:00Z", "home": "Séville", "away": "Betis", "selection": "X",
         "odds_sim": 3.10, "odds_median": 3.30, "stake_cents": 400, "payout_cents": 1240, "status": "won",
         "p_kairos": 0.36, "p_market": 0.31, "closing_odds": 3.20},
        {"league": "Bundesliga", "kickoff": "2026-10-13T18:00:00Z", "home": "Bayern", "away": "Dortmund", "selection": "2",
         "odds_sim": 1.90, "odds_median": 2.00, "stake_cents": 200, "payout_cents": 380, "status": "won",
         "p_kairos": 0.55, "p_market": 0.50, "closing_odds": 2.10},
        {"league": "Serie A", "kickoff": "2026-10-12T15:00:00Z", "home": "Inter", "away": "Milan", "selection": "1",
         "odds_sim": 2.50, "odds_median": 2.40, "stake_cents": 250, "payout_cents": 0, "status": "lost",
         "p_kairos": 0.45, "p_market": 0.42, "closing_odds": 2.30},
        {"league": "Premier League", "kickoff": "2026-10-11T12:00:00Z", "home": "Arsenal", "away": "Chelsea", "selection": "X",
         "odds_sim": 3.00, "odds_median": 3.10, "stake_cents": 150, "payout_cents": 150, "status": "void",
         "p_kairos": 0.30, "p_market": 0.28, "closing_odds": None},
    ]
    assert data["lessons"] == ["une leçon (3 cas)", "seconde leçon"]
    assert data["sources"] == [{"id": "compos", "description": "Compos", "status": "kept", "uses": 12, "score": 0.01}]
    assert data["trophies"][0] == {"id": "premier_gain", "label": "Premier pari gagné", "date": "2026-10-14"}
    assert len(data["trophies"]) == 7 and all(t["date"] is None for t in data["trophies"][1:])

    dead = dict(s, alive=False, death_date="2026-10-20")
    dead_data = build_site_data(dead, bets, forecasts, sources, lessons, date(2026, 10, 17), NOW)
    assert dead_data["alive"] is False and dead_data["death_date"] == "2026-10-20"
    assert dead_data["health"] == 0.0 and dead_data["mood"] == "Éteint"
