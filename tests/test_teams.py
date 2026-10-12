from kairos.teams import match_team, normalize

FD = ["Man United", "Man City", "Brighton", "Nott'm Forest", "Inter", "Milan", "St. Gallen", "Young Boys", "Servette", "Ein Frankfurt"]


def test_normalize_strips_accents_and_club_tokens():
    assert normalize("FC Zürich") == "zurich"
    assert normalize("1. FC Köln") == "koln"


def test_alias_wins():
    assert match_team("Manchester United", FD, {"Manchester United": "Man United"}) == "Man United"


def test_exact_after_normalisation():
    assert match_team("Servette FC", FD, {}) == "Servette"


def test_prefix_match():
    assert match_team("BSC Young Boys", FD, {}) == "Young Boys"


def test_fuzzy_match():
    assert match_team("St Gallen", FD, {}) == "St. Gallen"


def test_unknown_returns_none():
    assert match_team("Real Madrid", FD, {}) is None


def test_alias_to_missing_candidate_falls_back_to_prefix():
    assert match_team("Brighton and Hove Albion", FD, {"Brighton and Hove Albion": "Brighton & HA"}) == "Brighton"
    assert match_team("Brighton and Hove Albion", FD, {}) == "Brighton"


def test_fuzzy_only_transposed_letters():
    assert match_team("Yound Boys", FD, {}) == "Young Boys"


def test_fuzzy_only_dropped_letter():
    assert match_team("Servete", FD, {}) == "Servette"


def test_fuzzy_only_abbreviated_name():
    assert match_team("Nottingham Forest", FD, {}) == "Nott'm Forest"


def test_trailing_word_resolves_to_club():
    # Not prefix-isolated: fuzzy (ratio exactly 0.8) also matches this input; see report.
    assert match_team("Young Boys Bern", FD, {}) == "Young Boys"


def test_prefix_only_city_suffix():
    assert match_team("Servette Geneve", FD, {}) == "Servette"
