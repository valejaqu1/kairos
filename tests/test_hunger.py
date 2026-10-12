from datetime import date

from kairos.hunger import apply_hunger, check_death
from kairos.store import new_state


def test_hunger_charges_missed_days():
    s = new_state(date(2026, 10, 13))
    assert apply_hunger(s, date(2026, 10, 16)) == 75
    assert s["bankroll_cents"] == 9925
    assert s["hunger_paid_through"] == "2026-10-16"
    assert s["hunger_total_cents"] == 75
    assert apply_hunger(s, date(2026, 10, 16)) == 0


def test_hunger_never_goes_negative():
    s = new_state(date(2026, 10, 13))
    s["bankroll_cents"] = 30
    assert apply_hunger(s, date(2026, 10, 15)) == 30
    assert s["bankroll_cents"] == 0


def test_death_waits_for_open_bets():
    s = new_state(date(2026, 10, 13))
    s["bankroll_cents"] = 50
    assert check_death(s, [{"status": "open"}], date(2026, 10, 20)) is False
    assert s["alive"] is True
    assert check_death(s, [{"status": "lost"}], date(2026, 10, 20)) is True
    assert s["alive"] is False and s["death_date"] == "2026-10-20"


# Tests complementaires : branches non verrouillees par la liste du brief.


def test_hunger_on_dead_state_charges_nothing():
    s = new_state(date(2026, 10, 13))
    s["bankroll_cents"] = 5000
    s["alive"] = False
    assert apply_hunger(s, date(2026, 10, 16)) == 0
    assert s["bankroll_cents"] == 5000
    assert s["hunger_paid_through"] == "2026-10-13"


def test_hunger_ignores_paid_through_in_the_future():
    s = new_state(date(2026, 10, 13))
    assert apply_hunger(s, date(2026, 10, 10)) == 0
    assert s["bankroll_cents"] == 10_000
    assert s["hunger_paid_through"] == "2026-10-13"


def test_hunger_total_accumulates_across_charges():
    s = new_state(date(2026, 10, 13))
    assert apply_hunger(s, date(2026, 10, 15)) == 50
    assert apply_hunger(s, date(2026, 10, 18)) == 75
    assert s["hunger_total_cents"] == 125
    assert s["bankroll_cents"] == 9875


def test_hunger_never_refunds_a_negative_bankroll():
    s = new_state(date(2026, 10, 13))
    s["bankroll_cents"] = -10
    assert apply_hunger(s, date(2026, 10, 15)) == 0
    assert s["bankroll_cents"] == -10


def test_death_threshold_is_strictly_below_200():
    s = new_state(date(2026, 10, 13))
    s["bankroll_cents"] = 200
    assert check_death(s, [], date(2026, 10, 20)) is False
    s["bankroll_cents"] = 199
    assert check_death(s, [], date(2026, 10, 20)) is True


def test_dead_state_is_not_killed_twice():
    s = new_state(date(2026, 10, 13))
    s["bankroll_cents"] = 50
    s["alive"] = False
    s["death_date"] = "2026-10-18"
    assert check_death(s, [], date(2026, 10, 20)) is False
    assert s["death_date"] == "2026-10-18"
