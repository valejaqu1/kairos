import os
from dataclasses import dataclass
from pathlib import Path

START_BANKROLL_CENTS = 10_000
HUNGER_CENTS_PER_DAY = 25
ODDS_HAIRCUT = 0.95
MIN_SIM_ODDS = 1.01
VALUE_THRESHOLD = 0.05
KELLY_FRACTION = 0.25
MAX_STAKE_SHARE = 0.05
MIN_STAKE_CENTS = 200
MIN_BET_ODDS = 1.10
STAKE_STEP_CENTS = 10
MAX_BETS_PER_DAY = 3
MAX_EXPOSURE_SHARE = 0.15
# Plus petit avoir où 5 % atteignent la mise minimale : en dessous, Kairos ne peut plus miser (40 CHF).
DEATH_THRESHOLD_CENTS = round(MIN_STAKE_CENTS / MAX_STAKE_SHARE)
DIPLOMA_DAY = 56
DIPLOMA_CLV_SHARE = 0.55
VOID_AFTER_DAYS = 3
LOOKAHEAD_HOURS = 48
MAX_FORECASTS_PER_DAY = 10
MAX_SOURCES_PER_FORECAST = 5
MAX_LESSONS = 15
MAX_LESSONS_ADDED = 2
MAX_MESSAGE_CHARS = 600
SOURCE_MIN_USES = 10
CREDIT_FLOOR = 50
CLOSING_WINDOW_MIN = 45
KICKOFF_MARGIN_MIN = 10
HISTORY_DAYS = 730
DEFAULT_PAGE_URL = "https://valejaqu1.github.io/kairos/"


@dataclass(frozen=True)
class League:
    sport_key: str
    fd_url: str
    fd_format: str
    label: str


LEAGUES = (
    League("soccer_epl", "https://www.football-data.co.uk/mmz4281/{season}/E0.csv", "main", "Premier League"),
    League("soccer_spain_la_liga", "https://www.football-data.co.uk/mmz4281/{season}/SP1.csv", "main", "LaLiga"),
    League("soccer_italy_serie_a", "https://www.football-data.co.uk/mmz4281/{season}/I1.csv", "main", "Serie A"),
    League("soccer_germany_bundesliga", "https://www.football-data.co.uk/mmz4281/{season}/D1.csv", "main", "Bundesliga"),
)


def league_label(sport_key: str) -> str:
    for league in LEAGUES:
        if league.sport_key == sport_key:
            return league.label
    return sport_key


def root() -> Path:
    return Path(os.environ.get("KAIROS_ROOT", Path.cwd()))
