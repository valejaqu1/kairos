from datetime import datetime, timedelta, timezone
from pathlib import Path

from kairos.api import FakeOddsApi, OddsApiError
from kairos.closing import capture, due_bets

FIX = Path(__file__).parent / "fixtures"


def bet(eid="evt-brighton-villa", kickoff="2026-10-18T14:00:00Z", status="open", closing=None):
    return {"event_id": eid, "sport_key": "soccer_epl", "selection": "1", "commence_time": kickoff, "status": status,
            "closing_odds": closing}


def test_due_bets_window():
    now = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
    bets = [bet(), bet(kickoff="2026-10-18T16:00:00Z"), bet(closing=2.1), bet(status="won")]
    assert due_bets(bets, now) == [bets[0]]


def test_capture_stores_median_closing_odds():
    now = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
    bets = [bet()]
    assert capture(FakeOddsApi(FIX), bets, now) == 1
    assert bets[0]["closing_odds"] == 2.025


def test_capture_stops_under_credit_floor():
    now = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
    bets = [bet()]
    assert capture(FakeOddsApi(FIX, remaining=40), bets, now) == 0
    assert bets[0]["closing_odds"] is None


class ScriptedApi:
    """Fake de test : renvoie la fixture brighton-villa, sauf pour les événements de `scripted`
    (valeur = payload renvoyé, ou exception levée)."""
    remaining = 500

    def __init__(self, scripted):
        self.scripted = scripted

    def event_odds(self, sport_key, event_id):
        if event_id in self.scripted:
            result = self.scripted[event_id]
            if isinstance(result, Exception):
                raise result
            return result
        return FakeOddsApi(FIX).event_odds(sport_key, event_id)


def home_prices_event(event_id, prices):
    return {"id": event_id, "home_team": "Brighton and Hove Albion", "away_team": "Aston Villa",
            "bookmakers": [{"markets": [{"key": "h2h", "outcomes": [{"name": "Brighton and Hove Albion", "price": p}]}]}
                           for p in prices]}


def test_capture_skips_bet_whose_fetch_raises():
    now = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
    bets = [bet(eid="evt-broken"), bet()]
    api = ScriptedApi({"evt-broken": OddsApiError("HTTP 500 après 3 tentatives")})
    assert capture(api, bets, now) == 1
    assert bets[0]["closing_odds"] is None
    assert bets[1]["closing_odds"] == 2.025


def test_capture_skips_bet_whose_payload_is_malformed():
    now = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
    # outcome sans clé "price" : event_prices lève KeyError
    malformed = {"id": "evt-malformed", "home_team": "Brighton and Hove Albion", "away_team": "Aston Villa",
                 "bookmakers": [{"markets": [{"key": "h2h", "outcomes": [{"name": "Brighton and Hove Albion"}]}]}]}
    bets = [bet(eid="evt-malformed"), bet()]
    assert capture(ScriptedApi({"evt-malformed": malformed}), bets, now) == 1
    assert bets[0]["closing_odds"] is None
    assert bets[1]["closing_odds"] == 2.025


def test_capture_skips_empty_and_priceless_events():
    now = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
    # evt-missing : pas de fixture, donc {} ; evt-priceless : aucune cote pour la sélection "1"
    bets = [bet(eid="evt-missing"), bet(eid="evt-priceless"), bet()]
    api = ScriptedApi({"evt-priceless": home_prices_event("evt-priceless", [])})
    assert capture(api, bets, now) == 1
    assert [b["closing_odds"] for b in bets] == [None, None, 2.025]


def test_due_bets_window_edges():
    now = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)

    def kickoff(minutes):
        return (now + timedelta(minutes=minutes)).isoformat()

    bets = [bet(kickoff=kickoff(-1)), bet(kickoff=kickoff(0)), bet(kickoff=kickoff(45)), bet(kickoff=kickoff(46))]
    assert due_bets(bets, now) == [bets[1], bets[2]]


def test_capture_credit_floor_allows_exactly_fifty():
    now = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
    assert capture(FakeOddsApi(FIX, remaining=50), [bet()], now) == 1
    assert capture(FakeOddsApi(FIX, remaining=49), [bet()], now) == 0


def test_capture_runs_before_remaining_is_known():
    now = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
    api = FakeOddsApi(FIX)
    # OddsApi.remaining reste None tant qu'aucune réponse n'a été reçue dans le run
    api.remaining = None
    bets = [bet()]
    assert capture(api, bets, now) == 1
    assert bets[0]["closing_odds"] == 2.025


def test_capture_medians_and_rounds_closing_prices():
    now = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
    # médiane de 3 cotes (2.0), pas moyenne (2.1)
    # médiane de 1.11 et 1.17 = 1.1400000000000001 en flottant : l'arrondi à 3 décimales est observable
    bets = [bet(eid="evt-three-books"), bet(eid="evt-float")]
    api = ScriptedApi({"evt-three-books": home_prices_event("evt-three-books", [1.90, 2.00, 2.40]),
                       "evt-float": home_prices_event("evt-float", [1.11, 1.17])})
    assert capture(api, bets, now) == 2
    assert [b["closing_odds"] for b in bets] == [2.0, 1.14]


def test_capture_uses_each_bets_selection():
    now = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
    draw, away = bet(), bet()
    draw["selection"] = "X"
    away["selection"] = "2"
    bets = [draw, away]
    assert capture(FakeOddsApi(FIX), bets, now) == 2
    assert [b["closing_odds"] for b in bets] == [3.55, 3.65]
