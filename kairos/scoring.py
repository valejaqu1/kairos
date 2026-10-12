def rps(p: list[float], outcome: int) -> float:
    observed = [0.0, 0.0, 0.0]
    observed[outcome] = 1.0
    cum_p = cum_o = total = 0.0
    for k in range(2):
        cum_p += p[k]
        cum_o += observed[k]
        total += (cum_p - cum_o) ** 2
    return round(total / 2, 6)


def clv(taken: float, closing: float) -> float:
    return round(taken / closing - 1, 4)


def outcome_from_goals(home: int, away: int) -> int:
    if home > away:
        return 0
    if home == away:
        return 1
    return 2
