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
