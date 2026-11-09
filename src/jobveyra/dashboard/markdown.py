"""A deliberately small Markdown renderer for evaluation reports.

Supports headings, pipe tables, bullet and numbered lists, fenced code, horizontal rules,
paragraphs, and inline bold, code and links. Everything is HTML-escaped first; raw HTML in the
source is shown as text. Links are kept only for http, https and mailto URLs.
"""
from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

_INLINE = re.compile(
    r"`([^`\n]+)`"                                  # code
    r"|\[([^\]\n]+)\]\(([^()\s]+)\)"                # [label](url)
    r"|\*\*(.+?)\*\*"                               # bold
    r"|(https?://[^\s<>()\[\]`\"']+)"               # bare URL
)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_UL = re.compile(r"^[-*+]\s+(.*)$")
_OL = re.compile(r"^\d{1,9}[.)]\s+(.*)$")
_SEP = re.compile(r"^\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")
_HR = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
SCHEMES = ("http", "https", "mailto")


def _e(s: str) -> str:
    return html.escape(s, quote=True)


def safe_url(url: str) -> str:
    """The URL when its scheme is http, https or mailto; '' otherwise."""
    u = (url or "").strip()
    if not u or re.search(r"[\x00-\x20\x7f]", u):
        return ""
    try:
        scheme = urlsplit(u).scheme.lower()
    except ValueError:
        return ""
    return u if scheme in SCHEMES else ""


def inline(text: str, *, links: bool = True) -> str:
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        out.append(_e(text[pos:m.start()]))
        code, label, url, bold, bare = m.groups()
        if code is not None:
            out.append(f"<code>{_e(code)}</code>")
        elif label is not None:
            u = safe_url(url) if links else ""
            if u:
                out.append(f'<a href="{_e(u)}" rel="noopener noreferrer">{inline(label, links=False)}</a>')
            else:
                out.append(inline(label, links=False))
        elif bold is not None:
            out.append(f"<strong>{inline(bold, links=links)}</strong>")
        else:
            core = bare.rstrip(".,;:!?")
            tail = bare[len(core):]
            u = safe_url(core) if links else ""
            out.append(f'<a href="{_e(u)}" rel="noopener noreferrer">{_e(core)}</a>' if u else _e(core))
            out.append(_e(tail))
        pos = m.end()
    out.append(_e(text[pos:]))
    return "".join(out)


def _cells(row: str) -> list[str]:
    s = row.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    parts = re.split(r"(?<!\\)\|", s)
    return [p.strip().replace("\\|", "|") for p in parts]


def _table(header: str, sep: str, body: list[str]) -> str:
    heads = _cells(header)
    aligns = []
    for c in _cells(sep):
        c = c.strip()
        aligns.append("num" if c.endswith(":") and not c.startswith(":") else
                      "center" if c.startswith(":") and c.endswith(":") else "")
    def cls(i):
        a = aligns[i] if i < len(aligns) else ""
        return f' class="{a}"' if a else ""
    out = ['<div class="table-wrap"><table class="md-table"><thead><tr>']
    out += [f'<th scope="col"{cls(i)}>{inline(h)}</th>' for i, h in enumerate(heads)]
    out.append("</tr></thead><tbody>")
    for row in body:
        cells = _cells(row)
        cells += [""] * (len(heads) - len(cells))
        out.append("<tr>" + "".join(f"<td{cls(i)}>{inline(c)}</td>" for i, c in enumerate(cells[:len(heads)]))
                   + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def render(md: str, *, base_level: int = 2) -> str:
    """Markdown -> safe HTML. ``base_level`` is the HTML level used for a level-1 heading."""
    lines = (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []

    def flush():
        if para:
            out.append("<p>" + "<br>".join(inline(x) for x in para) + "</p>")
            para.clear()

    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s:
            flush()
            i += 1
            continue
        if s.startswith("```"):
            flush()
            body = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            out.append(f"<pre><code>{_e(chr(10).join(body))}</code></pre>")
            i += 1
            continue
        m = _HEADING.match(s)
        if m:
            flush()
            level = min(6, len(m.group(1)) + base_level - 1)
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue
        if _HR.match(s):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if s.startswith("|") and i + 1 < n and _SEP.match(lines[i + 1].strip()) and "-" in lines[i + 1]:
            flush()
            header, sep = s, lines[i + 1].strip()
            i += 2
            body = []
            while i < n and lines[i].strip().startswith("|"):
                body.append(lines[i].strip())
                i += 1
            out.append(_table(header, sep, body))
            continue
        for rx, tag in ((_UL, "ul"), (_OL, "ol")):
            if rx.match(s):
                flush()
                items = []
                while i < n and rx.match(lines[i].strip()):
                    items.append(rx.match(lines[i].strip()).group(1))
                    i += 1
                out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
                break
        else:
            para.append(s)
            i += 1
    flush()
    return "\n".join(out)
