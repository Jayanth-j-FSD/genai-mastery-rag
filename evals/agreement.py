"""How well does the judge agree with a human? (Judge validation, mentor check #3.)

"the judge says 90% of answers pass" means nothing until you know the judge
agrees with a person. So a human grades a sample of answers blind, the judge grades the same ones,
and these numbers say how often they agree.

  percent agreement   how often they gave the same verdict. Easy to read, but it flatters a judge
                      when almost everything passes: always answering "pass" scores 95% on a set
                      that is 95% good answers.
  Cohen's kappa       agreement corrected for that luck. 0 means no better than chance, 1 is
                      perfect. This is the number to trust.

Both verdicts are "pass" or "fail". The positive class is "pass".
"""

# A widely used rule of thumb for reading kappa (Landis and Koch, 1977), not a law.
_KAPPA_BANDS = [(0.0, "worse than chance"), (0.20, "slight"), (0.40, "fair"),
                (0.60, "moderate"), (0.80, "substantial"), (1.01, "almost perfect")]

DEFAULT_MIN_AGREEMENT = 0.80
DEFAULT_MIN_KAPPA = 0.60


def kappa_label(kappa):
    if kappa is None:
        return "undefined (all verdicts identical)"
    for upper, label in _KAPPA_BANDS:
        if kappa < upper:
            return label
    return "almost perfect"


def agreement_stats(pairs):
    """pairs: [(human, judge)], each "pass" or "fail". Returns the counts and both statistics."""
    both_pass = sum(1 for human, judge in pairs if human == "pass" and judge == "pass")
    both_fail = sum(1 for human, judge in pairs if human == "fail" and judge == "fail")
    judge_harsh = sum(1 for human, judge in pairs if human == "pass" and judge == "fail")   # human passed it, judge failed it
    judge_lenient = sum(1 for human, judge in pairs if human == "fail" and judge == "pass")  # human failed it, judge passed it
    n = len(pairs)
    stats = {"n": n, "both_pass": both_pass, "both_fail": both_fail,
             "judge_harsh": judge_harsh, "judge_lenient": judge_lenient,
             "percent": None, "kappa": None, "human_pass_rate": None, "judge_pass_rate": None}
    if n == 0:
        return stats
    observed = (both_pass + both_fail) / n
    human_pass = (both_pass + judge_harsh) / n
    judge_pass = (both_pass + judge_lenient) / n
    expected = human_pass * judge_pass + (1 - human_pass) * (1 - judge_pass)
    stats.update(percent=observed, human_pass_rate=human_pass, judge_pass_rate=judge_pass)
    if expected < 1.0:                      # when both always say the same thing kappa is 0/0
        stats["kappa"] = (observed - expected) / (1 - expected)
    return stats


def is_trustworthy(stats, min_agreement=DEFAULT_MIN_AGREEMENT, min_kappa=DEFAULT_MIN_KAPPA):
    """True only if the judge clears BOTH bars. Thresholds are conventions: say yours out loud."""
    if not stats["n"] or stats["percent"] is None:
        return False
    if stats["kappa"] is None:              # no variation to measure: agreement alone cannot show skill
        return False
    return stats["percent"] >= min_agreement and stats["kappa"] >= min_kappa
