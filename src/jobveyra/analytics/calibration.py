"""Does the fit score predict employer interest?

Over submitted jobs with a fit score: positive-response rate per fit bucket, the Brier score of
fit/100 read as a probability of a positive response (screen, interview, assessment, offer,
hired), the AUC (Mann-Whitney), and whether the bucket rates rise with fit. A threshold
recommendation is made only from ``MIN_N`` outcomes up; before that the answer is
"not enough outcomes yet".
"""
from __future__ import annotations

from .. import outcomes as oc

BUCKETS = (("<45", None, 45), ("45-54", 45, 55), ("55-64", 55, 65), ("65-74", 65, 75), ("75+", 75, None))
MIN_N = 30
NOT_ENOUGH = "not enough outcomes yet"


def _bucket(fit: float) -> str:
    for label, lo, hi in BUCKETS:
        if (lo is None or fit >= lo) and (hi is None or fit < hi):
            return label
    return BUCKETS[-1][0]


def auc(scores: list[float], labels: list[int]) -> float | None:
    """Probability a random positive outranks a random negative (ties count half)."""
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    # rank-sum form, average ranks for ties: O(n log n)
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    r_pos = sum(r for r, y in zip(ranks, labels) if y)
    u = r_pos - len(pos) * (len(pos) + 1) / 2
    return u / (len(pos) * len(neg))


def calibrate(jobs: list[dict], outcomes: list[dict], *, exclude_below: int = 45, min_n: int = MIN_N) -> dict:
    recs = oc.by_job(outcomes)
    pts = []
    for j in jobs:
        if j.get("state") != "submitted" or j.get("fit") in (None, ""):
            continue
        try:
            fit = float(j["fit"])
        except (TypeError, ValueError):
            continue
        pts.append((fit, 1 if oc.reached(recs.get(j["id"], []), oc.POSITIVE) else 0))
    n = len(pts)
    buckets = []
    for label, lo, hi in BUCKETS:
        ys = [y for f, y in pts if _bucket(f) == label]
        buckets.append({"bucket": label, "low": lo, "high": hi, "n": len(ys), "positive": sum(ys),
                        "rate": round(sum(ys) / len(ys), 4) if ys else None})
    rates = [b["rate"] for b in buckets if b["n"]]
    monotonic = all(a <= b for a, b in zip(rates, rates[1:])) if len(rates) > 1 else None
    brier = round(sum((min(max(f / 100, 0), 1) - y) ** 2 for f, y in pts) / n, 4) if n else None
    a = auc([f for f, _ in pts], [y for _, y in pts])
    overall = sum(y for _, y in pts) / n if n else None
    return {"n": n, "positive": sum(y for _, y in pts), "overall_rate": round(overall, 4) if overall is not None else None,
            "buckets": buckets, "brier": brier, "auc": round(a, 4) if a is not None else None,
            "monotonic": monotonic,
            "recommendation": _recommend(buckets, overall, a, monotonic, n, exclude_below, min_n)}


def _recommend(buckets, overall, a, monotonic, n, exclude_below, min_n) -> str:
    if n < min_n:
        return f"{NOT_ENOUGH} ({n} of {min_n} scored submissions with outcomes)"
    notes = []
    # weak low buckets: consecutive from the bottom, each with >= 5 jobs and under half the overall rate
    raise_to = None
    for b in buckets:
        if not b["n"]:
            continue
        if b["n"] >= 5 and overall and b["rate"] is not None and b["rate"] < overall / 2 and b["high"] is not None:
            raise_to = b["high"]
        else:
            break
    if raise_to is not None and raise_to > exclude_below:
        notes.append(f"raise policy.exclude_below from {exclude_below} to {raise_to}: jobs scored below {raise_to} "
                     f"respond at less than half the overall rate")
    if a is not None and a < 0.55:
        notes.append(f"fit barely separates positive responses (AUC {a:.2f}); review the rubric weights")
    if monotonic is False:
        notes.append("response rate does not rise steadily with fit; check the buckets that break the order")
    if not notes:
        notes.append("fit tracks responses; keep the current thresholds")
    return "; ".join(notes)


calibration = calibrate
