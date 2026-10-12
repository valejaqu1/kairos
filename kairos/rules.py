from datetime import date, datetime, timedelta

from kairos.config import (KELLY_FRACTION, KICKOFF_MARGIN_MIN, MAX_BETS_PER_DAY, MAX_EXPOSURE_SHARE, MAX_FORECASTS_PER_DAY,
                           MAX_LESSONS, MAX_LESSONS_ADDED, MAX_MESSAGE_CHARS, MAX_STAKE_SHARE, MIN_BET_ODDS, MIN_STAKE_CENTS,
                           MAX_SOURCES_PER_FORECAST, STAKE_STEP_CENTS, VALUE_THRESHOLD)
from kairos.odds import SEL_INDEX
from kairos.store import parse_ts

LESSONS_HEADER = "# Leçons de Kairos\n\n"


def _is_text_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _forecast_errors(i: int, f: dict) -> list[str]:
    errors = []
    if not isinstance(f.get("event_id"), str):
        errors.append(f"forecasts[{i}].event_id doit être un texte")
    if not isinstance(f.get("p"), list):
        errors.append(f"forecasts[{i}].p doit être une liste")
    if "sources" in f and not _is_text_list(f["sources"]):
        errors.append(f"forecasts[{i}].sources doit être une liste de textes")
    if "note" in f and not isinstance(f["note"], str):
        errors.append(f"forecasts[{i}].note doit être un texte")
    return errors


def _bet_errors(i: int, b: dict) -> list[str]:
    errors = []
    if not isinstance(b.get("event_id"), str):
        errors.append(f"bets[{i}].event_id doit être un texte")
    if not isinstance(b.get("selection"), str):
        errors.append(f"bets[{i}].selection doit être un texte")
    if "reasoning" in b and not isinstance(b["reasoning"], str):
        errors.append(f"bets[{i}].reasoning doit être un texte")
    return errors


def validate_decisions(dec: dict, today: date) -> list[str]:
    errors = []
    if not isinstance(dec, dict):
        return ["le fichier n'est pas un objet JSON"]
    if dec.get("date") != today.isoformat():
        errors.append("date incorrecte")
    if not isinstance(dec.get("forecasts"), list):
        errors.append("forecasts doit être une liste")
    elif not all(isinstance(f, dict) for f in dec["forecasts"]):
        errors.append("forecasts contient un élément invalide")
    else:
        for i, f in enumerate(dec["forecasts"]):
            errors += _forecast_errors(i, f)
    if not isinstance(dec.get("bets"), list):
        errors.append("bets doit être une liste")
    elif not all(isinstance(b, dict) for b in dec["bets"]):
        errors.append("bets contient un élément invalide")
    else:
        for i, b in enumerate(dec["bets"]):
            errors += _bet_errors(i, b)
    new_source = dec.get("new_source")
    if new_source is not None and not isinstance(new_source, dict):
        errors.append("new_source doit être un objet ou null")
    lessons = dec.get("lessons")
    if lessons is not None and not isinstance(lessons, dict):
        errors.append("lessons doit être un objet ou null")
    elif isinstance(lessons, dict):
        if "add" in lessons and not _is_text_list(lessons["add"]):
            errors.append("lessons.add doit être une liste de textes")
        if "remove" in lessons and not _is_text_list(lessons["remove"]):
            errors.append("lessons.remove doit être une liste de textes")
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
    seen = set()
    for f in dec["forecasts"][:MAX_FORECASTS_PER_DAY]:
        eid = str(f.get("event_id"))
        ev = events.get(eid)
        if ev is None:
            rejected.append((eid, "match inconnu"))
            continue
        p = f.get("p")
        if not (isinstance(p, list) and len(p) == 3 and all(isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 1 for x in p)):
            rejected.append((eid, "probabilités invalides"))
            continue
        total = sum(p)
        if not 0.98 <= total <= 1.02:
            rejected.append((eid, "les probabilités ne somment pas à 1"))
            continue
        if eid in seen:
            rejected.append((eid, "doublon"))
            continue
        seen.add(eid)
        usable = (s for s in f.get("sources", []) if isinstance(s, str) and s in sources and sources[s].get("status") != "dropped")
        srcs = list(dict.fromkeys(usable))[:MAX_SOURCES_PER_FORECAST]
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


def _one_line(value) -> str:
    return " ".join(str(value).split())


def update_lessons(text: str, changes: dict | None, today: date) -> tuple[str, list[str]]:
    if not changes:
        return text, []
    if today.weekday() != 6:
        return text, ["leçons ignorées : on ne les modifie que le dimanche"]
    lines = [l[2:].strip() for l in text.splitlines() if l.startswith("- ")]
    notes = []
    for item in changes.get("remove", []) or []:
        item = _one_line(item)
        if item in lines:
            lines.remove(item)
    adds = [_one_line(a)[:200] for a in (changes.get("add", []) or []) if _one_line(a)]
    if len(adds) > MAX_LESSONS_ADDED:
        notes.append(f"{len(adds) - MAX_LESSONS_ADDED} ajout ignoré ({MAX_LESSONS_ADDED} au maximum)")
        adds = adds[:MAX_LESSONS_ADDED]
    for a in adds:
        if len(lines) >= MAX_LESSONS:
            notes.append(f"ajout ignoré : déjà {MAX_LESSONS} leçons")
            break
        lines.append(a)
    return LESSONS_HEADER + "".join(f"- {l}\n" for l in lines), notes
