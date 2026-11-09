"""Any careers page that embeds schema.org ``JobPosting`` objects as JSON-LD.

Reads every ``<script type="application/ld+json">`` block, including ``@graph`` containers,
top-level lists and ``ItemList`` wrappers, and turns each JobPosting into a Posting.
spec: ``urls`` (list) or ``url``; ``employer`` (fallback when the page names no organisation).
"""
from __future__ import annotations

import html
import json
import re
from typing import Any, Iterator
from urllib.parse import urljoin, urlsplit

from ..models import Posting
from .base import (Source, SourceError, as_list, clean_title, employment_of, html_to_text, iso_date, join, num,
                   register)
from .http import HttpError

_SCRIPT = re.compile(r"<script\b[^>]*type\s*=\s*[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script\s*>", re.I | re.S)


def blocks(page: str) -> list[Any]:
    """Every JSON-LD block on an HTML page that parses as JSON."""
    out = []
    for raw in _SCRIPT.findall(page or ""):
        raw = raw.strip()
        raw = re.sub(r"^\s*(?:<!--|<!\[CDATA\[)|(?:-->|\]\]>)\s*$", "", raw).strip()
        for candidate in (raw, html.unescape(raw), re.sub(r",\s*([}\]])", r"\1", raw)):
            try:
                out.append(json.loads(candidate, strict=False))
                break
            except json.JSONDecodeError:
                continue
    return out


def _types(o: dict) -> list[str]:
    return [str(t).rsplit("/", 1)[-1].lower() for t in as_list(o.get("@type"))]


def job_postings(node: Any) -> Iterator[dict]:
    """Walk JSON-LD (dicts, lists, @graph, ItemList/ListItem) and yield every JobPosting."""
    if isinstance(node, list):
        for x in node:
            yield from job_postings(x)
    elif isinstance(node, dict):
        if "jobposting" in _types(node):
            yield node
            return
        for k in ("@graph", "itemListElement", "item", "mainEntity", "hasPart"):
            if k in node:
                yield from job_postings(node[k])


def _text(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("name") or v.get("value") or v.get("@value") or "")
    if isinstance(v, list):
        return join(*[_text(x) for x in v])
    return str(v or "")


def _location(jp: dict) -> str:
    out = []
    for loc in as_list(jp.get("jobLocation")):
        if isinstance(loc, str):
            out.append(loc)
            continue
        addr = loc.get("address") if isinstance(loc, dict) else None
        if isinstance(addr, str):
            out.append(addr)
        elif isinstance(addr, dict):
            out.append(join(_text(addr.get("addressLocality")), _text(addr.get("addressRegion")),
                            _text(addr.get("addressCountry"))))
        elif isinstance(loc, dict) and loc.get("name"):
            out.append(str(loc["name"]))
    if not any(out):
        out = [join(*[_text(x) for x in as_list(jp.get("applicantLocationRequirements"))])]
    return join(*out, sep="; ")


def to_posting(jp: dict, page_url: str, fallback_employer: str = "") -> Posting:
    org = jp.get("hiringOrganization")
    employer = _text(org) if org else ""
    ident = jp.get("identifier")
    if isinstance(ident, dict):
        req = str(ident.get("value") or ident.get("@value") or ident.get("name") or "")
    else:
        req = _text(ident) if ident else ""
    sal = jp.get("baseSalary") or jp.get("estimatedSalary") or {}
    sal = sal[0] if isinstance(sal, list) and sal else sal
    val = sal.get("value") if isinstance(sal, dict) else None
    lo = hi = None
    unit = ""
    if isinstance(val, dict):
        lo, hi = num(val.get("minValue") or val.get("value")), num(val.get("maxValue") or val.get("value"))
        unit = str(val.get("unitText") or "")
    elif val is not None:
        lo = hi = num(val)
    remote = True if "telecommute" in str(jp.get("jobLocationType", "")).lower() else None
    url = jp.get("url") or ""
    url = urljoin(page_url, url) if url else page_url
    return Posting(
        source="jsonld",
        employer=employer or fallback_employer or urlsplit(page_url).netloc.replace("www.", ""),
        title=clean_title(jp.get("title") or jp.get("name")),
        url=url,
        apply_url=url if jp.get("directApply") is True else "",
        req_id=req,
        location=_location(jp),
        remote=remote,
        posted=iso_date(jp.get("datePosted")),
        deadline=iso_date(jp.get("validThrough")),
        employment=employment_of(jp.get("employmentType")),
        salary_min=lo,
        salary_max=hi,
        salary_currency=str((sal or {}).get("currency", "") if isinstance(sal, dict) else ""),
        lang=str(jp.get("inLanguage") or "")[:2].lower(),
        text=html_to_text(str(jp.get("description") or "")),
        extra={"page": page_url, "salary_unit": unit, "industry": _text(jp.get("industry"))},
    )


@register
class JsonLd(Source):
    name = "jsonld"

    def fetch(self, spec: dict, http) -> list[Posting]:
        urls = as_list(spec.get("urls")) or as_list(spec.get("url"))
        if not urls:
            raise SourceError("source 'jsonld' needs 'urls'")
        out: list[Posting] = []
        errors: list[str] = []
        for page_url in urls:
            try:
                page = http.get_text(page_url)
            except HttpError as e:
                errors.append(str(e))
                continue
            for b in blocks(page):
                for jp in job_postings(b):
                    out.append(to_posting(jp, page_url, spec.get("employer", "")))
        if errors and len(errors) == len(urls):
            raise SourceError("; ".join(errors))
        return out
