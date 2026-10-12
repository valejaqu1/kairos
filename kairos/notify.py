import requests

from kairos.config import DIPLOMA_DAY
from kairos.metrics import equity_cents


class NotifyError(RuntimeError):
    pass


def chf(cents: int) -> str:
    sign = "−" if cents < 0 else ""
    return f"{sign}{abs(cents) / 100:.2f}".replace(".", ",")


def compose_daily(state: dict, bets: list, placed: list, hunger_cents: int, page_url: str) -> str:
    n = len(placed)
    line = f"Avoir {chf(equity_cents(state, bets))} CHF · faim −{chf(hunger_cents)} · {n} pari{'s' if n > 1 else ''} placé{'s' if n > 1 else ''}"
    message = state.get("last_message") or "Kairos n'a pas donné signe de vie aujourd'hui."
    return f"{message}\n\n{line}\n{page_url}"


def compose_death(state: dict, page_url: str) -> str:
    return (f"Kairos est mort le {state['death_date']}. Cagnotte finale : {chf(state['bankroll_cents'])} CHF.\n"
            f"Son histoire reste en ligne : {page_url}")


def compose_diploma(state: dict, result: str, page_url: str) -> str:
    if result == "obtenu":
        return f"Jour {DIPLOMA_DAY} : Kairos décroche son diplôme. Il a battu le marché et survécu.\n{page_url}"
    return f"Jour {DIPLOMA_DAY} : pas de diplôme pour Kairos. La simulation continue jusqu'à la fin.\n{page_url}"


def send(token: str, chat_id: str, text: str, post=requests.post) -> None:
    # Le jeton figure dans l'URL, et les messages requests citent cette URL : le message
    # ne reprend que le type de l'erreur. from None masque la chaîne dans les tracebacks,
    # mais exc.__context__ garde l'exception d'origine : ne jamais l'afficher.
    # Pas de raise_for_status, pour la même raison (son message cite l'URL).
    try:
        resp = post(f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, timeout=30)
    except requests.RequestException as exc:
        raise NotifyError(f"Telegram : {type(exc).__name__}") from None
    if resp.status_code >= 400:
        raise NotifyError(f"Telegram : HTTP {resp.status_code}") from None
