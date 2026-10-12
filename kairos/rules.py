from datetime import date, datetime, timedelta

from kairos.config import (KELLY_FRACTION, KICKOFF_MARGIN_MIN, MAX_BETS_PER_DAY, MAX_EXPOSURE_SHARE, MAX_FORECASTS_PER_DAY,
                           MAX_LESSONS, MAX_LESSONS_ADDED, MAX_MESSAGE_CHARS, MAX_STAKE_SHARE, MIN_BET_ODDS, MIN_STAKE_CENTS,
                           STAKE_STEP_CENTS, VALUE_THRESHOLD)
from kairos.odds import SEL_INDEX
from kairos.store import parse_ts

LESSONS_HEADER = "# Leçons de Kairos\n\n"


def validate_decisions(dec: dict, today: date) -> list[str]:
    errors = []
    if not isinstance(dec, dict):
        return ["le fichier n'est pas un objet JSON"]
    if dec.get("date") != today.isoformat():
        errors.append("date incorrecte")
    if not isinstance(dec.get("forecasts"), list):
        errors.append("forecasts doit être une liste")
    if not isinstance(dec.get("bets"), list):
        errors.append("bets doit être une liste")
    message = dec.get("message")
    if not isinstance(message, str) or not message.strip():
        errors.append("message manquant")
    elif len(message) > MAX_MESSAGE_CHARS:
        errors.append("message trop long")
    return errors


def register_sources(dec: dict, sources: dict, today: date) -> str | None:
    new = dec.get("new_source")
    if not isinstance(new, dict) or not isinstance(new.get("id"), str) or not new["id"].strip():
        return None
    sid = new["id"].strip()
    if sid in sources:
        return None
    sources[sid] = {"description": str(new.get("description", ""))[:200], "url": str(new.get("url", ""))[:300],
                    "status": "test", "uses": 0, "score": None, "first_seen": today.isoformat()}
    return sid


def accept_forecasts(dec: dict, events: dict, model: dict, sources: dict, today: date):
    accepted, rejected = [], []
    for f in dec["forecasts"][:MAX_FORECASTS_PER_DAY]:
        eid = str(f.get("event_id"))
        ev = events.get(eid)
        if ev is None:
            rejected.append((eid, "match inconnu"))
            continue
        p = f.get("p")
        if not (isinstance(p, list) and len(p) == 3 and all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in p)):
            rejected.append((eid, "probabilités invalides"))
            continue
        total = sum(p)
        if not 0.98 <= total <= 1.02:
            rejected.append((eid, "les probabilités ne somment pas à 1"))
            continue
        srcs = [s for s in f.get("sources", []) if isinstance(s, str) and s in sources and sources[s].get("status") != "dropped"]
        accepted.append({
            "date": today.isoformat(), "event_id": eid, "sport_key": ev["sport_key"], "home": ev["home"], "away": ev["away"],
            "commence_time": ev["commence_time"], "p_kairos": [round(x / total, 4) for x in p], "p_market": ev["p_market"],
            "p_model": model.get(eid), "sources": srcs, "note": str(f.get("note", ""))[:300],
            "outcome": None, "rps_kairos": None, "rps_market": None, "rps_model": None, "void": False,
        })
    return accepted, rejected


def stake_cents(p: float, odds: float, equity_cents: int) -> int:
    edge = p * odds - 1
    if odds <= 1 or edge < VALUE_THRESHOLD:
        return 0
    share = min(edge / (odds - 1) * KELLY_FRACTION, MAX_STAKE_SHARE)
    stake = int(share * equity_cents // STAKE_STEP_CENTS) * STAKE_STEP_CENTS
    return stake if stake >= MIN_STAKE_CENTS else 0


def place_bets(dec: dict, forecasts_by_event: dict, events: dict, state: dict, bets: list, now: datetime, today: date):
    placed, rejected = [], []
    open_stakes = sum(b["stake_cents"] for b in bets if b["status"] == "open")
    placed_today = sum(1 for b in bets if b["date"] == today.isoformat())
    for prop in dec["bets"]:
        eid, sel = str(prop.get("event_id")), prop.get("selection")
        if placed_today + len(placed) >= MAX_BETS_PER_DAY:
            rejected.append((eid, f"déjà {MAX_BETS_PER_DAY} paris aujourd'hui"))
            continue
        if sel not in SEL_INDEX:
            rejected.append((eid, "issue invalide"))
            continue
        forecast, ev = forecasts_by_event.get(eid), events.get(eid)
        if forecast is None or ev is None:
            rejected.append((eid, "pas de prévision acceptée pour ce match"))
            continue
        if any(b["event_id"] == eid and b["status"] == "open" for b in bets + placed):
            rejected.append((eid, "déjà un pari sur ce match"))
            continue
        if parse_ts(ev["commence_time"]) <= now + timedelta(minutes=KICKOFF_MARGIN_MIN):
            rejected.append((eid, "match trop proche ou déjà commencé"))
            continue
        odds, p = ev["sim"][sel], forecast["p_kairos"][SEL_INDEX[sel]]
        if odds < MIN_BET_ODDS:
            rejected.append((eid, "cote inférieure à 1,10"))
            continue
        equity = state["bankroll_cents"] + open_stakes
        stake = stake_cents(p, odds, equity)
        if stake == 0:
            edge = p * odds - 1
            rejected.append((eid, f"valeur insuffisante ({edge:+.1%})" if edge < VALUE_THRESHOLD else "mise inférieure à 2 CHF"))
            continue
        if open_stakes + stake > MAX_EXPOSURE_SHARE * equity:
            rejected.append((eid, "exposition maximale atteinte"))
            continue
        if stake > state["bankroll_cents"]:
            rejected.append((eid, "cagnotte insuffisante"))
            continue
        state["bankroll_cents"] -= stake
        open_stakes += stake
        placed.append({
            "id": f"{today.isoformat()}-{eid}-{sel}", "date": today.isoformat(), "event_id": eid, "sport_key": ev["sport_key"],
            "home": ev["home"], "away": ev["away"], "commence_time": ev["commence_time"], "selection": sel,
            "odds_median": ev["median"][sel], "odds_sim": odds, "stake_cents": stake, "p_kairos": p,
            "p_market": ev["p_market"][SEL_INDEX[sel]], "status": "open", "payout_cents": None, "closing_odds": None,
            "settled_date": None, "reasoning": str(prop.get("reasoning", ""))[:400],
        })
    bets.extend(placed)
    return placed, rejected


def update_lessons(text: str, changes: dict | None, today: date) -> tuple[str, list[str]]:
    if not changes:
        return text, []
    if today.weekday() != 6:
        return text, ["leçons ignorées : on ne les modifie que le dimanche"]
    lines = [l[2:].strip() for l in text.splitlines() if l.startswith("- ")]
    notes = []
    for item in changes.get("remove", []) or []:
        if item in lines:
            lines.remove(item)
    adds = [str(a).strip()[:200] for a in (changes.get("add", []) or []) if str(a).strip()]
    if len(adds) > MAX_LESSONS_ADDED:
        notes.append(f"{len(adds) - MAX_LESSONS_ADDED} ajout ignoré ({MAX_LESSONS_ADDED} au maximum)")
        adds = adds[:MAX_LESSONS_ADDED]
    for a in adds:
        if len(lines) >= MAX_LESSONS:
            notes.append(f"ajout ignoré : déjà {MAX_LESSONS} leçons")
            break
        lines.append(a)
    return LESSONS_HEADER + "".join(f"- {l}\n" for l in lines), notes
