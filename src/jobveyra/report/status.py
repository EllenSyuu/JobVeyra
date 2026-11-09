"""Markdown status block for a README or dashboard, and in-place replacement between markers."""
from __future__ import annotations

from pathlib import Path

from .newsletter import _day, _plural, coming_lines, needs_lines

START = "<!-- JOBVEYRA:STATUS:START -->"
END = "<!-- JOBVEYRA:STATUS:END -->"


def _cap(items: list[str], limit: int | None, more_link: str) -> list[str]:
    if limit is None or len(items) <= limit:
        return [f"- {x}" for x in items]
    rest = len(items) - limit
    tail = f"[and {rest} more]({more_link})" if more_link else f"and {rest} more"
    return [f"- {x}" for x in items[:limit]] + [f"- {tail}"]


def _cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def markdown(digest: dict, chart_light: str, chart_dark: str, limit: int | None = None, more_link: str = "") -> str:
    dg, t = digest, digest["totals"]
    L = []
    if chart_light:
        alt = f"Applications submitted per day over the last {len(dg.get('series', []))} days"
        src_dark = f'<source media="(prefers-color-scheme: dark)" srcset="{chart_dark}">' if chart_dark else ""
        L += [f'<picture>{src_dark}<img src="{chart_light}" alt="{alt}" width="600"></picture>', ""]
    L.append(f"**{_day(dg['date'])}** · {t['submitted']} submitted · {dg['last7']} in the last 7 days · "
             f"{t['replies']} {'reply' if t['replies'] == 1 else 'replies'} ({t['reply_rate']}%) · "
             f"{_plural(t['interviews'], 'interview')} · {_plural(t['offers'], 'offer')}")
    if dg.get("by_track"):
        L += ["", "| Track | Submitted | Replies | Avg fit |", "| --- | ---: | ---: | ---: |"]
        L += [f"| {_cell(r['label'])} | {r['sent']} | {r['replies']} | {'' if r['avg_fit'] is None else r['avg_fit']} |"
              for r in dg["by_track"]]
    for head, items in (("Needs attention", needs_lines(dg)), ("Coming up", coming_lines(dg))):
        L += ["", f"### {head}", ""]
        L += _cap(items, limit, more_link) if items else ["- Nothing right now."]
    return "\n".join(L) + "\n"


def update_block(path, block: str, start: str = START, end: str = END) -> bool:
    """Replace only the text between ``start`` and ``end`` in ``path``. Returns True when the file
    changed; no-op (False) when the file or either marker is missing."""
    p = Path(path)
    if not p.is_file():
        return False
    text = p.read_text(encoding="utf-8")
    i = text.find(start)
    j = text.find(end, i + len(start)) if i >= 0 else -1
    if i < 0 or j < 0:
        return False
    new = text[: i + len(start)] + "\n" + block.strip("\n") + "\n" + text[j:]
    if new == text:
        return False
    p.write_text(new, encoding="utf-8")
    return True
