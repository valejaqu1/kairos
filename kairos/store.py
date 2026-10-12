import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from kairos.config import START_BANKROLL_CENTS, root


def _path(rel: str) -> Path:
    return root() / rel


def read_json(rel: str, default):
    p = _path(rel)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(rel: str, data) -> None:
    p = _path(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)


def read_text(rel: str, default: str) -> str:
    p = _path(rel)
    return p.read_text(encoding="utf-8") if p.exists() else default


def write_text(rel: str, text: str) -> None:
    p = _path(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def new_state(today: date) -> dict:
    return {
        "name": "Kairos",
        "generation": 1,
        "start_date": today.isoformat(),
        "bankroll_cents": START_BANKROLL_CENTS,
        "hunger_paid_through": today.isoformat(),
        "hunger_total_cents": 0,
        "alive": True,
        "death_date": None,
        "death_announced": False,
        "diploma": None,
        "diploma_announced": False,
        "trophies": {},
        "applied_decisions": [],
        "silent_notified": None,
        "last_message": None,
        "last_message_date": None,
        "last_run": None,
        "history": [],
    }


def load_state(today: date) -> dict:
    return read_json("state/kairos.json", None) or new_state(today)


def save_state(state: dict) -> None:
    write_json("state/kairos.json", state)


def load_bets() -> list:
    return read_json("state/bets.json", [])


def save_bets(bets: list) -> None:
    write_json("state/bets.json", bets)


def load_forecasts() -> list:
    return read_json("state/forecasts.json", [])


def save_forecasts(forecasts: list) -> None:
    write_json("state/forecasts.json", forecasts)


def load_sources() -> dict:
    return read_json("memory/sources.json", {})


def save_sources(sources: dict) -> None:
    write_json("memory/sources.json", sources)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def zurich_today(now: datetime | None = None) -> date:
    return (now or utcnow()).astimezone(ZoneInfo("Europe/Zurich")).date()


def day_number(state: dict, today: date) -> int:
    return (today - date.fromisoformat(state["start_date"])).days + 1


def append_journal(today: date, title: str, lines: list[str]) -> None:
    rel = f"journal/{today.isoformat()}.md"
    text = read_text(rel, f"# Journal de Kairos · {today.isoformat()}\n")
    body = "\n".join(f"- {line}" for line in lines) if lines else "- rien à signaler"
    write_text(rel, f"{text}\n## {title}\n\n{body}\n")
