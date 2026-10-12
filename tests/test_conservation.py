"""Simulation de plusieurs jours par la ligne de commande : l'argent se conserve, rien n'est réglé deux fois.

Les cotes et les scores viennent de fixtures construites ici et réécrites chaque jour pour FakeOddsApi ;
football-data est indisponible (404), donc le modèle l'est aussi. Le calendrier couvre un jour sauté
(le 19), deux passages de prepare et d'apply le même jour, et des paris gagnés, perdus, annulés et ouverts.
"""
import json
from datetime import date, datetime, timezone

from kairos import store
from kairos.api import FakeOddsApi
from kairos.cli import Context, cmd_apply, cmd_prepare
from kairos.metrics import equity_cents
from kairos.store import load_bets, load_state

D1, D2, D4, D5 = date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 20), date(2026, 10, 21)
START = 10_000


class Resp:
    status_code = 404
    content = b""


def no_results(url, timeout):
    return Resp()


def odds_event(eid, home, away, commence):
    h, x, a = 2.40, 3.40, 3.00
    return {"id": eid, "sport_key": "soccer_epl", "commence_time": commence, "home_team": home, "away_team": away,
            "bookmakers": [{"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": h}, {"name": away, "price": a}, {"name": "Draw", "price": x}]}]}]}


def final_score(eid, home, away, commence, home_goals, away_goals):
    return {"id": eid, "sport_key": "soccer_epl", "commence_time": commence, "completed": True, "home_team": home,
            "away_team": away, "scores": [{"name": home, "score": str(home_goals)}, {"name": away, "score": str(away_goals)}]}


A = ("evt-a", "Alpha", "Beta", "2026-10-17T20:00:00Z")    # pari « 1 », gagné (2-0)
B = ("evt-b", "Gamma", "Delta", "2026-10-18T14:00:00Z")  # pari « 1 », perdu (0-1)
C = ("evt-c", "Epsilon", "Zeta", "2026-10-17T21:00:00Z")  # pari « 1 », jamais de score : annulé après 3 jours
D = ("evt-d", "Eta", "Theta", "2026-10-19T15:00:00Z")    # pari « 2 », gagné (0-2), joué pendant le jour sauté
E = ("evt-e", "Iota", "Kappa", "2026-10-21T20:00:00Z")   # pari « 1 », encore ouvert à la fin

SCORES = {
    "A": final_score(*A, 2, 0), "B": final_score(*B, 0, 1), "D": final_score(*D, 0, 2),
}


class Simulation:
    def __init__(self, root, fixtures):
        self.root, self.fixtures = root, fixtures
        self.sent = []
        self.api = FakeOddsApi(fixtures)
        self.applied_days = []
        self.settled = {}  # id du pari -> (statut, versement, date de règlement) vu à son règlement

    def set_market(self, events, scores):
        (self.fixtures / "odds_soccer_epl.json").write_text(json.dumps([odds_event(*e) for e in events]), encoding="utf-8")
        (self.fixtures / "scores_soccer_epl.json").write_text(json.dumps(scores), encoding="utf-8")

    def decide(self, day, bets, forecasts):
        (self.root / "decisions").mkdir(exist_ok=True)
        dec = {"date": day.isoformat(), "message": f"Jour {day.isoformat()}", "new_source": None, "lessons": None,
               "forecasts": [{"event_id": e[0], "p": p, "sources": [], "note": "n"} for e, p in forecasts],
               "bets": [{"event_id": e[0], "selection": sel, "reasoning": "valeur"} for e, sel in bets]}
        (self.root / "decisions" / f"{day.isoformat()}.json").write_text(json.dumps(dec), encoding="utf-8")

    def ctx(self, day, hour, minute):
        now = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)
        return Context(api=self.api, http_get=no_results, notify=self.sent.append, today=day, now=now, page_url="https://x/")

    def run(self, command, day, hour, minute):
        command(self.ctx(day, hour, minute))
        if command is cmd_apply and day not in self.applied_days:
            self.applied_days.append(day)
        self.check(day)

    def check(self, day):
        state, bets = load_state(day), load_bets()
        settled = [b for b in bets if b["status"] != "open"]
        # Conservation : départ - faim - toutes les mises + tout ce qui a été versé (annulé : la mise rendue)
        expected = START - state["hunger_total_cents"] - sum(b["stake_cents"] for b in bets) + sum(b["payout_cents"] for b in settled)
        assert state["bankroll_cents"] == expected, (day, state["bankroll_cents"], expected)
        assert state["hunger_total_cents"] == 25 * (day - date.fromisoformat(state["start_date"])).days  # faim rattrapée, jamais payée deux fois
        assert len({b["id"] for b in bets}) == len(bets)
        for b in settled:
            record = (b["status"], b["payout_cents"], b["settled_date"])
            assert self.settled.setdefault(b["id"], record) == record, f"{b['id']} réglé deux fois"
        for b in bets:
            if b["status"] == "open":
                assert b["id"] not in self.settled and b["payout_cents"] is None and b["settled_date"] is None
        history = state["history"]
        assert [h["date"] for h in history] == [d.isoformat() for d in self.applied_days]
        if history and history[-1]["date"] == day.isoformat():
            assert history[-1]["equity_cents"] == equity_cents(state, bets)


def test_bankroll_is_conserved_over_five_calendar_days(tmp_root, tmp_path_factory):
    sim = Simulation(tmp_root, tmp_path_factory.mktemp("fixtures"))

    # Jour 1 : trois paris, deux prepare et deux apply
    sim.set_market([A, B, C], [])
    sim.run(cmd_prepare, D1, 8, 15)
    sim.run(cmd_prepare, D1, 8, 45)
    sim.decide(D1, bets=[(A, "1"), (B, "1"), (C, "1")], forecasts=[(A, [0.55, 0.25, 0.20]), (B, [0.55, 0.25, 0.20]), (C, [0.55, 0.25, 0.20])])
    sim.run(cmd_apply, D1, 9, 40)
    after_first_apply = (load_state(D1)["bankroll_cents"], load_bets())
    sim.run(cmd_apply, D1, 9, 50)
    assert (load_state(D1)["bankroll_cents"], load_bets()) == after_first_apply
    assert [b["stake_cents"] for b in load_bets()] == [490, 490, 490]
    assert load_state(D1)["bankroll_cents"] == START - 3 * 490

    # Jour 2 : A est gagné ; B est reprévu (la nouvelle prévision remplace celle du jour 1) ; nouveau pari sur D
    sim.set_market([B, D], [SCORES["A"]])
    sim.run(cmd_prepare, D2, 8, 15)
    assert {b["event_id"]: b["status"] for b in load_bets()} == {"evt-a": "won", "evt-b": "open", "evt-c": "open"}
    sim.decide(D2, bets=[(D, "2")], forecasts=[(B, [0.60, 0.20, 0.20]), (D, [0.20, 0.35, 0.45])])
    sim.run(cmd_apply, D2, 9, 40)
    forecasts = store.load_forecasts()
    assert sorted(f["event_id"] for f in forecasts) == ["evt-a", "evt-b", "evt-c", "evt-d"]  # B n'y figure qu'une fois
    (b_forecast,) = [f for f in forecasts if f["event_id"] == "evt-b"]
    assert b_forecast["date"] == "2026-10-18" and b_forecast["p_kairos"] == [0.6, 0.2, 0.2]
    assert "- prévision remplacée evt-b\n" in (tmp_root / "journal" / "2026-10-18.md").read_text(encoding="utf-8")

    # Jour 3 (19 octobre) : aucun passage, la faim sera rattrapée au jour 4

    # Jour 4 : B perdu et D gagné (joué le jour sauté), deux jours de faim, deux prepare, apply sans décisions
    sim.set_market([], [SCORES["A"], SCORES["B"], SCORES["D"]])
    sim.run(cmd_prepare, D4, 8, 15)
    sim.run(cmd_prepare, D4, 8, 45)
    assert load_state(D4)["hunger_total_cents"] == 75
    assert {b["event_id"]: b["status"] for b in load_bets()} == {
        "evt-a": "won", "evt-b": "lost", "evt-c": "open", "evt-d": "won"}  # C n'a que 2 jours et 15 h de retard : encore ouvert
    sim.run(cmd_apply, D4, 9, 40)
    sim.run(cmd_apply, D4, 13, 10)  # le secours de 13 h 10 repasse le même jour : aucun second message de silence

    # Jour 5 : C, sans score depuis plus de 3 jours, est annulé et remboursé ; nouveau pari sur E, ouvert à la fin
    sim.set_market([E], [SCORES["A"], SCORES["B"], SCORES["D"]])
    sim.run(cmd_prepare, D5, 8, 15)
    sim.decide(D5, bets=[(E, "1")], forecasts=[(E, [0.55, 0.25, 0.20])])
    sim.run(cmd_apply, D5, 9, 40)
    sim.run(cmd_apply, D5, 13, 10)

    bets = {b["event_id"]: b for b in load_bets()}
    assert {k: v["status"] for k, v in bets.items()} == {"evt-a": "won", "evt-b": "lost", "evt-c": "void", "evt-d": "won", "evt-e": "open"}
    assert bets["evt-a"]["payout_cents"] == round(bets["evt-a"]["stake_cents"] * bets["evt-a"]["odds_sim"]) > bets["evt-a"]["stake_cents"]
    assert bets["evt-b"]["payout_cents"] == 0
    assert bets["evt-c"]["payout_cents"] == bets["evt-c"]["stake_cents"]
    assert bets["evt-d"]["payout_cents"] == round(bets["evt-d"]["stake_cents"] * bets["evt-d"]["odds_sim"]) > bets["evt-d"]["stake_cents"]
    assert bets["evt-e"]["payout_cents"] is None
    final = store.load_forecasts()
    assert len({f["event_id"] for f in final}) == len(final)  # un match, une prévision, y compris B reprévu le jour 2
    (b_final,) = [f for f in final if f["event_id"] == "evt-b"]
    assert b_final["date"] == "2026-10-18" and b_final["outcome"] == 2  # la prévision révisée est celle qui a été notée
    state = load_state(D5)
    assert state["hunger_total_cents"] == 100 and state["alive"] is True
    assert [h["date"] for h in state["history"]] == ["2026-10-17", "2026-10-18", "2026-10-20", "2026-10-21"]
    assert len(sim.sent) == 4  # un message par jour appliqué, jamais deux le même jour
