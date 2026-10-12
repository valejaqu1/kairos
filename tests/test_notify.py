from datetime import date

import pytest
import requests

from kairos.notify import NotifyError, chf, compose_daily, compose_death, compose_diploma, send
from kairos.store import new_state

URL = "https://valejaqu1.github.io/kairos/"


def test_chf():
    assert chf(10_420) == "104,20" and chf(-25) == "−0,25" and chf(5) == "0,05"


def test_compose_daily():
    s = new_state(date(2026, 10, 1))
    s["bankroll_cents"] = 10_110
    s["last_message"] = "Je mise sur Servette."
    text = compose_daily(s, [{"status": "open", "stake_cents": 310}], [{"id": "x"}], 25, URL)
    assert text.startswith("Je mise sur Servette.")
    assert "Avoir 104,20 CHF · faim −0,25 · 1 pari placé" in text
    assert text.endswith(URL)


def test_compose_death_and_diploma():
    s = new_state(date(2026, 10, 1))
    s["alive"], s["death_date"], s["bankroll_cents"] = False, "2026-11-02", 40
    assert "Kairos est mort le 2026-11-02" in compose_death(s, URL)
    assert "diplôme" in compose_diploma(s, "obtenu", URL).lower()


def test_send_posts_json():
    calls = []

    class R:
        status_code = 200

        def raise_for_status(self):
            pass

    def post(url, json, timeout):
        calls.append((url, json))
        return R()

    send("TOKEN", "42", "salut", post=post)
    assert calls == [("https://api.telegram.org/botTOKEN/sendMessage", {"chat_id": "42", "text": "salut", "disable_web_page_preview": True})]


def test_compose_daily_without_last_message():
    s = new_state(date(2026, 10, 1))
    assert s["last_message"] is None
    text = compose_daily(s, [], [], 25, URL)
    assert text == f"Kairos n'a pas donné signe de vie aujourd'hui.\n\nAvoir 100,00 CHF · faim −0,25 · 0 pari placé\n{URL}"


def test_compose_daily_plural_bets():
    s = new_state(date(2026, 10, 1))
    s["bankroll_cents"] = 10_110
    text = compose_daily(s, [{"status": "open", "stake_cents": 310}], [{"id": "x"}, {"id": "y"}], 25, URL)
    assert text.split("\n")[2] == "Avoir 104,20 CHF · faim −0,25 · 2 paris placés"


def test_compose_diploma_not_obtained():
    text = compose_diploma(new_state(date(2026, 10, 1)), "manqué", URL)
    assert text == f"Jour 56 : pas de diplôme pour Kairos. La simulation continue jusqu'à la fin.\n{URL}"


@pytest.mark.parametrize("result", ["obtenu", "manqué"])
def test_compose_diploma_day_from_config(monkeypatch, result):
    monkeypatch.setattr("kairos.notify.DIPLOMA_DAY", 60)
    text = compose_diploma(new_state(date(2026, 10, 1)), result, URL)
    assert text.startswith("Jour 60 : ")


def test_send_http_error_hides_token():
    class R:
        status_code = 401

        def raise_for_status(self):
            raise requests.HTTPError("401 Client Error: Unauthorized for url: https://api.telegram.org/botSECRET123/sendMessage")

    with pytest.raises(NotifyError) as info:
        send("SECRET123", "42", "salut", post=lambda url, json, timeout: R())
    assert "SECRET123" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


@pytest.mark.parametrize("exc", [
    requests.ConnectionError("HTTPSConnectionPool(host='api.telegram.org'): Max retries exceeded with url: /botSECRET123/sendMessage"),
    requests.Timeout("HTTPSConnectionPool(host='api.telegram.org'): Read timed out. with url: /botSECRET123/sendMessage"),
])
def test_send_network_error_hides_token(exc):
    def post(url, json, timeout):
        raise exc

    with pytest.raises(NotifyError) as info:
        send("SECRET123", "42", "salut", post=post)
    assert str(info.value) == f"Telegram : {type(exc).__name__}"
    assert "SECRET123" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_send_timeout_is_30():
    timeouts = []

    class R:
        status_code = 200

    def post(url, json, timeout):
        timeouts.append(timeout)
        return R()

    send("TOKEN", "42", "salut", post=post)
    assert timeouts == [30]


def test_notify_error_is_runtime_error():
    assert issubclass(NotifyError, RuntimeError)


def test_send_400_is_failure():
    class R:
        status_code = 400

    with pytest.raises(NotifyError, match="HTTP 400"):
        send("SECRET123", "42", "salut", post=lambda url, json, timeout: R())
