from datetime import date

from kairos.config import DIPLOMA_CLV_SHARE, DIPLOMA_DAY, SOURCE_MIN_USES, START_BANKROLL_CENTS
from kairos.scoring import clv
from kairos.store import day_number

TIERS = (("Bronze", 0.0, 0.45), ("Argent", 0.45, 0.55), ("Or", 0.55, 0.62))
DIVISIONS = ("I", "II", "III")
TROPHIES = {
    "premier_gain": "Premier pari gagné",
    "serie_3": "Série de 3",
    "serie_5": "Série de 5",
    "source_gardee": "Première source validée",
    "clv_10": "10 paris avant le marché",
    "survie_4_semaines": "4 semaines de survie",
    "diplome": "Diplômé",
}


def settled_forecasts(forecasts: list) -> list:
    return [f for f in forecasts if f.get("outcome") is not None]


def skill(f: dict) -> float:
    return f["rps_market"] - f["rps_kairos"]


def bet_clv(b: dict) -> float | None:
    return clv(b["odds_median"], b["closing_odds"]) if b.get("closing_odds") else None


def equity_cents(state: dict, bets: list) -> int:
    return state["bankroll_cents"] + sum(b["stake_cents"] for b in bets if b["status"] == "open")


def update_sources(sources: dict, forecasts: list) -> None:
    per_source: dict[str, list[float]] = {}
    for f in settled_forecasts(forecasts):
        for sid in f.get("sources", []):
            per_source.setdefault(sid, []).append(skill(f))
    for sid, meta in sources.items():
        values = per_source.get(sid, [])
        meta["uses"] = len(values)
        meta["score"] = round(sum(values) / len(values), 4) if values else None
        if len(values) >= SOURCE_MIN_USES:
            meta["status"] = "kept" if meta["score"] > 0 else "dropped"
        else:
            meta["status"] = "test"


def _settled_bets(bets: list) -> list:
    done = [b for b in bets if b["status"] in ("won", "lost")]
    return sorted(done, key=lambda b: (b["settled_date"], b["commence_time"]))


def rank(forecasts: list, bets: list) -> dict:
    recent_fc = settled_forecasts(forecasts)[-30:]
    recent_clv = [c for c in (bet_clv(b) for b in _settled_bets(bets)) if c is not None][-20:]
    parts = []
    if recent_fc:
        parts.append(sum(1 for f in recent_fc if skill(f) > 0) / len(recent_fc))
    if recent_clv:
        parts.append(sum(1 for c in recent_clv if c > 0) / len(recent_clv))
    score = sum(parts) / len(parts) if parts else 0.0
    if score >= 0.62:
        return {"tier": "Platine", "division": None, "score": round(score, 3), "progress": 1.0, "next": None}
    for i, (name, lo, hi) in enumerate(TIERS):
        if score < hi:
            third = (hi - lo) / 3
            idx = min(2, int((score - lo) // third))
            progress = (score - (lo + idx * third)) / third
            if idx < 2:
                nxt = f"{name} {DIVISIONS[idx + 1]}"
            else:
                nxt = "Platine" if i == len(TIERS) - 1 else f"{TIERS[i + 1][0]} I"
            return {"tier": name, "division": DIVISIONS[idx], "score": round(score, 3), "progress": round(progress, 3), "next": nxt}
    raise AssertionError("unreachable")


def current_streak(bets: list) -> int:
    streak = 0
    for b in reversed(_settled_bets(bets)):
        if b["status"] != "won":
            break
        streak += 1
    return streak


def _best_streak(bets: list) -> int:
    best = run = 0
    for b in _settled_bets(bets):
        run = run + 1 if b["status"] == "won" else 0
        best = max(best, run)
    return best


def update_trophies(state: dict, bets: list, sources: dict, today: date) -> list[str]:
    earned = state["trophies"]
    new = []

    def award(key: str) -> None:
        if key not in earned:
            earned[key] = today.isoformat()
            new.append(key)

    if any(b["status"] == "won" for b in bets):
        award("premier_gain")
    best = _best_streak(bets)
    if best >= 3:
        award("serie_3")
    if best >= 5:
        award("serie_5")
    if any(m.get("status") == "kept" for m in sources.values()):
        award("source_gardee")
    if sum(1 for b in bets if (c := bet_clv(b)) is not None and c > 0) >= 10:
        award("clv_10")
    if state["alive"] and day_number(state, today) >= 28:
        award("survie_4_semaines")
    if state.get("diploma") == "obtenu":
        award("diplome")
    return new


def check_diploma(state: dict, bets: list, forecasts: list, today: date) -> str | None:
    if state.get("diploma") is not None or day_number(state, today) < DIPLOMA_DAY:
        return None
    scored = settled_forecasts(forecasts)
    mean_skill = sum(skill(f) for f in scored) / len(scored) if scored else 0.0
    clvs = [c for c in (bet_clv(b) for b in bets) if c is not None]
    clv_share = sum(1 for c in clvs if c > 0) / len(clvs) if clvs else 0.0
    ok = state["alive"] and equity_cents(state, bets) >= START_BANKROLL_CENTS and mean_skill > 0 and clv_share >= DIPLOMA_CLV_SHARE
    state["diploma"] = "obtenu" if ok else "manqué"
    return state["diploma"]


def stats(bets: list) -> dict:
    done = _settled_bets(bets)
    staked = sum(b["stake_cents"] for b in done)
    returned = sum(b["payout_cents"] for b in done)
    clvs = [c for c in (bet_clv(b) for b in done) if c is not None]
    return {
        "bets": len(done),
        "won": sum(1 for b in done if b["status"] == "won"),
        "roi": (returned - staked) / staked if staked else 0.0,
        "clv_avg": sum(clvs) / len(clvs) if clvs else 0.0,
        "clv_beats": sum(1 for c in clvs if c > 0),
        "clv_total": len(clvs),
    }
