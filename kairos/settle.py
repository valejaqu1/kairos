from datetime import date, datetime, timedelta

from kairos.config import VOID_AFTER_DAYS
from kairos.odds import SEL_INDEX
from kairos.scoring import outcome_from_goals, rps
from kairos.store import parse_ts


def parse_scores(payload: list) -> dict[str, int]:
    outcomes: dict[str, int] = {}
    for game in payload:
        if not game.get("completed") or not game.get("scores"):
            continue
        goals = {s["name"]: int(s["score"]) for s in game["scores"]}
        if game["home_team"] in goals and game["away_team"] in goals:
            outcomes[game["id"]] = outcome_from_goals(goals[game["home_team"]], goals[game["away_team"]])
    return outcomes


def _stale(item: dict, now: datetime) -> bool:
    return parse_ts(item["commence_time"]) + timedelta(days=VOID_AFTER_DAYS) < now


def settle_bets(state: dict, bets: list, outcomes: dict[str, int], now: datetime, today: date) -> list[dict]:
    settled = []
    for b in bets:
        if b["status"] != "open":
            continue
        if b["event_id"] in outcomes:
            won = outcomes[b["event_id"]] == SEL_INDEX[b["selection"]]
            b["status"] = "won" if won else "lost"
            b["payout_cents"] = round(b["stake_cents"] * b["odds_sim"]) if won else 0
        elif _stale(b, now):
            b["status"] = "void"
            b["payout_cents"] = b["stake_cents"]
        else:
            continue
        b["settled_date"] = today.isoformat()
        state["bankroll_cents"] += b["payout_cents"]
        settled.append(b)
    return settled


def score_forecasts(forecasts: list, outcomes: dict[str, int], now: datetime) -> int:
    scored = 0
    for f in forecasts:
        if f.get("outcome") is not None or f.get("void"):
            continue
        if f["event_id"] in outcomes:
            o = outcomes[f["event_id"]]
            f["outcome"] = o
            f["rps_kairos"] = rps(f["p_kairos"], o)
            f["rps_market"] = rps(f["p_market"], o)
            f["rps_model"] = rps(f["p_model"], o) if f.get("p_model") else None
            scored += 1
        elif _stale(f, now):
            f["void"] = True
    return scored


def sports_to_check(bets: list, forecasts: list, now: datetime) -> set[str]:
    pending = [b for b in bets if b["status"] == "open"]
    pending += [f for f in forecasts if f.get("outcome") is None and not f.get("void")]
    return {item["sport_key"] for item in pending if parse_ts(item["commence_time"]) < now}
