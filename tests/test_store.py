from datetime import date, datetime, timezone

from kairos import store
from kairos.config import START_BANKROLL_CENTS


def test_new_state_starts_alive_with_bankroll(tmp_root):
    s = store.load_state(date(2026, 10, 13))
    assert s["alive"] is True
    assert s["bankroll_cents"] == START_BANKROLL_CENTS
    assert s["start_date"] == "2026-10-13"
    assert s["hunger_paid_through"] == "2026-10-13"
    assert s["history"] == []


def test_write_then_read_json_roundtrip(tmp_root):
    store.write_json("state/bets.json", [{"id": "a", "stake_cents": 310}])
    assert store.load_bets() == [{"id": "a", "stake_cents": 310}]
    assert (tmp_root / "state" / "bets.json").read_text().endswith("\n")


def test_missing_files_return_defaults(tmp_root):
    assert store.load_bets() == []
    assert store.load_forecasts() == []
    assert store.load_sources() == {}
    assert store.read_text("memory/lessons.md", "") == ""


def test_zurich_today_crosses_midnight():
    late_utc = datetime(2026, 10, 12, 22, 30, tzinfo=timezone.utc)
    assert store.zurich_today(late_utc) == date(2026, 10, 13)


def test_day_number_counts_start_as_day_one():
    s = {"start_date": "2026-10-13"}
    assert store.day_number(s, date(2026, 10, 13)) == 1
    assert store.day_number(s, date(2026, 12, 7)) == 56


def test_append_journal_adds_sections(tmp_root):
    store.append_journal(date(2026, 10, 13), "Matin", ["faim : 0,25"])
    store.append_journal(date(2026, 10, 13), "Décisions", ["1 pari"])
    text = (tmp_root / "journal" / "2026-10-13.md").read_text()
    assert text.startswith("# Journal de Kairos · 2026-10-13")
    assert "## Matin\n\n- faim : 0,25" in text
    assert "## Décisions\n\n- 1 pari" in text
