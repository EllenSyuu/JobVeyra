"""Offer negotiation script (Markdown).

Uses only what the caller passes: the offer, any competing offers, and the salary floor in the
config. It does not invent market data; where market numbers would help, it says where to look.
"""
from __future__ import annotations

COUNTER_LOW, COUNTER_HIGH = 0.08, 0.15
LEVERS = (
    ("Signing bonus", "a one-time signing bonus to bridge the gap in base pay"),
    ("Start date", "a start date that works for both sides, including notice and any move"),
    ("Work location", "the number of remote or hybrid days, written into the offer"),
    ("Title and level", "the level and title, which set the next salary band"),
    ("Salary review", "a written compensation review at six months against agreed goals"),
    ("Time off", "additional paid time off"),
    ("Learning budget", "a budget for courses, certifications or conferences"),
    ("Relocation", "relocation support if the role needs a move"),
)


def _money(x: float, cur: str) -> str:
    return f"{cur + ' ' if cur else ''}{x:,.0f}"


def _round(x: float) -> float:
    step = 500 if x < 50_000 else 1000
    return round(x / step) * step


def script(offer: dict, cfg, *, counter_low: float = COUNTER_LOW, counter_high: float = COUNTER_HIGH,
           name: str = "") -> str:
    """offer: ``{base, currency, bonus, equity, benefits, location, competing: [...]}``. Competing
    offers may be dicts ``{employer, base, currency, deadline}`` or plain strings."""
    if not 0 <= counter_low <= counter_high:
        raise ValueError("need 0 <= counter_low <= counter_high")
    cur = offer.get("currency") or cfg.focus.salary_currency or ""
    base = float(offer["base"]) if offer.get("base") not in (None, "") else None
    employer = offer.get("employer") or "the company"
    title = offer.get("title") or "the role"
    floor = float(cfg.focus.salary_floor or 0)
    floor_cur = cfg.focus.salary_currency or cur

    L = [f"# Negotiation script: {title} at {employer}", "", "## The offer", ""]
    L.append(f"- Base: {_money(base, cur) if base is not None else 'not stated yet'}")
    for k, label in (("bonus", "Bonus"), ("equity", "Equity"), ("benefits", "Benefits"), ("location", "Location")):
        v = offer.get(k)
        if v not in (None, "", [], {}):
            L.append(f"- {label}: {', '.join(map(str, v)) if isinstance(v, (list, tuple)) else v}")

    L += ["", "## Market framing", ""]
    if base is not None and floor and (not floor_cur or floor_cur == cur):
        diff = (base - floor) / floor
        where = "above" if diff >= 0 else "below"
        L.append(f"- Your floor is {_money(floor, floor_cur)}. The offer is {abs(diff):.0%} {where} it.")
        if diff < 0:
            L.append("- An offer below your floor is the main point to resolve before anything else.")
    elif floor:
        L.append(f"- Your floor is {_money(floor, floor_cur)}; the offer is in {cur or 'another currency'}, "
                 "so convert it before comparing.")
    else:
        L.append("- No salary floor is set in jobveyra.yml (focus.salary_floor). Set one before the call.")
    L.append("- Check published salary bands, government wage data and the employer's own pay scales for "
             "this role and location, and note the sources you use. This script does not supply market numbers.")

    L += ["", "## Counter", ""]
    if base is not None:
        lo, hi = _round(base * (1 + counter_low)), _round(base * (1 + counter_high))
        if floor and floor_cur == cur and lo < floor:
            lo = _round(floor)
            hi = max(hi, lo)
        L.append(f"- Range to ask for: {_money(lo, cur)} to {_money(hi, cur)} "
                 f"({counter_low:.0%} to {counter_high:.0%} above the offered base).")
        L.append(f"- Open with the top of the range, {_money(hi, cur)}, and be ready to settle inside it.")
        L += ["", "Suggested wording:", "",
              f"> Thank you for the offer. I am excited about {title} and about joining {employer}. "
              f"Based on the scope of the role and what I bring to it, I was hoping for a base closer to "
              f"{_money(hi, cur)}. Is there flexibility there?"]
    else:
        L.append("- Ask for the base salary and its band in writing before you counter.")

    comp = offer.get("competing") or []
    L += ["", "## Competing offers", ""]
    if not comp:
        L.append("- None. Do not imply one; talk about the role's scope and your fit instead.")
    for c in comp:
        if isinstance(c, dict):
            who = c.get("employer") or "another employer"
            amt = _money(float(c["base"]), c.get("currency") or cur) if c.get("base") not in (None, "") else ""
            dl = f", with a deadline of {c['deadline']}" if c.get("deadline") else ""
            L.append(f"- {who}{': ' + amt if amt else ''}{dl}.")
            L.append(f"  > I have another offer{' at ' + amt if amt else ''}{dl}. {employer} is my first choice, "
                     "and I would like to find a way to make this work.")
        else:
            L.append(f"- {c}")
    if comp:
        L.append("- Mention only offers you actually hold, and share figures only if you are comfortable doing so.")

    L += ["", "## Other levers", ""]
    L += [f"- {label}: {text}." for label, text in LEVERS]

    L += ["", "## On the call", "",
          "- Thank them, restate your interest, then make one clear ask.",
          "- Pause after the number. Let them respond first.",
          "- Ask for the final offer in writing before you accept.",
          "", "## Note", "",
          "This script is a preparation aid. It is not legal or financial advice. For questions about "
          "contract terms, equity, tax or immigration, ask a qualified professional."]
    if name:
        L.insert(1, f"Prepared for {name}.")
    return "\n".join(L) + "\n"
