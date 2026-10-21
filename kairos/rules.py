import re
from datetime import date, datetime, timedelta

from kairos.config import (KELLY_FRACTION, KICKOFF_MARGIN_MIN, MAX_BETS_PER_DAY, MAX_EXPOSURE_SHARE, MAX_FORECASTS_PER_DAY,
                           MAX_LESSONS, MAX_LESSONS_ADDED, MAX_MESSAGE_CHARS, MAX_STAKE_SHARE, MIN_BET_ODDS, MIN_STAKE_CENTS,
                           MAX_SOURCES_PER_FORECAST, SOURCE_DESCRIPTION_MAX, SOURCE_URL_MAX, STAKE_STEP_CENTS, VALUE_THRESHOLD)
from kairos.odds import SEL_INDEX
from kairos.store import parse_ts

LESSONS_HEADER = "# Leçons de Kairos\n\n"
BET_TYPES = ("valeur", "apprentissage")
SOURCE_ID = re.compile(r"[a-z0-9-]{1,40}")  # fullmatch : un « $ » accepterait un retour à la ligne final


def _one_line(value) -> str:
    return " ".join(str(value).split())


def _is_text_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _is_source_id(value) -> bool:
    return isinstance(value, str) and SOURCE_ID.fullmatch(value) is not None


def _forecast_errors(i: int, f: dict) -> list[str]:
    errors = []
    if not isinstance(f.get("event_id"), str):
        errors.append(f"forecasts[{i}].event_id doit être un texte")
    if not isinstance(f.get("p"), list):
        errors.append(f"forecasts[{i}].p doit être une liste")
    if "sources" in f and not _is_text_list(f["sources"]):
        errors.append(f"forecasts[{i}].sources doit être une liste de textes")
    elif "sources" in f and not all(_is_source_id(s) for s in f["sources"]):
        errors.append(f"forecasts[{i}].sources contient un identifiant invalide")
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
    if "type" in b and b["type"] not in BET_TYPES:
        errors.append(f"bets[{i}].type doit valoir « valeur » ou « apprentissage »")
    return errors


def _new_source_errors(source: dict) -> list[str]:
    errors = []
    if not _is_source_id(source.get("id")):
        errors.append("new_source.id doit être un identifiant (a-z, 0-9, tirets, 40 caractères au maximum)")
    if "description" in source:
        if not isinstance(source["description"], str):
            errors.append("new_source.description doit être un texte")
        elif len(_one_line(source["description"])) > SOURCE_DESCRIPTION_MAX:
            errors.append(f"new_source.description trop longue ({SOURCE_DESCRIPTION_MAX} caractères au maximum)")
    if "url" in source:
        url = source["url"]
        if not isinstance(url, str):
            errors.append("new_source.url doit être un texte")
        elif not url.startswith(("https://", "http://")):
            errors.append("new_source.url doit commencer par https:// ou http://")
        elif len(url) > SOURCE_URL_MAX:
            errors.append(f"new_source.url trop longue ({SOURCE_URL_MAX} caractères au maximum)")
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
    elif isinstance(new_source, dict):
        errors += _new_source_errors(new_source)
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
    sources[sid] = {"description": _one_line(new.get("description", ""))[:SOURCE_DESCRIPTION_MAX],
                    "url": str(new.get("url", ""))[:SOURCE_URL_MAX],
                    "status": "test", "uses": 0, "score": None, "first_seen": today.isoformat()}
    return sid


def accept_forecasts(dec: dict, events: dict, model: dict, sources: dict, today: date, now: datetime):
    accepted, rejected = [], []
    seen = set()
    cutoff = now + timedelta(minutes=KICKOFF_MARGIN_MIN)  # la même marge que pour les paris
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
        if parse_ts(ev["commence_time"]) <= cutoff:
            rejected.append((eid, "match commencé"))
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


def merge_forecasts(forecasts: list, accepted: list) -> list[str]:
    """Ajoute les prévisions acceptées. Une nouvelle prévision remplace l'ancienne, pas encore notée, du même match :
    un match ne compte qu'une fois dans le score de compétence, le rang et les sources. Une prévision notée (match joué)
    ou annulée n'est jamais touchée. Renvoie les identifiants des matchs dont la prévision a été remplacée."""
    revised = {f["event_id"] for f in accepted}

    def is_replaced(f: dict) -> bool:
        return f["event_id"] in revised and f.get("outcome") is None and not f.get("void")

    replaced = [f["event_id"] for f in forecasts if is_replaced(f)]
    forecasts[:] = [f for f in forecasts if not is_replaced(f)]
    forecasts.extend(accepted)
    return replaced


def stake_cents(p: float, odds: float, equity_cents: int) -> int:
    edge = p * odds - 1
    if odds <= 1 or edge < VALUE_THRESHOLD:
        return 0
    share = min(edge / (odds - 1) * KELLY_FRACTION, MAX_STAKE_SHARE)
    stake = int(share * equity_cents // STAKE_STEP_CENTS) * STAKE_STEP_CENTS
    return stake if stake >= MIN_STAKE_CENTS else 0


def place_bets(dec: dict, forecasts_by_event: dict, events: dict, state: dict, bets: list, now: datetime, today: date):
    placed, rejected, learning = [], [], []
    open_stakes = sum(b["stake_cents"] for b in bets if b["status"] == "open")
    placed_today = sum(1 for b in bets if b["date"] == today.isoformat())

    def record(prop: dict, eid: str, sel: str, ev: dict, odds: float, p: float, stake: int, kind: str) -> None:
        nonlocal open_stakes
        state["bankroll_cents"] -= stake
        open_stakes += stake
        placed.append({
            "id": f"{today.isoformat()}-{eid}-{sel}", "date": today.isoformat(), "event_id": eid, "sport_key": ev["sport_key"],
            "home": ev["home"], "away": ev["away"], "commence_time": ev["commence_time"], "selection": sel,
            "odds_median": ev["median"][sel], "odds_sim": odds, "stake_cents": stake, "p_kairos": p,
            "p_market": ev["p_market"][SEL_INDEX[sel]], "status": "open", "payout_cents": None, "closing_odds": None,
            "settled_date": None, "reasoning": str(prop.get("reasoning", ""))[:400], "kind": kind,
        })

    def limit_error(stake: int) -> str | None:
        if open_stakes + stake > MAX_EXPOSURE_SHARE * (state["bankroll_cents"] + open_stakes):
            return "exposition maximale atteinte"
        if stake > state["bankroll_cents"]:
            return "cagnotte insuffisante"
        return None

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
        stake = stake_cents(p, odds, state["bankroll_cents"] + open_stakes)
        if stake == 0:
            if prop.get("type") == "apprentissage":
                learning.append((prop, eid, sel, ev, odds, p))  # décidé après les paris de valeur, quel que soit l'ordre
                continue
            edge = p * odds - 1
            rejected.append((eid, f"valeur insuffisante ({edge:+.1%})" if edge < VALUE_THRESHOLD else "mise inférieure à 2 CHF"))
            continue
        error = limit_error(stake)
        if error:
            rejected.append((eid, error))
            continue
        record(prop, eid, sel, ev, odds, p, stake, "valeur")

    # Pari d'apprentissage : seulement les jours sans pari de valeur, un seul, à la mise minimale, et seulement si
    # Kairos se voit plus haut que le marché. Il garde Kairos actif et rend sa CLV mesurable.
    value_today = bool(placed) or any(b["date"] == today.isoformat() and b.get("kind") != "apprentissage" for b in bets)
    learning_today = any(b["date"] == today.isoformat() and b.get("kind") == "apprentissage" for b in bets)
    for prop, eid, sel, ev, odds, p in learning:
        if value_today:
            rejected.append((eid, "pas de pari d'apprentissage : un pari de valeur est placé aujourd'hui"))
        elif learning_today:
            rejected.append((eid, "un seul pari d'apprentissage par jour"))
        elif p <= ev["p_market"][SEL_INDEX[sel]]:
            rejected.append((eid, "pari d'apprentissage refusé : ta probabilité ne dépasse pas celle du marché"))
        elif error := limit_error(MIN_STAKE_CENTS):
            rejected.append((eid, error))
        else:
            record(prop, eid, sel, ev, odds, p, MIN_STAKE_CENTS, "apprentissage")
            learning_today = True
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
