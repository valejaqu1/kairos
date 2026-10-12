from datetime import date

from kairos.metrics import (TROPHIES, check_diploma, current_streak, equity_cents, rank, stats, update_sources,
                            update_trophies)
from kairos.store import new_state


def fc(sk, sm, sources=("a",)):
    return {"outcome": 0, "rps_kairos": sk, "rps_market": sm, "sources": list(sources)}


def b(status, stake=100, payout=0, odds=2.0, closing=None, settled="2026-10-20", kickoff="2026-10-19T14:00:00Z"):
    return {"status": status, "stake_cents": stake, "payout_cents": payout, "odds_median": odds, "closing_odds": closing,
            "settled_date": settled, "commence_time": kickoff, "date": "2026-10-18"}


def test_update_sources_statuses():
    sources = {"a": {"status": "test"}, "b": {"status": "test"}, "c": {"status": "test"}}
    forecasts = [fc(0.10, 0.12, ["a", "b"]) for _ in range(10)] + [fc(0.30, 0.12, ["b"]) for _ in range(5)] + [fc(0.1, 0.1, ["c"])]
    update_sources(sources, forecasts)
    assert sources["a"]["status"] == "kept" and sources["a"]["uses"] == 10
    assert sources["b"]["status"] == "dropped"
    assert sources["c"]["status"] == "test"


def test_rank_tiers():
    assert rank([], [])["tier"] == "Bronze" and rank([], [])["division"] == "I"
    good = [fc(0.1, 0.2) for _ in range(30)]
    assert rank(good, [])["tier"] == "Platine"
    half = [fc(0.1, 0.2) for _ in range(15)] + [fc(0.2, 0.1) for _ in range(15)]
    r = rank(half, [])
    assert r["tier"] == "Argent" and r["division"] == "II" and r["next"] == "Argent III"


def test_streak_and_trophies():
    bets = [b("lost", settled="2026-10-18"), b("won", 100, 200, settled="2026-10-19"), b("won", 100, 200, settled="2026-10-20"),
            b("won", 100, 200, settled="2026-10-21")]
    assert current_streak(bets) == 3
    s = new_state(date(2026, 10, 1))
    new = update_trophies(s, bets, {"x": {"status": "kept"}}, date(2026, 10, 29))
    assert set(new) == {"premier_gain", "serie_3", "source_gardee", "survie_4_semaines"}
    assert update_trophies(s, bets, {}, date(2026, 10, 30)) == []
    assert set(TROPHIES) >= set(new)


def test_stats():
    bets = [b("won", 200, 436, odds=2.27, closing=2.05), b("lost", 100, 0, odds=3.2, closing=3.45), b("open", 300)]
    st = stats(bets)
    assert st["bets"] == 2 and st["won"] == 1
    assert round(st["roi"], 4) == round((436 - 300) / 300, 4)
    assert st["clv_beats"] == 1 and st["clv_total"] == 2


def test_diploma_once_at_day_56():
    s = new_state(date(2026, 10, 1))
    good_fc = [fc(0.1, 0.2) for _ in range(5)]
    good_bets = [b("won", 100, 300, odds=2.5, closing=2.2) for _ in range(3)]
    assert check_diploma(s, good_bets, good_fc, date(2026, 11, 24)) is None
    assert check_diploma(s, good_bets, good_fc, date(2026, 11, 25)) == "obtenu"
    assert check_diploma(s, good_bets, good_fc, date(2026, 11, 26)) is None
    s2 = new_state(date(2026, 10, 1))
    s2["bankroll_cents"] = 9_000
    assert check_diploma(s2, good_bets, good_fc, date(2026, 11, 25)) == "manqué"


def test_equity_includes_open_stakes():
    s = new_state(date(2026, 10, 1))
    s["bankroll_cents"] = 9_580
    assert equity_cents(s, [b("open", 420), b("lost", 100)]) == 10_000


# --- Tests complémentaires : branches non couvertes par la liste du plan ---


def fc_unsettled(sources=("u",)):
    return {"outcome": None, "rps_kairos": 0.1, "rps_market": 0.2, "sources": list(sources)}


def seq(*statuses):
    return [b(st, 100, 200 if st == "won" else 0, settled=f"2026-10-{i + 1:02d}") for i, st in enumerate(statuses)]


def clv_bets(signs):
    closing = {"+": 1.9, "-": 2.1, "0": 2.0}
    return [b("lost", 100, 0, odds=2.0, closing=closing[s], settled=f"2026-09-{i + 1:02d}") for i, s in enumerate(signs)]


def test_update_sources_edge_cases():
    sources = {"z": {"status": "test"}, "p9": {"status": "test"}, "n": {"status": "test"}, "u": {"status": "test"}}
    forecasts = ([fc(0.1, 0.1, ["z"]) for _ in range(10)] + [fc(0.1, 0.2, ["p9"]) for _ in range(9)]
                 + [fc_unsettled(["u"]) for _ in range(10)])
    update_sources(sources, forecasts)
    assert sources["z"]["score"] == 0.0 and sources["z"]["status"] == "dropped"
    assert sources["p9"]["uses"] == 9 and sources["p9"]["status"] == "test"
    assert sources["n"]["uses"] == 0 and sources["n"]["score"] is None and sources["n"]["status"] == "test"
    assert sources["u"]["uses"] == 0 and sources["u"]["status"] == "test"


def test_update_sources_score_value():
    sources = {"a": {"status": "test"}, "b": {"status": "test"}}
    forecasts = [fc(0.10, 0.12, ["a", "b"]) for _ in range(10)] + [fc(0.30, 0.12, ["b"]) for _ in range(5)]
    update_sources(sources, forecasts)
    assert sources["a"]["score"] == 0.02
    assert sources["b"]["score"] == -0.0467


def test_rank_tier_boundaries():
    r = rank([fc(0.1, 0.2) for _ in range(9)] + [fc(0.2, 0.1) for _ in range(11)], [])
    assert (r["tier"], r["division"], r["next"], r["progress"]) == ("Argent", "I", "Argent II", 0.0)
    r = rank([fc(0.1, 0.2) for _ in range(11)] + [fc(0.2, 0.1) for _ in range(9)], [])
    assert (r["tier"], r["division"], r["next"], r["progress"]) == ("Or", "I", "Or II", 0.0)


def test_rank_bronze_iii_next_is_argent_i():
    r = rank([fc(0.1, 0.2) for _ in range(12)] + [fc(0.2, 0.1) for _ in range(18)], [])
    assert (r["tier"], r["division"], r["next"]) == ("Bronze", "III", "Argent I")


def test_rank_or_tier_next_is_platine():
    r = rank([fc(0.1, 0.2) for _ in range(18)] + [fc(0.2, 0.1) for _ in range(12)], [])
    assert (r["tier"], r["division"], r["next"]) == ("Or", "III", "Platine")
    assert r["progress"] == 0.143


def test_rank_platine_threshold_is_062_not_061():
    # (18/30 + 5/8) / 2 = 0,6125 : encore Or, pas Platine
    r = rank([fc(0.1, 0.2) for _ in range(18)] + [fc(0.2, 0.1) for _ in range(12)], clv_bets("+" * 5 + "-" * 3))
    assert (r["tier"], r["next"]) == ("Or", "Platine")


def test_rank_platine_threshold_is_inclusive():
    # (16/25 + 6/10) / 2 = 0,62 exactement : le seuil Platine est inclus
    fcs = [fc(0.1, 0.2) for _ in range(16)] + [fc(0.2, 0.1) for _ in range(9)]
    r = rank(fcs, clv_bets("+" * 6 + "-" * 4))
    assert r["score"] == 0.62
    assert (r["tier"], r["division"], r["next"], r["progress"]) == ("Platine", None, None, 1.0)


def test_rank_averages_forecast_and_clv_parts():
    # part forecasts 1,0 et part CLV 0,0 : moyenne 0,5 (Argent II, progression 0,5)
    r = rank([fc(0.1, 0.2) for _ in range(30)], clv_bets("-" * 10))
    assert (r["tier"], r["division"], r["score"], r["progress"]) == ("Argent", "II", 0.5, 0.5)


def test_rank_counts_only_strictly_positive_values():
    # skill nulle et CLV nulle ne comptent pas : 5/15 pour chaque part, score 0,333
    fcs = [fc(0.1, 0.1) for _ in range(5)] + [fc(0.1, 0.2) for _ in range(5)] + [fc(0.2, 0.1) for _ in range(5)]
    assert rank(fcs, clv_bets("0" * 5 + "+" * 5 + "-" * 5))["score"] == 0.333


def test_rank_window_is_last_30_forecasts():
    fcs = [fc(0.1, 0.2), fc(0.1, 0.2)] + [fc(0.2, 0.1) for _ in range(29)]
    assert rank(fcs, [])["score"] == 0.033


def test_rank_window_is_last_20_clv_bets():
    assert rank([], clv_bets("+-" + "+" * 5 + "-" * 14))["score"] == 0.25


def test_streak_resets_and_keeps_best_run():
    bets = seq("won", "won", "won", "lost", "won", "won")
    assert current_streak(bets) == 2
    new = update_trophies(new_state(date(2026, 10, 1)), bets, {}, date(2026, 10, 25))
    assert set(new) == {"premier_gain", "serie_3"}


def test_serie_3_and_serie_5_thresholds():
    today = date(2026, 10, 25)
    assert "serie_3" not in update_trophies(new_state(date(2026, 10, 1)), seq("won", "won"), {}, today)
    four = update_trophies(new_state(date(2026, 10, 1)), seq(*["won"] * 4), {}, today)
    assert "serie_3" in four and "serie_5" not in four
    assert "serie_5" in update_trophies(new_state(date(2026, 10, 1)), seq(*["won"] * 5), {}, today)


def test_current_streak_uses_chronological_order():
    bets = [b("won", 100, 200, settled="2026-10-21"), b("won", 100, 200, settled="2026-10-20"),
            b("lost", settled="2026-10-18"), b("won", 100, 200, settled="2026-10-19")]
    assert current_streak(bets) == 3


def test_trophy_premier_gain_needs_a_win_and_stores_the_date():
    s = new_state(date(2026, 10, 1))
    assert update_trophies(s, seq("lost", "lost", "lost"), {}, date(2026, 10, 20)) == []
    assert update_trophies(s, seq("won"), {}, date(2026, 10, 20)) == ["premier_gain"]
    assert s["trophies"]["premier_gain"] == "2026-10-20"


def test_survie_trophy_needs_day_28_and_being_alive():
    s = new_state(date(2026, 10, 1))
    assert "survie_4_semaines" not in update_trophies(s, [], {}, date(2026, 10, 27))
    assert "survie_4_semaines" in update_trophies(s, [], {}, date(2026, 10, 28))
    dead = new_state(date(2026, 10, 1))
    dead["alive"] = False
    assert "survie_4_semaines" not in update_trophies(dead, [], {}, date(2026, 10, 30))


def test_diplome_trophy_only_when_obtenu():
    s = new_state(date(2026, 10, 1))
    s["diploma"] = "obtenu"
    assert "diplome" in update_trophies(s, [], {}, date(2026, 11, 25))
    manque = new_state(date(2026, 10, 1))
    manque["diploma"] = "manqué"
    assert "diplome" not in update_trophies(manque, [], {}, date(2026, 11, 25))


def test_clv_10_trophy_needs_ten_strictly_positive_clv_bets():
    today = date(2026, 10, 20)
    assert "clv_10" in update_trophies(new_state(date(2026, 10, 1)), clv_bets("+" * 10), {}, today)
    assert "clv_10" not in update_trophies(new_state(date(2026, 10, 1)), clv_bets("+" * 9 + "0"), {}, today)


def test_stats_edge_cases():
    assert stats([]) == {"bets": 0, "won": 0, "roi": 0.0, "clv_avg": 0.0, "clv_beats": 0, "clv_total": 0}
    no_closing = stats([b("won", 100, 200)])
    assert (no_closing["roi"], no_closing["clv_total"], no_closing["clv_avg"], no_closing["clv_beats"]) == (1.0, 0, 0.0, 0)
    zero = stats([b("lost", 100, 0, odds=2.0, closing=2.0)])
    assert (zero["clv_total"], zero["clv_beats"]) == (1, 0)


def test_stats_clv_average():
    st = stats(clv_bets("+-"))
    assert round(st["clv_avg"], 4) == 0.0025
    assert (st["clv_beats"], st["clv_total"]) == (1, 2)


def test_diploma_manque_for_each_failing_condition():
    day = date(2026, 11, 25)
    good_fc = [fc(0.1, 0.2) for _ in range(5)]
    good_bets = [b("won", 100, 300, odds=2.5, closing=2.2) for _ in range(3)]

    def fresh(**changes):
        s = new_state(date(2026, 10, 1))
        s.update(changes)
        return s

    assert check_diploma(fresh(alive=False), good_bets, good_fc, day) == "manqué"
    assert check_diploma(fresh(), good_bets, [], day) == "manqué"
    assert check_diploma(fresh(), good_bets, [fc(0.1, 0.1) for _ in range(5)], day) == "manqué"
    assert check_diploma(fresh(), good_bets, [fc(0.2, 0.1) for _ in range(5)], day) == "manqué"
    assert check_diploma(fresh(), [b("won", 100, 300, odds=2.5) for _ in range(3)], good_fc, day) == "manqué"
    assert check_diploma(fresh(), good_bets, good_fc, day) == "obtenu"


def test_diploma_clv_share_boundary():
    day = date(2026, 11, 25)
    good_fc = [fc(0.1, 0.2) for _ in range(5)]
    pos = b("won", 100, 300, odds=2.5, closing=2.2)
    neg = b("won", 100, 300, odds=2.0, closing=2.2)
    zero = b("won", 100, 300, odds=2.0, closing=2.0)
    assert check_diploma(new_state(date(2026, 10, 1)), [pos] * 10 + [neg] * 10, good_fc, day) == "manqué"
    assert check_diploma(new_state(date(2026, 10, 1)), [pos] * 10 + [zero] * 10, good_fc, day) == "manqué"
    assert check_diploma(new_state(date(2026, 10, 1)), [pos] * 11 + [neg] * 9, good_fc, day) == "obtenu"
