from datetime import datetime, timedelta
from statistics import median

from kairos.config import LOOKAHEAD_HOURS, MIN_SIM_ODDS, ODDS_HAIRCUT
from kairos.store import parse_ts

SELECTIONS = ("1", "X", "2")
SEL_INDEX = {"1": 0, "X": 1, "2": 2}


def event_prices(event: dict) -> dict[str, list[float]]:
    prices: dict[str, list[float]] = {"1": [], "X": [], "2": []}
    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") != "h2h":
                continue
            for outcome in market.get("outcomes", []):
                price = float(outcome["price"])
                if outcome["name"] == event["home_team"]:
                    prices["1"].append(price)
                elif outcome["name"] == event["away_team"]:
                    prices["2"].append(price)
                elif outcome["name"] == "Draw":
                    prices["X"].append(price)
    return prices


def simulated(odds: float) -> float:
    return max(MIN_SIM_ODDS, round(odds * ODDS_HAIRCUT, 2))


def summarize_event(event: dict, sport_key: str) -> dict | None:
    prices = event_prices(event)
    if any(not prices[s] for s in SELECTIONS):
        return None
    med = {s: round(median(prices[s]), 3) for s in SELECTIONS}
    return {
        "event_id": event["id"],
        "sport_key": sport_key,
        "home": event["home_team"],
        "away": event["away_team"],
        "commence_time": event["commence_time"],
        "median": med,
        "sim": {s: simulated(med[s]) for s in SELECTIONS},
        "n_books": min(len(prices[s]) for s in SELECTIONS),
    }


def within_lookahead(summaries: list[dict], now: datetime) -> list[dict]:
    end = now + timedelta(hours=LOOKAHEAD_HOURS)
    return [s for s in summaries if now < parse_ts(s["commence_time"]) <= end]
