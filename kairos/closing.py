from datetime import datetime, timedelta
from statistics import median

from kairos.config import CLOSING_WINDOW_MIN, CREDIT_FLOOR
from kairos.odds import event_prices
from kairos.store import parse_ts


def due_bets(bets: list, now: datetime) -> list[dict]:
    end = now + timedelta(minutes=CLOSING_WINDOW_MIN)
    return [b for b in bets if b["status"] == "open" and b.get("closing_odds") is None and now <= parse_ts(b["commence_time"]) <= end]


def capture(api, bets: list, now: datetime) -> int:
    captured = 0
    for b in due_bets(bets, now):
        if api.remaining is not None and api.remaining < CREDIT_FLOOR:
            break
        # Un pari dont la récupération ou l'analyse échoue est sauté (repris au run suivant) :
        # cmd_closing n'enregistre qu'au retour de capture, une exception perdrait toutes les cotes du run.
        try:
            event = api.event_odds(b["sport_key"], b["event_id"])
            if not event:
                continue
            prices = event_prices(event)[b["selection"]]
        except Exception:
            continue
        if prices:
            b["closing_odds"] = round(median(prices), 3)
            captured += 1
    return captured
