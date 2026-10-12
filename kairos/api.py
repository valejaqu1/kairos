import json
import time
from pathlib import Path

import requests

BASE = "https://api.the-odds-api.com/v4"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class OddsApi:
    def __init__(self, key: str, session=None):
        self.key = key
        self.session = session or requests.Session()
        self.remaining: int | None = None

    def _get(self, path: str, **params):
        params["apiKey"] = self.key
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.get(f"{BASE}{path}", params=params, timeout=30)
            except requests.ConnectionError as exc:
                last_error = exc
            else:
                if resp.status_code not in RETRY_STATUSES:
                    resp.raise_for_status()
                    remaining = resp.headers.get("x-requests-remaining")
                    if remaining is not None:
                        self.remaining = int(float(remaining))
                    return resp.json()
                last_error = RuntimeError(f"HTTP {resp.status_code}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
        raise last_error

    def odds(self, sport_key: str) -> list:
        return self._get(f"/sports/{sport_key}/odds/", regions="eu", markets="h2h", oddsFormat="decimal", dateFormat="iso")

    def scores(self, sport_key: str) -> list:
        return self._get(f"/sports/{sport_key}/scores/", daysFrom=3, dateFormat="iso")

    def event_odds(self, sport_key: str, event_id: str) -> dict:
        return self._get(f"/sports/{sport_key}/events/{event_id}/odds", regions="eu", markets="h2h", oddsFormat="decimal", dateFormat="iso")

    def sports(self) -> list:
        return self._get("/sports/")


class FakeOddsApi:
    def __init__(self, fixtures: Path, remaining: int = 500):
        self.dir = Path(fixtures)
        self.remaining = remaining

    def _load(self, name: str, default):
        p = self.dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

    def odds(self, sport_key: str) -> list:
        return self._load(f"odds_{sport_key}.json", [])

    def scores(self, sport_key: str) -> list:
        return self._load(f"scores_{sport_key}.json", [])

    def event_odds(self, sport_key: str, event_id: str) -> dict:
        return self._load(f"event_odds_{event_id}.json", {})

    def sports(self) -> list:
        return self._load("sports.json", [])
