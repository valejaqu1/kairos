import io
from datetime import date, timedelta

import pandas as pd
import penaltyblog as pb
import requests

from kairos.config import HISTORY_DAYS, League
from kairos.teams import match_team

COLUMNS = {
    "main": {"HomeTeam": "home", "AwayTeam": "away", "FTHG": "hg", "FTAG": "ag"},
    "new": {"Home": "home", "Away": "away", "HG": "hg", "AG": "ag"},
}


def season_codes(today: date) -> list[str]:
    start = today.year if today.month >= 7 else today.year - 1
    return [f"{(start - 1) % 100:02d}{start % 100:02d}", f"{start % 100:02d}{(start + 1) % 100:02d}"]


def parse_results(csv_text: str, fmt: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(csv_text)).rename(columns=COLUMNS[fmt])
    df = df[["Date", "home", "away", "hg", "ag"]].dropna()
    df["date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["date"])
    df["hg"] = df["hg"].astype(int)
    df["ag"] = df["ag"].astype(int)
    return df[["date", "home", "away", "hg", "ag"]].reset_index(drop=True)


def fetch_results(league: League, today: date, get=requests.get) -> pd.DataFrame:
    if league.fd_format == "new":
        urls = [league.fd_url]
    else:
        urls = [league.fd_url.format(season=code) for code in season_codes(today)]
    frames = []
    for url in urls:
        resp = get(url, timeout=60)
        if resp.status_code == 200 and resp.content.strip():
            frames.append(parse_results(resp.content.decode("utf-8-sig", errors="replace"), league.fd_format))
    if not frames:
        raise RuntimeError(f"aucun résultat pour {league.sport_key}")
    df = pd.concat(frames, ignore_index=True)
    cutoff = pd.Timestamp(today - timedelta(days=HISTORY_DAYS))
    return df[df["date"] >= cutoff].sort_values("date").reset_index(drop=True)


def fit_model(df: pd.DataFrame, today: date):
    weights = pb.models.dixon_coles_weights(df["date"], xi=0.0018, base_date=pd.Timestamp(today))
    model = pb.models.DixonColesGoalModel(df["hg"], df["ag"], df["home"], df["away"], weights)
    model.fit()
    return model


def predict_events(model, teams: list[str], events: list[dict], aliases: dict) -> tuple[dict, list[str]]:
    preds: dict[str, list[float] | None] = {}
    unmatched: set[str] = set()
    for ev in events:
        home = match_team(ev["home"], teams, aliases)
        away = match_team(ev["away"], teams, aliases)
        if home is None:
            unmatched.add(ev["home"])
        if away is None:
            unmatched.add(ev["away"])
        if home is None or away is None or home == away:
            preds[ev["event_id"]] = None
            continue
        grid = model.predict(home, away)
        preds[ev["event_id"]] = [round(float(grid.home_win), 4), round(float(grid.draw), 4), round(float(grid.away_win), 4)]
    return preds, sorted(unmatched)
