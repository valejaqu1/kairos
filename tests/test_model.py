from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import penaltyblog as pb
import pytest

from kairos.config import League
from kairos.model import fetch_results, fit_model, parse_results, predict_events, season_codes

FIX = Path(__file__).parent / "fixtures"


class Resp:
    def __init__(self, status, content=b""):
        self.status_code = status
        self.content = content


def test_season_codes_follow_july_switch():
    assert season_codes(date(2026, 10, 12)) == ["2526", "2627"]
    assert season_codes(date(2027, 3, 1)) == ["2526", "2627"]
    assert season_codes(date(2027, 7, 15)) == ["2627", "2728"]


def test_parse_results_both_formats():
    main = parse_results((FIX / "fd_main.csv").read_text(), "main")
    new = parse_results((FIX / "fd_new.csv").read_text(), "new")
    assert list(main.columns) == ["date", "home", "away", "hg", "ag"]
    assert main.iloc[0].tolist()[1:] == ["Brighton", "Villa", 2, 1]
    assert new.iloc[0]["home"] == "Servette"


def test_fetch_results_skips_missing_season_and_old_rows():
    main_csv = (FIX / "fd_main.csv").read_bytes()

    def get(url, timeout):
        return Resp(200, main_csv) if "2526" in url else Resp(404)

    league = League("soccer_epl", "https://x/{season}/E0.csv", "main", "PL")
    df = fetch_results(league, date(2026, 10, 12), get=get)
    assert len(df) == 2

    new_league = League("soccer_switzerland_superleague", "https://x/new/SWZ.csv", "new", "SL")
    df_new = fetch_results(new_league, date(2026, 10, 12), get=lambda url, timeout: Resp(200, (FIX / "fd_new.csv").read_bytes()))
    assert df_new["home"].tolist() == ["Servette"]


def _synthetic_results():
    # Scores tirés d'une loi de Poisson à graine fixe : des scores déterministes par équipe
    # font diverger rho vers sa borne (-2,5) et penaltyblog 1.13 refuse alors toute prévision.
    rng = np.random.default_rng(0)
    strength = {"Strong": 1.5, "Mid": 1.0, "Other": 1.0, "Weak": 0.7}
    rows = []
    teams = ["Strong", "Mid", "Weak", "Other"]
    day = pd.Timestamp("2026-01-01")
    for round_ in range(6):
        for h in teams:
            for a in teams:
                if h == a:
                    continue
                hg = int(rng.poisson(1.3 * strength[h] / strength[a]))
                ag = int(rng.poisson(1.0 * strength[a] / strength[h]))
                rows.append({"date": day, "home": h, "away": a, "hg": hg, "ag": ag})
                day += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


def test_fit_and_predict_favours_strong_team():
    df = _synthetic_results()
    model = fit_model(df, date(2026, 6, 1))
    events = [
        {"event_id": "e1", "home": "Strong FC", "away": "Weak"},
        {"event_id": "e2", "home": "Real Madrid", "away": "Weak"},
    ]
    preds, unmatched = predict_events(model, ["Strong", "Mid", "Weak", "Other"], events, {})
    p = preds["e1"]
    assert sum(p) == pytest.approx(1.0, abs=1e-3)
    assert p[0] > 0.6
    assert preds["e2"] is None
    assert unmatched == ["Real Madrid"]


# --- Tests ajoutés (hors liste du brief) : chaque branche ci-dessous n'était gardée par aucun test ---

MAIN_HEADER = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
TODAY = date(2026, 10, 12)
EPL = League("soccer_epl", "https://x/{season}/E0.csv", "main", "PL")
TEAMS = ["Strong", "Mid", "Weak", "Other"]


def _main_csv(*rows):
    return (MAIN_HEADER + "".join(f"E0,{r}\n" for r in rows)).encode()


@pytest.fixture(scope="module")
def fitted():
    return fit_model(_synthetic_results(), date(2026, 6, 1))


def test_parse_results_maps_every_column_of_the_new_format():
    new = parse_results((FIX / "fd_new.csv").read_text(), "new")
    assert new.iloc[0].tolist()[1:] == ["Servette", "Lugano", 3, 1]
    assert new.iloc[1].tolist()[1:] == ["Servette", "Basel", 0, 2]


def test_parse_results_reads_day_first_dates_and_drops_incomplete_rows():
    csv_text = MAIN_HEADER + "".join(
        [
            "E0,05/10/2025,15:00,A,B,2,1,H\n",
            "E0,12/10/2025,15:00,C,D,,,\n",
            "E0,TBD,15:00,E,F,0,0,D\n",
            "E0,06/10/2025,15:00,G,H,1,3,A\n",
        ]
    )
    df = parse_results(csv_text, "main")
    assert df["home"].tolist() == ["A", "G"]
    assert df.index.tolist() == [0, 1]
    assert df["date"].tolist() == [pd.Timestamp(2025, 10, 5), pd.Timestamp(2025, 10, 6)]
    assert df["hg"].dtype.kind == "i" and df["ag"].dtype.kind == "i"


def _recording_get(calls, content):
    def get(url, timeout):
        calls.append((url, timeout))
        return Resp(200, content)

    return get


def test_fetch_results_requests_each_season_url_with_timeout():
    calls = []
    fetch_results(EPL, TODAY, get=_recording_get(calls, _main_csv("16/08/2025,15:00,A,B,2,1,H")))
    assert calls == [("https://x/2526/E0.csv", 60), ("https://x/2627/E0.csv", 60)]

    calls.clear()
    new_league = League("soccer_switzerland_superleague", "https://x/new/SWZ.csv", "new", "SL")
    fetch_results(new_league, TODAY, get=_recording_get(calls, (FIX / "fd_new.csv").read_bytes()))
    assert calls == [("https://x/new/SWZ.csv", 60)]


def test_fetch_results_merges_both_seasons_in_date_order():
    def get(url, timeout):
        row = "16/08/2025,15:00,A,B,2,1,H" if "2526" in url else "15/08/2026,15:00,C,D,0,0,D"
        return Resp(200, _main_csv(row))

    df = fetch_results(EPL, TODAY, get=get)
    assert df["home"].tolist() == ["A", "C"]


def test_fetch_results_ignores_error_pages_and_empty_files():
    good = _main_csv("16/08/2025,15:00,A,B,2,1,H")
    html_404 = Resp(404, b"<html><body>Not Found</body></html>")
    blank_200 = Resp(200, b"  \n")
    first_ok = fetch_results(EPL, TODAY, get=lambda url, timeout: Resp(200, good) if "2526" in url else html_404)
    second_ok = fetch_results(EPL, TODAY, get=lambda url, timeout: blank_200 if "2526" in url else Resp(200, good))
    assert len(first_ok) == 1
    assert len(second_ok) == 1


def test_fetch_results_raises_when_no_season_is_available():
    with pytest.raises(RuntimeError, match="soccer_epl"):
        fetch_results(EPL, TODAY, get=lambda url, timeout: Resp(404))


@pytest.mark.parametrize("status", [403, 429, 500, 503])
@pytest.mark.parametrize("failing_season", ["2526", "2627"])
def test_fetch_results_raises_on_a_non_404_error_instead_of_training_on_one_season(status, failing_season):
    good = _main_csv("16/08/2025,15:00,A,B,2,1,H")

    def get(url, timeout):
        return Resp(status, b"<html>oops</html>") if failing_season in url else Resp(200, good)

    with pytest.raises(RuntimeError) as err:
        fetch_results(EPL, TODAY, get=get)
    assert f"football-data HTTP {status} pour https://x/{failing_season}/E0.csv" in str(err.value)


def test_fetch_results_raises_on_a_non_404_error_for_the_single_new_format_file():
    new_league = League("soccer_switzerland_superleague", "https://x/new/SWZ.csv", "new", "SL")
    with pytest.raises(RuntimeError, match="HTTP 503 pour https://x/new/SWZ.csv"):
        fetch_results(new_league, TODAY, get=lambda url, timeout: Resp(503))


def test_fetch_results_accepts_a_missing_first_season_file():
    good = _main_csv("16/08/2025,15:00,A,B,2,1,H")
    df = fetch_results(EPL, TODAY, get=lambda url, timeout: Resp(404) if "2526" in url else Resp(200, good))
    assert df["home"].tolist() == ["A"]


def test_fetch_results_keeps_the_cutoff_day_drops_the_day_before_and_sorts():
    csv_bytes = _main_csv(
        "20/03/2025,15:00,A,B,1,0,H",
        "11/10/2024,15:00,C,D,1,1,D",
        "12/10/2024,15:00,E,F,2,2,D",
    )
    df = fetch_results(EPL, TODAY, get=lambda url, timeout: Resp(200, csv_bytes) if "2526" in url else Resp(404))
    assert df["home"].tolist() == ["E", "A"]
    assert df.index.tolist() == [0, 1]


def test_fit_model_applies_time_decay_weights(monkeypatch):
    calls = []
    real = pb.models.dixon_coles_weights

    def spy(dates, xi, base_date):
        calls.append((xi, base_date))
        return real(dates, xi=xi, base_date=base_date)

    monkeypatch.setattr(pb.models, "dixon_coles_weights", spy)
    df = _synthetic_results()
    model = fit_model(df, date(2026, 6, 1))
    expected = real(df["date"], xi=0.0018, base_date=pd.Timestamp(2026, 6, 1))
    assert calls == [(0.0018, pd.Timestamp(2026, 6, 1))]
    assert model.weights.tolist() == expected.tolist()


def test_predict_events_returns_home_draw_away_rounded_to_four_decimals(fitted):
    preds, unmatched = predict_events(fitted, TEAMS, [{"event_id": "e1", "home": "Strong", "away": "Weak"}], {})
    grid = fitted.predict("Strong", "Weak")
    assert preds["e1"] == [round(grid.home_win, 4), round(grid.draw, 4), round(grid.away_win, 4)]
    assert unmatched == []


def test_predict_events_flags_unknown_away_team_and_skips_same_team(fitted):
    events = [
        {"event_id": "e1", "home": "Strong", "away": "Nowhere FC"},
        {"event_id": "e2", "home": "Strong FC", "away": "Strong"},
    ]
    preds, unmatched = predict_events(fitted, TEAMS, events, {})
    assert preds == {"e1": None, "e2": None}
    assert unmatched == ["Nowhere FC"]


def test_predict_events_lists_each_unmatched_name_once_in_sorted_order(fitted):
    events = [
        {"event_id": "e1", "home": "Zed United", "away": "Weak"},
        {"event_id": "e2", "home": "Real Madrid", "away": "Weak"},
        {"event_id": "e3", "home": "Zed United", "away": "Mid"},
    ]
    _, unmatched = predict_events(fitted, TEAMS, events, {})
    assert unmatched == ["Real Madrid", "Zed United"]


def test_predict_events_resolves_names_through_aliases(fitted):
    events = [{"event_id": "e1", "home": "Los Blancos", "away": "Los Debiles"}]
    aliases = {"Los Blancos": "Strong", "Los Debiles": "Weak"}
    preds, unmatched = predict_events(fitted, TEAMS, events, aliases)
    assert preds["e1"] == predict_events(fitted, TEAMS, [{"event_id": "e1", "home": "Strong", "away": "Weak"}], {})[0]["e1"]
    assert unmatched == []
