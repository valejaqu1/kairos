from datetime import date

from kairos.config import DEATH_THRESHOLD_CENTS, HUNGER_CENTS_PER_DAY


def apply_hunger(state: dict, today: date) -> int:
    days = (today - date.fromisoformat(state["hunger_paid_through"])).days
    if days <= 0 or not state["alive"]:
        return 0
    cost = min(days * HUNGER_CENTS_PER_DAY, max(state["bankroll_cents"], 0))
    state["bankroll_cents"] -= cost
    state["hunger_total_cents"] = state.get("hunger_total_cents", 0) + cost
    state["hunger_paid_through"] = today.isoformat()
    return cost


def check_death(state: dict, bets: list, today: date) -> bool:
    if not state["alive"]:
        return False
    has_open = any(b["status"] == "open" for b in bets)
    if state["bankroll_cents"] < DEATH_THRESHOLD_CENTS and not has_open:
        state["alive"] = False
        state["death_date"] = today.isoformat()
        return True
    return False
