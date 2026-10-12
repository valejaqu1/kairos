import shutil
from datetime import date, datetime
from pathlib import Path

from kairos.config import DIPLOMA_DAY, START_BANKROLL_CENTS, league_label, root
from kairos.metrics import TROPHIES, current_streak, equity_cents, rank, stats
from kairos.store import day_number, write_json

TEMPLATE = Path(__file__).resolve().parent.parent / "site_template" / "index.html"


def health(state: dict, equity: int) -> float:
    if not state["alive"]:
        return 0.0
    return max(0.0, min(1.0, equity / (START_BANKROLL_CENTS * 1.2)))


def mood(state: dict, bets: list, equity: int) -> str:
    if not state["alive"]:
        return "Éteint"
    if state.get("diploma") == "obtenu":
        return "Diplômé"
    if any(b["status"] == "open" for b in bets):
        return "En chasse"
    if equity < START_BANKROLL_CENTS * 0.5:
        return "Affamé"
    return "En forme" if equity >= START_BANKROLL_CENTS else "Sous pression"


def _bet_view(b: dict) -> dict:
    return {
        "league": league_label(b["sport_key"]), "kickoff": b["commence_time"], "home": b["home"], "away": b["away"],
        "selection": b["selection"], "odds_sim": b["odds_sim"], "odds_median": b["odds_median"], "stake_cents": b["stake_cents"],
        "payout_cents": b["payout_cents"], "status": b["status"], "p_kairos": b["p_kairos"], "p_market": b["p_market"],
        "closing_odds": b["closing_odds"],
    }


def build_site_data(state, bets, forecasts, sources, lessons_text, today: date, now: datetime) -> dict:
    equity = equity_cents(state, bets)
    st = stats(bets)
    recent = sorted(bets, key=lambda b: (b["date"], b["commence_time"]), reverse=True)[:8]
    return {
        "name": state["name"], "generation": state["generation"], "day": day_number(state, today),
        "diploma_day": DIPLOMA_DAY, "diploma_in": max(0, DIPLOMA_DAY - day_number(state, today)),
        "alive": state["alive"], "death_date": state["death_date"], "diploma": state.get("diploma"),
        "equity_cents": equity, "bankroll_cents": state["bankroll_cents"], "delta_cents": equity - START_BANKROLL_CENTS,
        "hunger_total_cents": state.get("hunger_total_cents", 0), "health": round(health(state, equity), 3),
        "mood": mood(state, bets, equity), "last_run": now.isoformat(),
        "message": state.get("last_message"), "message_date": state.get("last_message_date"),
        "history": state.get("history", []),
        "clv": {"beats": st["clv_beats"], "total": st["clv_total"]}, "streak": current_streak(bets),
        "rank": rank(forecasts, bets), "stats": {k: st[k] for k in ("bets", "won", "roi", "clv_avg")},
        "bets": [_bet_view(b) for b in recent],
        "lessons": [l[2:].strip() for l in lessons_text.splitlines() if l.startswith("- ")],
        "sources": [{"id": sid, **{k: m.get(k) for k in ("description", "status", "uses", "score")}} for sid, m in sorted(sources.items())],
        "trophies": [{"id": k, "label": v, "date": state["trophies"].get(k)} for k, v in TROPHIES.items()],
        "updated_at": now.isoformat(),
    }


def write_site(data: dict) -> None:
    write_json("site/data.json", data)
    target = root() / "site" / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TEMPLATE, target)
