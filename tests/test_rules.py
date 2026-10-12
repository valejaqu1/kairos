from datetime import date, datetime, timezone

from kairos.rules import (LESSONS_HEADER, accept_forecasts, place_bets, register_sources, stake_cents,
                          update_lessons, validate_decisions)
from kairos.store import new_state

TODAY = date(2026, 10, 17)
NOW = datetime(2026, 10, 17, 9, 30, tzinfo=timezone.utc)
EV = {
    "e1": {"event_id": "e1", "sport_key": "soccer_epl", "home": "Brighton and Hove Albion", "away": "Aston Villa",
           "commence_time": "2026-10-18T14:00:00Z", "median": {"1": 2.30, "X": 3.50, "2": 3.20},
           "sim": {"1": 2.18, "X": 3.32, "2": 3.04}, "n_books": 3, "p_market": [0.42, 0.28, 0.30]},
    "e2": {"event_id": "e2", "sport_key": "soccer_epl", "home": "A", "away": "B",
           "commence_time": "2026-10-17T09:35:00Z", "median": {"1": 2.0, "X": 3.4, "2": 3.9},
           "sim": {"1": 1.9, "X": 3.23, "2": 3.7}, "n_books": 3, "p_market": [0.48, 0.28, 0.24]},
}


def dec(**kw):
    base = {"date": "2026-10-17", "forecasts": [], "bets": [], "message": "Bonjour", "new_source": None, "lessons": None}
    base.update(kw)
    return base


def test_validate_decisions():
    assert validate_decisions(dec(), TODAY) == []
    errs = validate_decisions(dec(date="2026-10-16", message="x" * 601, bets="nope"), TODAY)
    assert "date incorrecte" in errs and "message trop long" in errs and "bets doit être une liste" in errs


def test_register_sources_one_new_per_day():
    sources = {"compos": {"status": "kept"}}
    d = dec(new_source={"id": "presse-ch", "description": "Presse locale", "url": "https://x"})
    assert register_sources(d, sources, TODAY) == "presse-ch"
    assert sources["presse-ch"]["status"] == "test" and sources["presse-ch"]["first_seen"] == "2026-10-17"


def test_accept_forecasts_normalises_and_filters_sources():
    sources = {"compos": {"status": "kept"}, "forum": {"status": "dropped"}}
    d = dec(forecasts=[
        {"event_id": "e1", "p": [0.5, 0.3, 0.21], "sources": ["compos", "forum", "inconnue"], "note": "n"},
        {"event_id": "zz", "p": [0.5, 0.3, 0.2], "sources": []},
        {"event_id": "e2", "p": [0.9, 0.3, 0.2], "sources": []},
    ])
    acc, rej = accept_forecasts(d, EV, {"e1": [0.45, 0.27, 0.28]}, sources, TODAY)
    assert len(acc) == 1
    f = acc[0]
    assert abs(sum(f["p_kairos"]) - 1) < 1e-3
    assert f["sources"] == ["compos"]
    assert f["p_model"] == [0.45, 0.27, 0.28] and f["p_market"] == [0.42, 0.28, 0.30]
    assert ("zz", "match inconnu") in rej
    assert ("e2", "les probabilités ne somment pas à 1") in rej


def test_stake_quarter_kelly_capped_and_rounded():
    assert stake_cents(0.55, 2.18, 10_000) == 420
    assert stake_cents(0.80, 2.18, 10_000) == 500
    assert stake_cents(0.50, 2.18, 10_000) == 0
    assert stake_cents(0.47, 2.18, 10_000) == 0
    assert stake_cents(0.55, 2.18, 2_000) == 0


def test_place_bets_refuses_odds_below_jouezsport_floor():
    s = new_state(date(2026, 10, 1))
    events = {"e9": {**EV["e1"], "event_id": "e9", "sim": {"1": 1.08, "X": 9.0, "2": 20.0}, "median": {"1": 1.14, "X": 9.5, "2": 21.0}}}
    placed, rej = place_bets(dec(bets=[{"event_id": "e9", "selection": "1"}]), {"e9": {"p_kairos": [0.99, 0.005, 0.005]}}, events, s, [], NOW, TODAY)
    assert placed == [] and rej == [("e9", "cote inférieure à 1,10")]


def test_place_bets_applies_all_limits():
    s = new_state(date(2026, 10, 1))
    bets = []
    fbe = {"e1": {"p_kairos": [0.55, 0.25, 0.20]}, "e2": {"p_kairos": [0.6, 0.2, 0.2]}}
    d = dec(bets=[
        {"event_id": "e1", "selection": "1", "reasoning": "retour du buteur"},
        {"event_id": "e1", "selection": "1"},
        {"event_id": "e2", "selection": "1"},
        {"event_id": "e1", "selection": "Z"},
    ])
    placed, rej = place_bets(d, fbe, EV, s, bets, NOW, TODAY)
    assert len(placed) == 1
    b = placed[0]
    assert b["stake_cents"] == 420 and b["odds_sim"] == 2.18 and b["status"] == "open"
    assert s["bankroll_cents"] == 9_580
    reasons = [r for _, r in rej]
    assert "déjà un pari sur ce match" in reasons
    assert "match trop proche ou déjà commencé" in reasons
    assert "issue invalide" in reasons


def test_place_bets_max_three_per_day():
    s = new_state(date(2026, 10, 1))
    bets = [{"date": "2026-10-17", "status": "open", "event_id": f"x{i}", "stake_cents": 100} for i in range(3)]
    placed, rej = place_bets(dec(bets=[{"event_id": "e1", "selection": "1"}]), {"e1": {"p_kairos": [0.6, 0.2, 0.2]}}, EV, s, bets, NOW, TODAY)
    assert placed == [] and rej == [("e1", "déjà 3 paris aujourd'hui")]


def test_update_lessons_only_on_sunday_with_limits():
    text = LESSONS_HEADER + "- vieille leçon (3 cas)\n"
    changes = {"add": ["a (2 cas)", "b (4 cas)", "c (5 cas)"], "remove": ["vieille leçon (3 cas)"]}
    same, notes = update_lessons(text, changes, date(2026, 10, 17))
    assert same == text and notes == ["leçons ignorées : on ne les modifie que le dimanche"]
    new, notes = update_lessons(text, changes, date(2026, 10, 18))
    assert new == LESSONS_HEADER + "- a (2 cas)\n- b (4 cas)\n"
    assert "1 ajout ignoré (2 au maximum)" in notes


# Tests supplémentaires : branches non couvertes par la liste du brief.


def event(eid, **kw):
    return {**EV["e1"], "event_id": eid, **kw}


def test_validate_decisions_rejects_malformed_fields():
    assert validate_decisions(["pas", "un", "objet"], TODAY) == ["le fichier n'est pas un objet JSON"]
    assert "forecasts doit être une liste" in validate_decisions(dec(forecasts="x"), TODAY)
    assert validate_decisions(dec(message="   "), TODAY) == ["message manquant"]
    assert validate_decisions(dec(message=None), TODAY) == ["message manquant"]
    assert validate_decisions(dec(message="x" * 600), TODAY) == []


def test_register_sources_ignores_malformed_or_existing_ids():
    sources = {"compos": {"status": "kept"}}
    assert register_sources(dec(), sources, TODAY) is None
    assert register_sources(dec(new_source={"description": "sans id"}), sources, TODAY) is None
    assert register_sources(dec(new_source={"id": "   "}), sources, TODAY) is None
    assert register_sources(dec(new_source={"id": 42}), sources, TODAY) is None
    assert register_sources(dec(new_source={"id": "compos", "description": "doublon"}), sources, TODAY) is None
    assert sources == {"compos": {"status": "kept"}}
    assert register_sources(dec(new_source={"id": " presse-ch "}), sources, TODAY) == "presse-ch"
    assert "presse-ch" in sources


def test_free_text_is_truncated_to_limits():
    sources = {}
    register_sources(dec(new_source={"id": "src", "description": "d" * 250, "url": "u" * 350}), sources, TODAY)
    assert len(sources["src"]["description"]) == 200 and len(sources["src"]["url"]) == 300
    acc, _ = accept_forecasts(dec(forecasts=[{"event_id": "e1", "p": [0.5, 0.3, 0.2], "sources": [], "note": "n" * 350}]),
                              EV, {}, {}, TODAY)
    assert len(acc[0]["note"]) == 300
    placed, _ = place_bets(dec(bets=[{"event_id": "e1", "selection": "1", "reasoning": "r" * 450}]),
                           {"e1": {"p_kairos": [0.55, 0.25, 0.20]}}, EV, new_state(date(2026, 10, 1)), [], NOW, TODAY)
    assert len(placed[0]["reasoning"]) == 400
    new, _ = update_lessons(LESSONS_HEADER, {"add": ["x" * 250]}, date(2026, 10, 18))
    assert new == LESSONS_HEADER + "- " + "x" * 200 + "\n"


def test_accept_forecasts_rejects_invalid_probability_types():
    bad = [None, [0.5, 0.5], "0.5,0.3,0.2", ["a", 0.3, 0.2], [-0.1, 0.6, 0.5], [1.2, 0.0, 0.0]]
    acc, rej = accept_forecasts(dec(forecasts=[{"event_id": "e1", "p": p, "sources": []} for p in bad]), EV, {}, {}, TODAY)
    assert acc == [] and rej == [("e1", "probabilités invalides")] * len(bad)
    acc, rej = accept_forecasts(dec(forecasts=[
        {"event_id": "e1", "p": [0, 0.5, 0.5], "sources": []},
        {"event_id": "e2", "p": [0.5, 0.3, 0.1], "sources": []},
    ]), EV, {}, {}, TODAY)
    assert [f["event_id"] for f in acc] == ["e1"] and acc[0]["p_kairos"] == [0.0, 0.5, 0.5]
    assert rej == [("e2", "les probabilités ne somment pas à 1")]


def test_probability_sum_tolerance_window():
    ids = ["lo_ok", "lo_no", "hi_ok", "hi_no"]
    events = {i: event(i) for i in ids}
    ps = {"lo_ok": [0.5, 0.3, 0.185], "lo_no": [0.5, 0.3, 0.175], "hi_ok": [0.5, 0.3, 0.215], "hi_no": [0.5, 0.3, 0.225]}
    acc, rej = accept_forecasts(dec(forecasts=[{"event_id": i, "p": ps[i], "sources": []} for i in ids]), events, {}, {}, TODAY)
    assert [f["event_id"] for f in acc] == ["lo_ok", "hi_ok"]
    assert rej == [("lo_no", "les probabilités ne somment pas à 1"), ("hi_no", "les probabilités ne somment pas à 1")]


def test_accept_forecasts_normalises_to_four_decimals():
    acc, _ = accept_forecasts(dec(forecasts=[{"event_id": "e1", "p": [0.5, 0.3, 0.21], "sources": []}]), EV, {}, {}, TODAY)
    assert acc[0]["p_kairos"] == [0.495, 0.297, 0.2079]


def test_accept_forecasts_keeps_first_ten_and_ignores_non_string_sources():
    events = {f"m{i}": event(f"m{i}") for i in range(11)}
    d = dec(forecasts=[{"event_id": f"m{i}", "p": [0.5, 0.3, 0.2], "sources": ["compos", ["compos"], {"x": 1}, 5]}
                       for i in range(11)])
    acc, rej = accept_forecasts(d, events, {}, {"compos": {"status": "kept"}}, TODAY)
    assert len(acc) == 10 and rej == [] and acc[-1]["event_id"] == "m9"
    assert all(f["sources"] == ["compos"] for f in acc)


def test_place_bets_needs_a_forecast_and_an_event():
    s = new_state(date(2026, 10, 1))
    d = dec(bets=[{"event_id": "e1", "selection": "1"}])
    reason = [("e1", "pas de prévision acceptée pour ce match")]
    assert place_bets(d, {}, EV, s, [], NOW, TODAY) == ([], reason)
    assert place_bets(d, {"e1": {"p_kairos": [0.55, 0.25, 0.20]}}, {}, s, [], NOW, TODAY) == ([], reason)
    assert s["bankroll_cents"] == 10_000


def test_existing_open_bet_blocks_match_and_settled_bet_does_not():
    s = new_state(date(2026, 10, 1))
    s["bankroll_cents"] = 9_000
    bets = [{"date": "2026-10-16", "status": "open", "event_id": "e1", "stake_cents": 1_000},
            {"date": "2026-10-16", "status": "lost", "event_id": "e3", "stake_cents": 100},
            {"date": "2026-10-16", "status": "lost", "event_id": "e4", "stake_cents": 100}]
    fbe = {"e1": {"p_kairos": [0.55, 0.25, 0.20]}, "e3": {"p_kairos": [0.55, 0.25, 0.20]}}
    placed, rej = place_bets(dec(bets=[{"event_id": "e1", "selection": "1"}, {"event_id": "e3", "selection": "1"}]),
                             fbe, {**EV, "e3": event("e3")}, s, bets, NOW, TODAY)
    assert [b["event_id"] for b in placed] == ["e3"] and placed[0]["stake_cents"] == 420
    assert rej == [("e1", "déjà un pari sur ce match")]


def test_place_bets_reports_why_a_stake_is_zero():
    s = new_state(date(2026, 10, 1))
    d = dec(bets=[{"event_id": "e1", "selection": "1"}])
    assert place_bets(d, {"e1": {"p_kairos": [0.47, 0.30, 0.23]}}, EV, s, [], NOW, TODAY) == (
        [], [("e1", "valeur insuffisante (+2.5%)")])
    assert place_bets(d, {"e1": {"p_kairos": [0.50, 0.30, 0.20]}}, EV, s, [], NOW, TODAY) == (
        [], [("e1", "mise inférieure à 2 CHF")])


def test_place_bets_accepts_odds_at_the_floor_and_records_the_selection():
    s = new_state(date(2026, 10, 1))
    events = {"e4": event("e4", sim={"1": 1.10, "X": 9.0, "2": 3.04})}
    placed, rej = place_bets(dec(bets=[{"event_id": "e4", "selection": "1"}]), {"e4": {"p_kairos": [0.96, 0.02, 0.02]}},
                             events, s, [], NOW, TODAY)
    assert rej == [] and placed[0]["stake_cents"] == 500 and placed[0]["odds_sim"] == 1.10
    bets = []
    placed, _ = place_bets(dec(bets=[{"event_id": "e5", "selection": "2"}]), {"e5": {"p_kairos": [0.20, 0.25, 0.55]}},
                           {"e5": event("e5")}, new_state(date(2026, 10, 1)), bets, NOW, TODAY)
    b = placed[0]
    assert b == bets[0]
    assert b["id"] == "2026-10-17-e5-2" and b["selection"] == "2" and b["odds_sim"] == 3.04
    assert b["odds_median"] == 3.20 and b["p_kairos"] == 0.55 and b["p_market"] == 0.30


def test_place_bets_respects_exposure_cap():
    s = new_state(date(2026, 10, 1))
    s["bankroll_cents"] = 9_000
    placed, _ = place_bets(dec(bets=[{"event_id": "e1", "selection": "1"}]), {"e1": {"p_kairos": [0.55, 0.25, 0.20]}},
                           EV, s, [{"date": "2026-10-16", "status": "open", "event_id": "old", "stake_cents": 1_000}],
                           NOW, TODAY)
    assert placed[0]["stake_cents"] == 420
    s = new_state(date(2026, 10, 1))
    s["bankroll_cents"] = 8_600
    placed, rej = place_bets(dec(bets=[{"event_id": "e1", "selection": "1"}]), {"e1": {"p_kairos": [0.55, 0.25, 0.20]}},
                             EV, s, [{"date": "2026-10-16", "status": "open", "event_id": "old", "stake_cents": 1_400}],
                             NOW, TODAY)
    assert placed == [] and rej == [("e1", "exposition maximale atteinte")]
    assert s["bankroll_cents"] == 8_600


def test_place_bets_refuses_stake_above_bankroll(monkeypatch):
    # Avec le plafond d'exposition de 15 %, ce garde est masqué : on le teste isolément.
    monkeypatch.setattr("kairos.rules.MAX_EXPOSURE_SHARE", 2.0)
    s = new_state(date(2026, 10, 1))
    s["bankroll_cents"] = 300
    placed, rej = place_bets(dec(bets=[{"event_id": "e1", "selection": "1"}]), {"e1": {"p_kairos": [0.55, 0.25, 0.20]}},
                             EV, s, [{"date": "2026-10-16", "status": "open", "event_id": "old", "stake_cents": 9_700}],
                             NOW, TODAY)
    assert placed == [] and rej == [("e1", "cagnotte insuffisante")]
    assert s["bankroll_cents"] == 300


def test_kickoff_margin_is_inclusive_at_ten_minutes():
    s = new_state(date(2026, 10, 1))
    fc = {"p_kairos": [0.55, 0.25, 0.20]}
    placed, rej = place_bets(dec(bets=[{"event_id": "e6", "selection": "1"}]), {"e6": fc},
                             {"e6": event("e6", commence_time="2026-10-17T09:40:00Z")}, s, [], NOW, TODAY)
    assert placed == [] and rej == [("e6", "match trop proche ou déjà commencé")]
    placed, _ = place_bets(dec(bets=[{"event_id": "e7", "selection": "1"}]), {"e7": fc},
                           {"e7": event("e7", commence_time="2026-10-17T09:40:01Z")}, s, [], NOW, TODAY)
    assert len(placed) == 1


def test_place_bets_caps_one_decision_at_three_bets():
    s = new_state(date(2026, 10, 1))
    ids = ["m1", "m2", "m3", "m4"]
    events = {i: event(i) for i in ids}
    fbe = {i: {"p_kairos": [0.55, 0.25, 0.20]} for i in ids}
    placed, rej = place_bets(dec(bets=[{"event_id": i, "selection": "1"} for i in ids]), fbe, events, s, [], NOW, TODAY)
    assert [b["event_id"] for b in placed] == ["m1", "m2", "m3"]
    assert rej == [("m4", "déjà 3 paris aujourd'hui")]
    assert s["bankroll_cents"] == 10_000 - 3 * 420


def test_stake_minimum_is_inclusive_at_two_chf():
    assert stake_cents(0.55, 2.18, 4_800) == 200
    assert stake_cents(0.55, 2.18, 4_700) == 0


def test_update_lessons_caps_the_list_at_fifteen():
    text = LESSONS_HEADER + "".join(f"- l{i}\n" for i in range(15))
    new, notes = update_lessons(text, {"add": ["x", "y"], "remove": ["l0"]}, date(2026, 10, 18))
    assert new == LESSONS_HEADER + "".join(f"- l{i}\n" for i in range(1, 15)) + "- x\n"
    assert notes == ["ajout ignoré : déjà 15 leçons"]
    new, notes = update_lessons(text, {"add": ["x", "y"]}, date(2026, 10, 18))
    assert new == text and notes == ["ajout ignoré : déjà 15 leçons"]


def test_update_lessons_edge_inputs():
    text = LESSONS_HEADER + "- a\n"
    assert update_lessons(text, None, date(2026, 10, 18)) == (text, [])
    assert update_lessons(text, {"add": [], "remove": None}, date(2026, 10, 18)) == (text, [])
    assert update_lessons(text, {"add": ["  ", "b"], "remove": ["absent"]}, date(2026, 10, 18)) == (
        LESSONS_HEADER + "- a\n- b\n", [])


def test_validate_decisions_rejects_non_object_elements():
    assert validate_decisions(dec(forecasts=["oops"]), TODAY) == ["forecasts contient un élément invalide"]
    assert validate_decisions(dec(bets=[{"event_id": "e1", "selection": "1"}, "e1"]), TODAY) == [
        "bets contient un élément invalide"]
    assert validate_decisions(dec(forecasts=[{"event_id": "e1", "p": [0.5, 0.3, 0.2], "sources": []}]), TODAY) == []


def test_accept_forecasts_rejects_boolean_probabilities():
    d = dec(forecasts=[{"event_id": "e1", "p": [True, False, False], "sources": []}])
    acc, rej = accept_forecasts(d, EV, {}, {}, TODAY)
    assert acc == [] and rej == [("e1", "probabilités invalides")]


def fc(**kw):
    base = {"event_id": "e1", "p": [0.5, 0.3, 0.2], "sources": []}
    base.update(kw)
    return base


def bet(**kw):
    base = {"event_id": "e1", "selection": "1"}
    base.update(kw)
    return base


def test_validate_decisions_rejects_bad_forecast_fields():
    assert validate_decisions(dec(forecasts=[fc(event_id=1)]), TODAY) == ["forecasts[0].event_id doit être un texte"]
    assert validate_decisions(dec(forecasts=[fc(p="0.5,0.3,0.2")]), TODAY) == ["forecasts[0].p doit être une liste"]
    assert validate_decisions(dec(forecasts=[fc(sources=None)]), TODAY) == [
        "forecasts[0].sources doit être une liste de textes"]
    assert validate_decisions(dec(forecasts=[fc(sources=[1])]), TODAY) == [
        "forecasts[0].sources doit être une liste de textes"]
    assert validate_decisions(dec(forecasts=[fc(), fc(note=5)]), TODAY) == ["forecasts[1].note doit être un texte"]
    assert validate_decisions(dec(forecasts=[fc(sources=["compos"], note="ok")]), TODAY) == []
    assert validate_decisions(dec(forecasts=[{"event_id": "e1"}]), TODAY) == ["forecasts[0].p doit être une liste"]


def test_validate_decisions_rejects_bad_bet_fields():
    assert validate_decisions(dec(bets=[bet(event_id=1)]), TODAY) == ["bets[0].event_id doit être un texte"]
    assert validate_decisions(dec(bets=[bet(selection=["1"])]), TODAY) == ["bets[0].selection doit être un texte"]
    assert validate_decisions(dec(bets=[bet(reasoning=None)]), TODAY) == ["bets[0].reasoning doit être un texte"]
    assert validate_decisions(dec(bets=[bet(reasoning="retour du buteur")]), TODAY) == []


def test_validate_decisions_rejects_bad_new_source_and_lessons():
    assert validate_decisions(dec(new_source="presse"), TODAY) == ["new_source doit être un objet ou null"]
    assert validate_decisions(dec(new_source={"id": "presse-ch"}), TODAY) == []
    assert validate_decisions(dec(lessons="texte"), TODAY) == ["lessons doit être un objet ou null"]
    assert validate_decisions(dec(lessons={"add": "une leçon"}), TODAY) == ["lessons.add doit être une liste de textes"]
    assert validate_decisions(dec(lessons={"add": ["a", 1], "remove": None}), TODAY) == [
        "lessons.add doit être une liste de textes", "lessons.remove doit être une liste de textes"]
    assert validate_decisions(dec(lessons={"add": ["a"], "remove": ["b"]}), TODAY) == []
    assert validate_decisions(dec(lessons=None), TODAY) == []


def test_update_lessons_counts_each_lesson_as_one_line():
    new, notes = update_lessons(LESSONS_HEADER, {"add": ["a\n- b\n- c"]}, date(2026, 10, 18))
    assert new == LESSONS_HEADER + "- a - b - c\n" and notes == []
    text = LESSONS_HEADER + "".join(f"- l{i}\n" for i in range(14))
    new, notes = update_lessons(text, {"add": ["a\n- b\n- c", "d"]}, date(2026, 10, 18))
    assert new == text + "- a - b - c\n" and notes == ["ajout ignoré : déjà 15 leçons"]


def test_update_lessons_matches_removals_after_normalisation():
    text = LESSONS_HEADER + "- b c\n- z\n"
    new, _ = update_lessons(text, {"remove": ["b\nc"]}, date(2026, 10, 18))
    assert new == LESSONS_HEADER + "- z\n"


def test_accept_forecasts_rejects_a_second_forecast_for_the_same_event():
    acc, rej = accept_forecasts(dec(forecasts=[fc(), fc()]), EV, {}, {}, TODAY)
    assert len(acc) == 1 and rej == [("e1", "doublon")]
    acc, rej = accept_forecasts(dec(forecasts=[fc(p=[0.9, 0.3, 0.2]), fc()]), EV, {}, {}, TODAY)
    assert len(acc) == 1 and rej == [("e1", "les probabilités ne somment pas à 1")]


def test_accept_forecasts_dedupes_then_caps_sources_in_order():
    sources = {k: {"status": "kept"} for k in ["s1", "s2", "s3", "s4", "s5", "s6", "s7"]}
    acc, _ = accept_forecasts(dec(forecasts=[fc(sources=["s3", "s1", "s3", "s2", "s1", "s4", "s5", "s6", "s7"])]),
                              EV, {}, sources, TODAY)
    assert acc[0]["sources"] == ["s3", "s1", "s2", "s4", "s5"]
    acc, _ = accept_forecasts(dec(forecasts=[fc(sources=["s1", "s1"])]), EV, {}, sources, TODAY)
    assert acc[0]["sources"] == ["s1"]
