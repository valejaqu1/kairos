import re
import unicodedata
from difflib import get_close_matches

from kairos.store import read_json

COMMON_TOKENS = {"fc", "afc", "cf", "ac", "as", "sc", "ssc", "fk", "bc", "bsc", "club", "calcio", "1", "sv", "tsg", "vfb", "vfl", "us"}


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(t for t in s.split() if t not in COMMON_TOKENS)


def match_team(name: str, candidates: list[str], aliases: dict[str, str]) -> str | None:
    if name in aliases and aliases[name] in candidates:
        return aliases[name]
    by_norm = {normalize(c): c for c in candidates}
    n = normalize(name)
    if not n:
        return None
    if n in by_norm:
        return by_norm[n]
    for key, cand in by_norm.items():
        if min(len(n), len(key)) >= 4 and (n.startswith(key) or key.startswith(n)):
            return cand
    close = get_close_matches(n, list(by_norm), n=1, cutoff=0.8)
    return by_norm[close[0]] if close else None


def load_aliases() -> dict[str, str]:
    return read_json("data/team_aliases.json", {})
