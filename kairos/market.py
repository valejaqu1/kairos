import penaltyblog as pb


def no_vig(median: dict[str, float]) -> list[float]:
    result = pb.implied.calculate_implied([median["1"], median["X"], median["2"]], method="power")
    return [round(float(p), 4) for p in result.probabilities]
