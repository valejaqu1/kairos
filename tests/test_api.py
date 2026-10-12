from pathlib import Path

import pytest
import requests

from kairos.api import FakeOddsApi, OddsApi

FIX = Path(__file__).parent / "fixtures"


class Resp:
    def __init__(self, status, payload, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, dict(params)))
        return self.responses.pop(0)


def test_odds_passes_key_and_reads_credits(monkeypatch):
    monkeypatch.setattr("kairos.api.time.sleep", lambda s: None)
    s = Session([Resp(200, [{"id": "x"}], {"x-requests-remaining": "487"})])
    api = OddsApi("KEY", session=s)
    assert api.odds("soccer_epl") == [{"id": "x"}]
    url, params = s.calls[0]
    assert url.endswith("/v4/sports/soccer_epl/odds/")
    assert params["apiKey"] == "KEY" and params["regions"] == "eu" and params["markets"] == "h2h"
    assert api.remaining == 487


def test_retries_on_server_error(monkeypatch):
    monkeypatch.setattr("kairos.api.time.sleep", lambda s: None)
    s = Session([Resp(503, {}), Resp(200, [])])
    assert OddsApi("KEY", session=s).scores("soccer_epl") == []
    assert s.calls[0][1]["daysFrom"] == 3


def test_gives_up_after_three_attempts(monkeypatch):
    monkeypatch.setattr("kairos.api.time.sleep", lambda s: None)
    s = Session([Resp(503, {}), Resp(503, {}), Resp(503, {})])
    with pytest.raises(RuntimeError):
        OddsApi("KEY", session=s).odds("soccer_epl")


def test_fake_api_reads_fixtures():
    fake = FakeOddsApi(FIX)
    assert fake.odds("soccer_epl")[0]["id"] == "evt-brighton-villa"
    assert fake.scores("soccer_epl")[0]["completed"] is True
    assert fake.odds("soccer_unknown") == []
    assert fake.event_odds("soccer_epl", "nope") == {}
    assert fake.sports()[1]["key"] == "soccer_switzerland_superleague"


def test_does_not_retry_client_error(monkeypatch):
    monkeypatch.setattr("kairos.api.time.sleep", lambda s: None)
    s = Session([Resp(401, {}), Resp(200, [])])
    with pytest.raises(RuntimeError):
        OddsApi("KEY", session=s).odds("soccer_epl")
    assert len(s.calls) == 1


def test_retries_on_connection_error(monkeypatch):
    monkeypatch.setattr("kairos.api.time.sleep", lambda s: None)
    s = Session([Resp(200, [{"id": "y"}])])
    attempts = []

    def flaky_get(url, params, timeout):
        attempts.append(url)
        if len(attempts) == 1:
            raise requests.ConnectionError("reset")
        return Session.get(s, url, params, timeout)

    s.get = flaky_get
    assert OddsApi("KEY", session=s).odds("soccer_epl") == [{"id": "y"}]
    assert len(attempts) == 2


def test_keeps_last_known_credits_when_header_missing(monkeypatch):
    monkeypatch.setattr("kairos.api.time.sleep", lambda s: None)
    s = Session([Resp(200, [], {"x-requests-remaining": "300"}), Resp(200, [])])
    api = OddsApi("KEY", session=s)
    api.odds("soccer_epl")
    api.odds("soccer_epl")
    assert api.remaining == 300


@pytest.mark.parametrize("status", [429, 500, 502, 504])
def test_retries_each_transient_status(monkeypatch, status):
    monkeypatch.setattr("kairos.api.time.sleep", lambda s: None)
    s = Session([Resp(status, {}), Resp(200, [])])
    assert OddsApi("KEY", session=s).scores("soccer_epl") == []
    assert len(s.calls) == 2


def test_backs_off_between_attempts(monkeypatch):
    sleeps = []
    monkeypatch.setattr("kairos.api.time.sleep", sleeps.append)
    s = Session([Resp(503, {}), Resp(503, {}), Resp(503, {})])
    with pytest.raises(RuntimeError):
        OddsApi("KEY", session=s).odds("soccer_epl")
    assert sleeps == [5, 10]


def test_fake_event_odds_reads_event_file(tmp_path):
    (tmp_path / "event_odds_evt-live.json").write_text('{"id": "evt-live"}', encoding="utf-8")
    fake = FakeOddsApi(tmp_path)
    assert fake.event_odds("soccer_epl", "evt-live") == {"id": "evt-live"}
