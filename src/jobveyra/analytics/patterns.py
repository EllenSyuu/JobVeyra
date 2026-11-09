"""Response rate by source, portal, track, lane, seniority and flagship, with Wilson intervals.

A group gets a ``signal`` of ``above`` or ``below`` only when it has at least ``MIN_N``
submissions and its 95 % interval excludes the overall rate; everything else is
``insufficient``. Small samples are reported, never read as patterns.
"""
from __future__ import annotations

import math

from .. import outcomes as oc

MIN_N = 8
Z95 = 1.959964
DIMENSIONS = (("source", "source"), ("portal", "portal"), ("track", "family"), ("lane", "lane"),
              ("seniority", "seniority"), ("flagship", "flagship"))


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials; (0, 1) when n is 0."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def _value(job: dict, field: str) -> str:
    v = job.get(field)
    if field == "flagship":
        try:
            return "yes" if int(float(v or 0)) else "no"
        except (TypeError, ValueError):
            return "yes" if v else "no"
    return str(v) if v not in (None, "") else "(none)"


def patterns(jobs: list[dict], outcomes: list[dict], *, min_n: int = MIN_N) -> list[dict]:
    """One row per (dimension, value) over submitted jobs, strongest evidence first."""
    recs = oc.by_job(outcomes)
    sub = [j for j in jobs if j.get("state") == "submitted"]
    if not sub:
        return []
    replied = {j["id"]: oc.reached(recs.get(j["id"], []), oc.REPLY) for j in sub}
    overall = sum(replied.values()) / len(sub)
    rows = []
    for dim, field in DIMENSIONS:
        if field == "seniority" and not any(j.get("seniority") for j in sub):
            continue
        groups: dict[str, list[dict]] = {}
        for j in sub:
            groups.setdefault(_value(j, field), []).append(j)
        for value, js in groups.items():
            n, k = len(js), sum(1 for j in js if replied[j["id"]])
            lo, hi = wilson(k, n)
            signal = "insufficient"
            if n >= min_n and lo > overall:
                signal = "above"
            elif n >= min_n and hi < overall:
                signal = "below"
            half = (hi - lo) / 2 or 1.0
            rows.append({"dimension": dim, "value": value, "n": n, "replied": k,
                         "rate": round(k / n, 4), "low": round(lo, 4), "high": round(hi, 4),
                         "overall": round(overall, 4), "signal": signal,
                         "evidence": round(abs(k / n - overall) / half, 3)})
    rows.sort(key=lambda r: (r["signal"] == "insufficient", -r["evidence"], -r["n"], r["dimension"], r["value"]))
    return rows
