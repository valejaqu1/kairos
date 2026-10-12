import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from kairos import store
from kairos.api import FakeOddsApi, OddsApiError
from kairos.cli import Context, cmd_apply, cmd_check_api, cmd_check_decisions, cmd_closing, cmd_prepare, main
from kairos.config import DEFAULT_PAGE_URL
from kairos.store import load_bets, load_state, new_state

FIX = Path(__file__).parent / "fixtures"


class Resp:
    def __init__(self, status, content=b""):
        self.status_code = status
        self.content = content


def http_get(url, timeout):
    if "E0.csv" in url and "2627" in url:
        # Scores tirés d'une loi de Poisson à graine fixe (comme tests/test_model.py) : des scores
        # quasi constants font diverger le modèle de Dixon-Coles vers une borne et predict() échoue.
        rng = np.random.default_rng(0)
        strength = {"Brighton": 1.5, "Aston Villa": 1.0, "Arsenal": 1.0, "Chelsea": 0.7}
        rows = ["Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR"]
        teams = list(strength)
        day = 1
        for _ in range(4):
            for h in teams:
                for a in teams:
                    if h != a:
                        hg = int(rng.poisson(1.3 * strength[h] / strength[a]))
                        ag = int(rng.poisson(1.0 * strength[a] / strength[h]))
                        ftr = "H" if hg > ag else "A" if hg < ag else "D"
                        rows.append(f"E0,{day:02d}/09/2026,15:00,{h},{a},{hg},{ag},{ftr}")
                        day = day % 28 + 1
        return Resp(200, "\n".join(rows).encode())
    return Resp(404)


def test_full_day_cycle(tmp_root):
    sent = []
    day1 = Context(api=FakeOddsApi(FIX), http_get=http_get, notify=sent.append,
                   today=date(2026, 10, 17), now=datetime(2026, 10, 17, 8, 15, tzinfo=timezone.utc), page_url="https://x/")
    cmd_prepare(day1)
    snap = json.loads((tmp_root / "data" / "odds" / "2026-10-17.json").read_text())
    assert [e["event_id"] for e in snap["events"]] == ["evt-brighton-villa"]
    model = json.loads((tmp_root / "data" / "model" / "2026-10-17.json").read_text())
    assert model["events"]["evt-brighton-villa"] is not None

    decisions = {"date": "2026-10-17", "message": "Je tente Brighton.", "new_source": {"id": "compos", "description": "Compos probables", "url": "https://x"},
                 "forecasts": [{"event_id": "evt-brighton-villa", "p": [0.55, 0.25, 0.20], "sources": ["compos"], "note": "buteur de retour"}],
                 "bets": [{"event_id": "evt-brighton-villa", "selection": "1", "reasoning": "valeur"}], "lessons": None}
    (tmp_root / "decisions").mkdir()
    (tmp_root / "decisions" / "2026-10-17.json").write_text(json.dumps(decisions))
    assert cmd_check_decisions(str(tmp_root / "decisions" / "2026-10-17.json"), date(2026, 10, 17)) == 0

    day1.now = datetime(2026, 10, 17, 9, 40, tzinfo=timezone.utc)
    cmd_apply(day1)
    bets = load_bets()
    assert len(bets) == 1 and bets[0]["stake_cents"] == 420
    assert sent and sent[0].startswith("Je tente Brighton.")
    assert (tmp_root / "site" / "data.json").exists()
    cmd_apply(day1)
    assert len(load_bets()) == 1 and len(sent) == 1

    day1.now = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
    cmd_closing(day1)
    assert load_bets()[0]["closing_odds"] == 2.025

    day2 = Context(api=FakeOddsApi(FIX), http_get=http_get, notify=sent.append,
                   today=date(2026, 10, 19), now=datetime(2026, 10, 19, 8, 15, tzinfo=timezone.utc), page_url="https://x/")
    cmd_prepare(day2)
    state = load_state(date(2026, 10, 19))
    assert load_bets()[0]["status"] == "won"
    assert state["bankroll_cents"] == 10_000 - 420 + round(420 * 2.18) - 50
    cmd_apply(day2)
    assert "Kairos n'a pas donné signe de vie" in sent[-1]


# --- Tests ajoutés (hors brief) : arbitrages du contrôleur et branches que le test de bout en bout ne couvre pas ---

TODAY = date(2026, 10, 17)
MORNING = datetime(2026, 10, 17, 8, 15, tzinfo=timezone.utc)
MIDMORNING = datetime(2026, 10, 17, 9, 40, tzinfo=timezone.utc)
PAGE = "https://x/"
SECRET = "SECRET-KEY-123"


def make_ctx(notify, api=None, today=TODAY, now=MORNING):
    return Context(api=api if api is not None else FakeOddsApi(FIX), http_get=http_get, notify=notify,
                   today=today, now=now, page_url=PAGE)


def seed_state(**changes):
    # Kairos né le 15 : au 17, deux jours de faim (50 centimes) restent à payer.
    state = new_state(date(2026, 10, 15))
    state.update(changes)
    store.save_state(state)


def valid_decisions(**changes):
    dec = {"date": "2026-10-17", "message": "Je tente Brighton.", "new_source": None,
           "forecasts": [{"event_id": "evt-brighton-villa", "p": [0.55, 0.25, 0.20], "sources": [], "note": "valeur"}],
           "bets": [{"event_id": "evt-brighton-villa", "selection": "1", "reasoning": "valeur"}], "lessons": None}
    dec.update(changes)
    return dec


def write_decisions(root, **changes):
    (root / "decisions").mkdir(exist_ok=True)
    (root / "decisions" / "2026-10-17.json").write_text(json.dumps(valid_decisions(**changes)), encoding="utf-8")


def open_bet(commence, event_id="evt-old", selection="1"):
    return {"id": f"2026-10-16-{event_id}-{selection}", "date": "2026-10-16", "event_id": event_id, "sport_key": "soccer_epl",
            "home": "Brighton and Hove Albion", "away": "Aston Villa", "commence_time": commence, "selection": selection,
            "odds_median": 2.3, "odds_sim": 2.18, "stake_cents": 420, "p_kairos": 0.55, "p_market": 0.42, "status": "open",
            "payout_cents": None, "closing_odds": None, "settled_date": None, "reasoning": "valeur"}


def journal(root):
    return (root / "journal" / "2026-10-17.md").read_text(encoding="utf-8")


def assert_no_secret(root, capsys):
    leaked = [p.name for p in root.rglob("*") if p.is_file() and SECRET in p.read_bytes().decode("utf-8", errors="replace")]
    captured = capsys.readouterr()
    assert leaked == [] and SECRET not in captured.out + captured.err


def test_daily_message_carries_the_days_full_hunger_after_two_prepares(tmp_root):
    seed_state()
    sent = []
    ctx = make_ctx(sent.append)
    cmd_prepare(ctx)
    cmd_prepare(ctx)  # second passage du jour : plus rien à payer, mais la faim du jour reste 50 centimes
    write_decisions(tmp_root)
    ctx.now = MIDMORNING
    cmd_apply(ctx)
    assert load_state(TODAY)["hunger_today"] == {"date": "2026-10-17", "cents": 50}
    assert "faim −0,50 ·" in sent[0]
    assert "faim −0,00" not in sent[0]


def test_prepare_does_not_reuse_hunger_recorded_on_another_day(tmp_root):
    seed_state(hunger_paid_through="2026-10-16", hunger_today={"date": "2026-10-16", "cents": 700})
    cmd_prepare(make_ctx(lambda text: None))
    assert load_state(TODAY)["hunger_today"] == {"date": "2026-10-17", "cents": 25}


@pytest.mark.parametrize("changes", [{"hunger_today": {"date": "2026-10-16", "cents": 700}}, {}])
def test_apply_reports_no_hunger_without_a_record_for_today(tmp_root, changes):
    seed_state(**changes)
    sent = []
    cmd_apply(make_ctx(sent.append, now=MIDMORNING))
    assert "faim −0,00 ·" in sent[0]


def test_rejected_forecast_named_like_a_hunger_line_does_not_crash_apply(tmp_root):
    seed_state()
    sent = []
    ctx = make_ctx(sent.append)
    cmd_prepare(ctx)
    write_decisions(tmp_root, forecasts=[{"event_id": "faim −x", "p": [0.4, 0.3, 0.3]}], bets=[])
    ctx.now = MIDMORNING
    cmd_apply(ctx)
    assert "prévision rejetée faim −x : match inconnu" in journal(tmp_root)
    assert "faim −0,50 ·" in sent[0]


@pytest.mark.parametrize("exc, shown", [
    (RuntimeError("Telegram : HTTP 502"), "Telegram : HTTP 502"),
    (OSError(f"https://api.telegram.org/bot{SECRET}/sendMessage"), "OSError"),
])
def test_telegram_failure_never_aborts_apply(tmp_root, capsys, exc, shown):
    def boom(text):
        raise exc

    seed_state()
    ctx = make_ctx(boom)
    cmd_prepare(ctx)
    write_decisions(tmp_root)
    ctx.now = MIDMORNING
    cmd_apply(ctx)
    state = load_state(TODAY)
    assert len(load_bets()) == 1
    assert state["applied_decisions"] == ["2026-10-17"] and state["last_message"] == "Je tente Brighton."
    assert (tmp_root / "site" / "data.json").exists()
    text = journal(tmp_root)
    assert "## Telegram" in text and f"Telegram indisponible : {shown}\n" in text
    assert_no_secret(tmp_root, capsys)


DEATH_MESSAGE = f"Kairos est mort le 2026-10-17. Cagnotte finale : 39,75 CHF.\nSon histoire reste en ligne : {PAGE}"


def seed_starved():
    # Sous 40 CHF (seuil de mort), sans pari ouvert : 5 % de l'avoir n'atteint plus la mise minimale de 2 CHF.
    state = new_state(date(2026, 10, 1))
    state.update(bankroll_cents=3_975, hunger_paid_through="2026-10-17")
    store.save_state(state)


def test_a_kairos_that_dies_today_gets_only_the_death_message(tmp_root):
    seed_starved()
    sent = []
    cmd_apply(make_ctx(sent.append, now=MIDMORNING))
    assert sent == [DEATH_MESSAGE]
    assert (tmp_root / "site" / "data.json").exists()


def test_death_announcement_is_retried_until_telegram_succeeds(tmp_root):
    def boom(text):
        raise RuntimeError("Telegram : HTTP 502")

    seed_starved()
    ctx = make_ctx(boom, now=MIDMORNING)
    cmd_apply(ctx)
    assert load_state(TODAY)["alive"] is False and not load_state(TODAY).get("death_announced")
    assert (tmp_root / "site" / "data.json").exists()
    assert "Telegram indisponible : Telegram : HTTP 502" in journal(tmp_root)
    sent = []
    ctx.notify = sent.append
    cmd_apply(ctx)
    assert sent == [DEATH_MESSAGE]
    assert load_state(TODAY)["death_announced"] is True
    cmd_apply(ctx)
    assert len(sent) == 1


def test_prepare_marks_a_starved_kairos_dead(tmp_root):
    state = new_state(date(2026, 10, 1))
    state.update(bankroll_cents=3_950, hunger_paid_through="2026-10-17")
    store.save_state(state)
    cmd_prepare(make_ctx(lambda text: None))
    assert load_state(TODAY)["alive"] is False and load_state(TODAY)["death_date"] == "2026-10-17"


def test_prepare_settles_a_win_before_charging_hunger(tmp_root):
    state = new_state(date(2026, 10, 14))  # trois jours de faim (75 centimes) à payer le 17
    state.update(bankroll_cents=20)
    store.save_state(state)
    store.save_bets([open_bet("2026-10-16T14:00:00Z", event_id="evt-brighton-villa", selection="1")])
    cmd_prepare(make_ctx(lambda text: None))
    assert load_bets()[0]["status"] == "won"
    assert load_state(TODAY)["bankroll_cents"] == 20 + round(420 * 2.18) - 75


def test_prepare_checks_death_after_charging_hunger(tmp_root):
    state = new_state(date(2026, 10, 1))
    state.update(bankroll_cents=4_010, hunger_paid_through="2026-10-16")  # au-dessus de 40 CHF avant la faim, en dessous après
    store.save_state(state)
    cmd_prepare(make_ctx(lambda text: None))
    assert load_state(TODAY)["bankroll_cents"] == 3_985 and load_state(TODAY)["alive"] is False


def test_prepare_checks_death_after_settling_the_last_bet(tmp_root):
    state = new_state(date(2026, 10, 1))
    state.update(bankroll_cents=100, hunger_paid_through="2026-10-17")
    store.save_state(state)
    store.save_bets([open_bet("2026-10-16T14:00:00Z", event_id="evt-brighton-villa", selection="2")])
    cmd_prepare(make_ctx(lambda text: None))
    assert load_bets()[0]["status"] == "lost" and load_state(TODAY)["alive"] is False


def test_prepare_on_a_dead_kairos_only_saves_state(tmp_root):
    state = new_state(date(2026, 10, 1))
    state.update(alive=False, death_date="2026-10-16", bankroll_cents=40)
    store.save_state(state)
    cmd_prepare(make_ctx(lambda text: None))
    assert not (tmp_root / "data").exists()
    assert load_state(TODAY)["alive"] is False


def test_prepare_degrades_to_no_model_when_football_data_is_unavailable(tmp_root):
    sent = []
    ctx = make_ctx(sent.append)
    ctx.http_get = lambda url, timeout: Resp(404)
    cmd_prepare(ctx)
    model = json.loads((tmp_root / "data" / "model" / "2026-10-17.json").read_text())
    assert model == {"events": {"evt-brighton-villa": None}, "unmatched": []}
    assert "- modèle indisponible pour Premier League : aucun résultat pour soccer_epl\n" in journal(tmp_root)
    write_decisions(tmp_root, bets=[])
    ctx.now = MIDMORNING
    cmd_apply(ctx)
    assert [f["p_model"] for f in store.load_forecasts()] == [None]


def test_model_failure_note_quotes_only_wrapped_text(tmp_root, capsys):
    def leaky(url, timeout):
        raise ConnectionError(f"GET {url}?token={SECRET}")

    ctx = make_ctx(lambda text: None)
    ctx.http_get = leaky
    cmd_prepare(ctx)
    assert "- modèle indisponible pour Premier League : ConnectionError\n" in journal(tmp_root)
    assert_no_secret(tmp_root, capsys)


class FailingApi(FakeOddsApi):
    def __init__(self, fixtures, fail_on, exc):
        super().__init__(fixtures)
        self.fail_on, self.exc = fail_on, exc

    def odds(self, sport_key):
        if self.fail_on == "odds" and sport_key == "soccer_epl":
            raise self.exc
        return super().odds(sport_key)

    def scores(self, sport_key):
        if self.fail_on == "scores":
            raise self.exc
        return super().scores(sport_key)


@pytest.mark.parametrize("fail_on, line", [
    ("odds", "cotes indisponibles pour Premier League : "),
    ("scores", "résultats indisponibles pour soccer_epl : "),
])
@pytest.mark.parametrize("exc, shown", [
    (OddsApiError("HTTP 401 sur /sports/soccer_epl/odds/"), "HTTP 401 sur /sports/soccer_epl/odds/"),
    (ValueError(f"GET https://api.the-odds-api.com/v4/sports/soccer_epl/odds/?apiKey={SECRET}"), "ValueError"),
])
def test_journal_quotes_exception_text_only_from_wrapped_clients(tmp_root, capsys, fail_on, line, exc, shown):
    store.save_bets([open_bet("2026-10-16T14:00:00Z")])
    cmd_prepare(make_ctx(lambda text: None, api=FailingApi(FIX, fail_on, exc)))
    assert f"- {line}{shown}\n" in journal(tmp_root)
    assert_no_secret(tmp_root, capsys)


@pytest.mark.parametrize("remaining, bet_commence, fetched", [
    (49, None, 0),
    (49, "2026-10-18T14:00:00Z", 1),
    (50, None, 1),
    (None, None, 1),
])
def test_credit_floor_skips_leagues_without_an_open_bet(tmp_root, remaining, bet_commence, fetched):
    if bet_commence:
        store.save_bets([open_bet(bet_commence)])
    api = FakeOddsApi(FIX, remaining=remaining)
    cmd_prepare(make_ctx(lambda text: None, api=api))
    snap = json.loads((tmp_root / "data" / "odds" / "2026-10-17.json").read_text())
    assert len(snap["events"]) == fetched
    text = journal(tmp_root)
    assert ("Premier League sauté : crédits bas (49)" in text) == (remaining == 49 and not bet_commence)
    assert ("LaLiga sauté : crédits bas (49)" in text) == (remaining == 49)


def _bad_date(root):
    write_decisions(root, date="2026-10-16")


def _not_json(root):
    (root / "decisions").mkdir()
    (root / "decisions" / "2026-10-17.json").write_text("{ pas du json", encoding="utf-8")


def _binary(root):
    (root / "decisions").mkdir()
    (root / "decisions" / "2026-10-17.json").write_bytes(b"\xff\xfe\x00")


def _directory(root):
    (root / "decisions" / "2026-10-17.json").mkdir(parents=True)


@pytest.mark.parametrize("writer, reason", [
    (_bad_date, "date incorrecte"),
    (_not_json, "fichier JSON illisible"),
    (_binary, "fichier JSON illisible"),
    (_directory, "fichier JSON illisible"),
])
def test_rejected_decisions_place_no_bet_and_send_one_apology(tmp_root, writer, reason):
    seed_state()
    sent = []
    ctx = make_ctx(sent.append)
    cmd_prepare(ctx)
    writer(tmp_root)
    ctx.now = MIDMORNING
    cmd_apply(ctx)
    cmd_apply(ctx)
    assert load_bets() == []
    assert f"décisions rejetées : {reason}\n" in journal(tmp_root)
    assert len(sent) == 1 and sent[0].startswith("J'ai rendu une copie illisible aujourd'hui. Aucun pari.")
    assert load_state(TODAY)["applied_decisions"] == ["2026-10-17"]


def test_missing_decisions_file_sends_one_silent_message_per_day(tmp_root):
    sent = []
    ctx = make_ctx(sent.append, now=MIDMORNING)
    cmd_apply(ctx)
    cmd_apply(ctx)
    assert len(sent) == 1 and sent[0].startswith("Kairos n'a pas donné signe de vie aujourd'hui.")
    assert journal(tmp_root).count("pas de fichier de décisions") == 1
    assert load_state(TODAY)["silent_notified"] == "2026-10-17"
    assert load_state(TODAY)["history"] == [{"date": "2026-10-17", "equity_cents": 10_000}]
    cmd_apply(make_ctx(sent.append, today=date(2026, 10, 18), now=datetime(2026, 10, 18, 9, 40, tzinfo=timezone.utc)))
    assert len(sent) == 2
    assert [h["date"] for h in load_state(TODAY)["history"]] == ["2026-10-17", "2026-10-18"]


def test_check_decisions_exit_codes_and_messages(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(store, "zurich_today", lambda now=None: TODAY)

    def check(path):
        code = main(["check-decisions"] + ([] if path is None else [str(path)]))
        return code, capsys.readouterr().out

    def write(name, content):
        p = tmp_path / name
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return p

    assert cmd_check_decisions(None, TODAY) == 2
    assert capsys.readouterr().out == "chemin manquant\n"
    assert check(None) == (2, "chemin manquant\n")
    assert check("") == (2, "chemin manquant\n")
    assert check(write("ok.json", json.dumps(valid_decisions()))) == (0, "fichier de décisions valide\n")
    assert check(write("old.json", json.dumps(valid_decisions(date="2026-10-16")))) == (1, "erreur : date incorrecte\n")
    for bad in (write("bad.json", "{ pas du json"), write("bin.json", b"\xff\xfe\x00"), tmp_path / "absent.json"):
        code, out = check(bad)
        assert code == 1 and out.startswith("illisible : ")


def test_check_api_reports_each_league_and_the_remaining_credits():
    api = FakeOddsApi(FIX, remaining=321)
    api.sports = lambda: [{"key": "soccer_epl", "group": "Soccer"}, {"key": "soccer_italy_serie_a", "group": "Aussie Rules"},
                          {"key": "soccer_spain_la_liga", "group": "Soccer"}, {"key": "soccer_other", "group": "Soccer"}]
    assert cmd_check_api(api).splitlines() == [
        "OK  soccer_epl", "ABSENT soccer_germany_bundesliga", "ABSENT soccer_italy_serie_a", "OK  soccer_spain_la_liga",
        "crédits restants : 321"]


def test_main_prints_without_telegram_secrets_and_sends_with_them(tmp_root, monkeypatch, capsys):
    from kairos import notify

    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "PAGE_URL"):
        monkeypatch.delenv(name, raising=False)
    calls = []
    monkeypatch.setattr(notify, "send", lambda token, chat, text: calls.append((token, chat, text)))
    assert main(["apply"]) == 0
    out = capsys.readouterr().out
    assert calls == [] and "Kairos n'a pas donné signe de vie" in out and DEFAULT_PAGE_URL in out
    (tmp_root / "state" / "kairos.json").unlink()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    assert main(["apply"]) == 0
    assert capsys.readouterr().out == ""
    assert len(calls) == 1 and calls[0][:2] == ("tok", "chat") and "Kairos n'a pas donné signe de vie" in calls[0][2]
    (tmp_root / "state" / "kairos.json").unlink()
    monkeypatch.delenv("TELEGRAM_CHAT_ID")
    assert main(["apply"]) == 0
    assert len(calls) == 1 and "Kairos n'a pas donné signe de vie" in capsys.readouterr().out
    assert main(["closing"]) == 0


def test_diploma_message_is_sent_once_on_day_56(tmp_root):
    seed_state(start_date=(TODAY - timedelta(days=55)).isoformat(), hunger_paid_through="2026-10-17")
    sent = []
    ctx = make_ctx(sent.append, now=MIDMORNING)
    cmd_apply(ctx)
    assert len(sent) == 2 and sent[1].startswith("Jour 56 : pas de diplôme pour Kairos.")
    cmd_apply(ctx)
    assert len(sent) == 2


DIPLOMA_MISSED = f"Jour 56 : pas de diplôme pour Kairos. La simulation continue jusqu'à la fin.\n{PAGE}"


def test_failed_diploma_announcement_is_retried_until_it_goes_out(tmp_root):
    seed_state(start_date=(TODAY - timedelta(days=55)).isoformat(), hunger_paid_through="2026-10-17")
    sent = []

    def flaky(text):
        if text.startswith("Jour 56"):
            raise RuntimeError("Telegram : HTTP 502")
        sent.append(text)

    ctx = make_ctx(flaky, now=MIDMORNING)
    cmd_apply(ctx)
    assert len(sent) == 1 and sent[0].startswith("Kairos n'a pas donné signe de vie")
    assert load_state(TODAY)["diploma"] == "manqué" and not load_state(TODAY).get("diploma_announced")
    assert "Telegram indisponible : Telegram : HTTP 502" in journal(tmp_root)
    ctx.notify = sent.append
    cmd_apply(ctx)
    assert sent[1:] == [DIPLOMA_MISSED]
    assert load_state(TODAY)["diploma_announced"] is True
    cmd_apply(ctx)
    assert len(sent) == 2


def test_a_dead_kairos_past_day_56_gets_no_diploma_text(tmp_root):
    state = new_state(TODAY - timedelta(days=60))
    state.update(alive=False, death_date="2026-10-16", bankroll_cents=3_975, hunger_paid_through="2026-10-17")
    store.save_state(state)
    sent = []
    cmd_apply(make_ctx(sent.append, now=MIDMORNING))
    assert load_state(TODAY)["diploma"] == "manqué" and not load_state(TODAY).get("diploma_announced")
    assert sent == [f"Kairos est mort le 2026-10-16. Cagnotte finale : 39,75 CHF.\nSon histoire reste en ligne : {PAGE}"]


def test_apply_persists_forecasts_new_source_and_lessons(tmp_root):
    sunday = date(2026, 10, 18)
    sent = []
    ctx = make_ctx(sent.append, today=sunday, now=datetime(2026, 10, 18, 8, 15, tzinfo=timezone.utc))
    cmd_prepare(ctx)
    (tmp_root / "decisions").mkdir()
    dec = valid_decisions(date="2026-10-18", new_source={"id": "compos", "description": "Compos probables", "url": "https://x"},
                          forecasts=[{"event_id": "evt-brighton-villa", "p": [0.55, 0.25, 0.20], "sources": ["compos"], "note": "valeur"}],
                          bets=[], lessons={"add": ["Toujours lire les compos."]})
    (tmp_root / "decisions" / "2026-10-18.json").write_text(json.dumps(dec), encoding="utf-8")
    ctx.now = datetime(2026, 10, 18, 9, 40, tzinfo=timezone.utc)
    cmd_apply(ctx)
    [forecast] = store.load_forecasts()
    assert forecast["sources"] == ["compos"] and forecast["p_kairos"] == [0.55, 0.25, 0.20] and forecast["p_model"] is not None
    assert store.load_sources()["compos"]["status"] == "test"
    assert store.read_text("memory/lessons.md", "").endswith("- Toujours lire les compos.\n")
    assert "nouvelle source en test : compos" in (tmp_root / "journal" / "2026-10-18.md").read_text(encoding="utf-8")
