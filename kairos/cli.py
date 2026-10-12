import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from kairos import store
from kairos.config import CREDIT_FLOOR, DEFAULT_PAGE_URL, LEAGUES


@dataclass
class Context:
    api: object
    http_get: Callable
    notify: Callable[[str], None]
    today: date
    now: datetime
    page_url: str


def _why(exc: Exception) -> str:
    # Le journal est public. Le texte d'une exception n'y entre que s'il vient d'un de nos clients
    # enveloppés (OddsApiError, NotifyError) : des RuntimeError sans clé ni jeton. Toute autre
    # exception est réduite à son type, car son message pourrait citer une URL de requête.
    return str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__


def _notify(ctx: Context, text: str, notes: list[str]) -> bool:
    # Un échec Telegram n'interrompt jamais le run : il est noté dans le journal.
    try:
        ctx.notify(text)
    except Exception as exc:
        notes.append(f"Telegram indisponible : {_why(exc)}")
        return False
    return True


def cmd_prepare(ctx: Context) -> None:
    from kairos.hunger import apply_hunger, check_death
    from kairos.market import no_vig
    from kairos.model import fetch_results, fit_model, predict_events
    from kairos.odds import summarize_event, within_lookahead
    from kairos.settle import parse_scores, score_forecasts, settle_bets, sports_to_check
    from kairos.teams import load_aliases

    state, bets, forecasts = store.load_state(ctx.today), store.load_bets(), store.load_forecasts()
    notes = []
    if not state["alive"]:
        store.save_state(state)
        return
    outcomes = {}
    for key in sorted(sports_to_check(bets, forecasts, ctx.now)):
        try:
            outcomes.update(parse_scores(ctx.api.scores(key)))
        except Exception as exc:
            notes.append(f"résultats indisponibles pour {key} : {_why(exc)}")
    settled = settle_bets(state, bets, outcomes, ctx.now, ctx.today)
    scored = score_forecasts(forecasts, outcomes, ctx.now)
    hunger = apply_hunger(state, ctx.today)
    # Un second prepare le même jour paie 0 : la faim du jour s'additionne, elle n'est pas remplacée.
    prior = state.get("hunger_today")
    prior_cents = prior["cents"] if isinstance(prior, dict) and prior.get("date") == ctx.today.isoformat() else 0
    state["hunger_today"] = {"date": ctx.today.isoformat(), "cents": prior_cents + hunger}
    notes.append(f"{len(settled)} pari(s) réglé(s), {scored} prévision(s) notée(s), faim −{hunger / 100:.2f} CHF")

    open_keys = {b["sport_key"] for b in bets if b["status"] == "open"}
    events = []
    for league in LEAGUES:
        if ctx.api.remaining is not None and ctx.api.remaining < CREDIT_FLOOR and league.sport_key not in open_keys:
            notes.append(f"{league.label} sauté : crédits bas ({ctx.api.remaining})")
            continue
        try:
            raw = ctx.api.odds(league.sport_key)
        except Exception as exc:
            notes.append(f"cotes indisponibles pour {league.label} : {_why(exc)}")
            continue
        summaries = [s for s in (summarize_event(e, league.sport_key) for e in raw) if s]
        for s in within_lookahead(summaries, ctx.now):
            s["p_market"] = no_vig(s["median"])
            events.append(s)
    store.write_json(f"data/odds/{ctx.today.isoformat()}.json", {"fetched_at": ctx.now.isoformat(), "events": events})

    preds, unmatched = {}, []
    aliases = load_aliases()
    for league in LEAGUES:
        league_events = [e for e in events if e["sport_key"] == league.sport_key]
        if not league_events:
            continue
        try:
            df = fetch_results(league, ctx.today, get=ctx.http_get)
            model = fit_model(df, ctx.today)
            teams = sorted(set(df["home"]) | set(df["away"]))
            p, um = predict_events(model, teams, league_events, aliases)
            preds.update(p)
            unmatched += um
        except Exception as exc:
            notes.append(f"modèle indisponible pour {league.label} : {_why(exc)}")
            preds.update({e["event_id"]: None for e in league_events})
    store.write_json(f"data/model/{ctx.today.isoformat()}.json", {"events": preds, "unmatched": sorted(set(unmatched))})
    notes.append(f"{len(events)} match(s) dans les 48 h, {len(set(unmatched))} équipe(s) non reconnue(s)")

    check_death(state, bets, ctx.today)
    state["last_run"] = ctx.now.isoformat()
    store.save_state(state)
    store.save_bets(bets)
    store.save_forecasts(forecasts)
    store.append_journal(ctx.today, "Matin", notes)


def cmd_apply(ctx: Context) -> None:
    from kairos.hunger import check_death
    from kairos.metrics import check_diploma, equity_cents, update_sources, update_trophies
    from kairos.notify import compose_daily, compose_death, compose_diploma
    from kairos.rules import LESSONS_HEADER, accept_forecasts, place_bets, register_sources, update_lessons, validate_decisions
    from kairos.site import build_site_data, write_site

    today = ctx.today.isoformat()
    state, bets, forecasts, sources = store.load_state(ctx.today), store.load_bets(), store.load_forecasts(), store.load_sources()
    lessons = store.read_text("memory/lessons.md", LESSONS_HEADER)
    messages, notes, placed = [], [], []

    if state["alive"] and today not in state["applied_decisions"]:
        events = {e["event_id"]: e for e in store.read_json(f"data/odds/{today}.json", {"events": []})["events"]}
        model = store.read_json(f"data/model/{today}.json", {"events": {}})["events"]
        try:
            dec = store.read_json(f"decisions/{today}.json", None)
        except (OSError, ValueError):
            dec, errors = {}, ["fichier JSON illisible"]
        else:
            errors = validate_decisions(dec, ctx.today) if dec is not None else []
        if dec is not None:
            if errors:
                notes.append("décisions rejetées : " + "; ".join(errors))
                state["last_message"] = "J'ai rendu une copie illisible aujourd'hui. Aucun pari."
            else:
                new_source = register_sources(dec, sources, ctx.today)
                if new_source:
                    notes.append(f"nouvelle source en test : {new_source}")
                accepted, rejected = accept_forecasts(dec, events, model, sources, ctx.today, ctx.now, forecasts)
                forecasts.extend(accepted)
                placed, rejected_bets = place_bets(dec, {f["event_id"]: f for f in accepted}, events, state, bets, ctx.now, ctx.today)
                lessons, lesson_notes = update_lessons(lessons, dec.get("lessons"), ctx.today)
                notes += [f"{len(accepted)} prévision(s), {len(placed)} pari(s) placé(s)"]
                notes += [f"prévision rejetée {eid} : {why}" for eid, why in rejected]
                notes += [f"pari rejeté {eid} : {why}" for eid, why in rejected_bets]
                notes += lesson_notes
                state["last_message"] = dec["message"].strip()
            state["last_message_date"] = today
            state["applied_decisions"].append(today)
            messages.append("daily")
        elif state.get("silent_notified") != today:
            state["last_message"] = None
            state["last_message_date"] = today
            state["silent_notified"] = today
            notes.append("pas de fichier de décisions")
            messages.append("daily")

    update_sources(sources, forecasts)
    # Le diplôme se décide avant les trophées : le trophée « Diplômé » porte la date du jour 56, pas du lendemain.
    check_diploma(state, bets, forecasts, ctx.today)
    update_trophies(state, bets, sources, ctx.today)
    check_death(state, bets, ctx.today)
    history = [h for h in state["history"] if h["date"] != today]
    state["history"] = history + [{"date": today, "equity_cents": equity_cents(state, bets)}]
    state["last_run"] = ctx.now.isoformat()

    store.save_state(state)
    store.save_bets(bets)
    store.save_forecasts(forecasts)
    store.save_sources(sources)
    store.write_text("memory/lessons.md", lessons)
    if notes:
        store.append_journal(ctx.today, "Décisions", notes)
    write_site(build_site_data(state, bets, forecasts, sources, lessons, ctx.today, ctx.now))

    hunger = state.get("hunger_today")
    hunger_today = hunger["cents"] if isinstance(hunger, dict) and hunger.get("date") == today else 0
    telegram_notes = []
    if "daily" in messages and state["alive"]:
        _notify(ctx, compose_daily(state, bets, placed, hunger_today, ctx.page_url), telegram_notes)
    # Comme la mort : l'annonce est répétée tant qu'elle n'est pas partie. Un Kairos éteint n'a pas de diplôme à fêter.
    if state["alive"] and state.get("diploma") and not state.get("diploma_announced"):
        if _notify(ctx, compose_diploma(state, state["diploma"], ctx.page_url), telegram_notes):
            state["diploma_announced"] = True
            store.save_state(state)
    if not state["alive"] and not state.get("death_announced"):
        if _notify(ctx, compose_death(state, ctx.page_url), telegram_notes):
            state["death_announced"] = True
            store.save_state(state)
    if telegram_notes:
        store.append_journal(ctx.today, "Telegram", telegram_notes)


def cmd_closing(ctx: Context) -> None:
    from kairos.closing import capture

    bets = store.load_bets()
    if capture(ctx.api, bets, ctx.now):
        store.save_bets(bets)


def cmd_check_decisions(path: str, today: date) -> int:
    from kairos.rules import validate_decisions

    if not path:
        print("chemin manquant")
        return 2
    try:
        dec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"illisible : {exc}")
        return 1
    errors = validate_decisions(dec, today)
    for e in errors:
        print(f"erreur : {e}")
    if not errors:
        print("fichier de décisions valide")
    return 1 if errors else 0


def cmd_check_api(api) -> str:
    keys = {league.sport_key for league in LEAGUES}
    found = {s["key"] for s in api.sports() if s.get("group") == "Soccer"}
    lines = [f"{'OK ' if k in found else 'ABSENT'} {k}" for k in sorted(keys)]
    api.odds("soccer_epl")
    lines.append(f"crédits restants : {api.remaining}")
    return "\n".join(lines)


def _real_context() -> Context:
    import requests

    from kairos.api import OddsApi
    from kairos.notify import send

    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")

    def notify(text: str) -> None:
        if token and chat:
            send(token, chat, text)
        else:
            print(text)

    now = store.utcnow()
    return Context(api=OddsApi(os.environ.get("ODDS_API_KEY", "")), http_get=requests.get, notify=notify,
                   today=store.zurich_today(now), now=now, page_url=os.environ.get("PAGE_URL", DEFAULT_PAGE_URL))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="kairos")
    parser.add_argument("command", choices=["prepare", "apply", "closing", "check-decisions", "check-api"])
    parser.add_argument("path", nargs="?")
    args = parser.parse_args(argv)
    if args.command == "check-decisions":
        return cmd_check_decisions(args.path, store.zurich_today())
    ctx = _real_context()
    if args.command == "prepare":
        cmd_prepare(ctx)
    elif args.command == "apply":
        cmd_apply(ctx)
    elif args.command == "closing":
        cmd_closing(ctx)
    else:
        print(cmd_check_api(ctx.api))
    return 0


if __name__ == "__main__":
    sys.exit(main())
