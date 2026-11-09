"""Jobs from a LinkedIn job-alert email the user saved (``.eml``, ``.html`` or ``.txt``).

This adapter only reads local files. It never contacts LinkedIn: the posting URL is rebuilt as
``https://www.linkedin.com/jobs/view/<id>/`` for the user to open, and the text stays empty
until another step (for example the employer's own posting) supplies it.

spec: ``path`` (a file or a folder of saved alerts; relative paths resolve against the
workspace when discovery passes ``_workspace``).
"""
from __future__ import annotations

import email
import email.policy
import html
import re
from pathlib import Path

from ..models import Posting
from .base import Source, SourceError, clean_title, fold, register, remote_hint, require

JOB_LINK = re.compile(r"https?://(?:[a-z]{2,3}\.)?(?:www\.|jobs\.)?linkedin\.com/(?:comm/)?jobs/view/"
                      r"(?:[a-z0-9-]*?-)?(\d{6,})[^\s\"'<>)]*", re.I)
MARK = "⟦{}⟧"
MARK_RX = re.compile("⟦(\\d+)⟧")
NOISE = re.compile(r"^(?:view job:?|view|apply(?: now)?|easy apply|actively (?:hiring|recruiting)|promoted|new|"
                   r"be an early applicant|.*\bconnections?\b.*|.*\balumni?\b.*|.*\bapplicants?\b.*|"
                   r".*\b(?:day|days|week|weeks|hour|hours|minute|minutes|month|months) ago\b.*|"
                   r"see all jobs.*|.*job alert.*|.*jobs? match.*|unsubscribe.*|manage .*|help.*|"
                   r"linkedin.*|top job pick.*|\W*)$", re.I)
SEPARATOR = re.compile(r"^\s*[-_=*]{5,}\s*$")
SUFFIXES = (".eml", ".html", ".htm", ".txt", ".mht")


def _read(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    head = raw[:4096].decode("utf-8", errors="replace")
    if path.suffix.lower() == ".eml" or re.search(r"^(?:From|Subject|Content-Type|MIME-Version):", head, re.M):
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        part = msg.get_body(preferencelist=("html", "plain"))
        if part is not None:
            body = part.get_content()
            return body, part.get_content_type() == "text/html"
    text = raw.decode("utf-8", errors="replace")
    return text, bool(re.search(r"<\s*(?:html|body|table|a\s)", text, re.I))


def _lines(body: str, is_html: bool) -> list[str]:
    if is_html:
        def anchor(m: re.Match) -> str:
            href = html.unescape(m.group(1))
            inner = re.sub(r"<[^>]+>", " ", m.group(2))
            jl = JOB_LINK.search(href)
            return f"\n{MARK.format(jl.group(1))} {inner}\n" if jl else inner
        body = re.sub(r"<\s*(script|style|head)\b.*?<\s*/\s*\1\s*>", " ", body, flags=re.S | re.I)
        body = re.sub(r"<a\b[^>]*?href\s*=\s*[\"']([^\"']*)[\"'][^>]*>(.*?)</a\s*>", anchor, body, flags=re.S | re.I)
        body = re.sub(r"<\s*(?:br|/p|/div|/td|/tr|/table|/h\d|p|div|tr|li)\b[^>]*>", "\n", body, flags=re.I)
        body = html.unescape(re.sub(r"<[^>]+>", " ", body))
    else:
        body = JOB_LINK.sub(lambda m: MARK.format(m.group(1)), body)
    return [re.sub(r"\s+", " ", ln).strip() for ln in body.replace(" ", " ").split("\n")]


def _is_noise(line: str) -> bool:
    return bool(NOISE.match(line.strip()))


def _fields(lines: list[str]) -> tuple[str, str, str]:
    """(title, company, location) from the meaningful lines of one job card, in reading order."""
    lines = [ln for ln in lines if ln and not _is_noise(ln)]
    if not lines:
        return "", "", ""
    title, rest = lines[0], lines[1:]
    if " · " in title:                     # "Company · Location" came first: title is missing
        return "", *[x.strip() for x in title.split(" · ", 1)]  # type: ignore[return-value]
    if rest and " · " in rest[0]:
        company, location = (x.strip() for x in rest[0].split(" · ", 1))
        return title, company, location
    return title, rest[0] if rest else "", rest[1] if len(rest) > 1 else ""


def parse(body: str, is_html: bool) -> list[dict]:
    """Jobs in an alert body: dicts with id, title, company, location."""
    lines = _lines(body, is_html)
    marks = [(i, MARK_RX.search(ln).group(1)) for i, ln in enumerate(lines) if MARK_RX.search(ln)]
    jobs: dict[str, dict] = {}
    for n, (i, jid) in enumerate(marks):
        if is_html:
            # Cards read top-down after the first link: logo link, title link, "Company · Location".
            if any(j == jid for _, j in marks[:n]):
                continue
            end = next((k for k, j in marks[n + 1:] if j != jid), len(lines))
            seg = [MARK_RX.sub("", ln).strip() for ln in lines[i:end]]
        else:
            # Plain-text alerts list title, company and location above each "View job: <link>".
            start = marks[n - 1][0] + 1 if n else 0
            seg = [ln for ln in lines[start:i] if not SEPARATOR.match(ln)]
            for k in range(len(seg) - 1, -1, -1):        # keep only the block after the last blank line
                if not seg[k] and any(seg[k + 1:]):
                    seg = seg[k + 1:]
                    break
            inline = MARK_RX.sub("", lines[i]).strip()
            seg = [s for s in seg + [inline] if s and not _is_noise(s)][-3:]
        title, company, location = _fields(seg)
        if jid in jobs and jobs[jid]["title"]:
            continue
        jobs[jid] = {"id": jid, "title": title, "company": company, "location": location}
    return list(jobs.values())


def _files(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES)
    if path.is_file():
        return [path]
    raise SourceError(f"linkedin_alert: {path} does not exist")


@register
class LinkedInAlert(Source):
    name = "linkedin_alert"

    def fetch(self, spec: dict, http=None) -> list[Posting]:
        path = Path(str(require(spec, "path"))).expanduser()
        if not path.is_absolute() and spec.get("_workspace"):
            path = Path(spec["_workspace"]) / path
        out: dict[str, Posting] = {}
        for f in _files(path):
            body, is_html = _read(f)
            for j in parse(body, is_html):
                if j["id"] in out or not j["title"]:
                    continue
                loc = j["location"]
                remote = remote_hint(loc)
                loc = re.sub(r"\s*\((?:remote|hybrid|on-site|onsite)\)\s*$", "", loc, flags=re.I).strip()
                if fold(loc) in ("remote", "hybrid", "on site"):
                    loc = ""
                out[j["id"]] = Posting(
                    source=self.name,
                    employer=j["company"],
                    title=clean_title(j["title"]),
                    url=f"https://www.linkedin.com/jobs/view/{j['id']}/",
                    req_id=j["id"],
                    location=loc,
                    remote=remote,
                    extra={"alert_file": f.name},
                )
        return list(out.values())
