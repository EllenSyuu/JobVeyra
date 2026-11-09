"""Workable accounts (public widget API, no key).

GET https://apply.workable.com/api/v1/widget/accounts/{board}?details=true
spec: ``board`` (required), ``employer``, ``details`` (default true: include descriptions).
"""
from __future__ import annotations

from urllib.parse import quote

from ..models import Posting
from .base import Source, clean_title, employment_of, html_to_text, iso_date, join, register, require


@register
class Workable(Source):
    name = "workable"

    def fetch(self, spec: dict, http) -> list[Posting]:
        board = str(require(spec, "board"))
        url = f"https://apply.workable.com/api/v1/widget/accounts/{quote(board)}"
        if spec.get("details", True):
            url += "?details=true"
        d = http.get_json(url)
        employer = spec.get("employer") or d.get("name") or board
        out = []
        for j in d.get("jobs") or []:
            locs = [join(x.get("city"), x.get("region"), x.get("country"))
                    for x in j.get("locations") or [] if x and not x.get("hidden")]
            loc = join(*locs, sep="; ") or join(j.get("city"), j.get("state"), j.get("country"))
            tele = j.get("telecommuting")
            out.append(Posting(
                source=self.name,
                employer=employer,
                title=clean_title(j.get("title")),
                url=j.get("url") or j.get("shortlink") or "",
                apply_url=j.get("application_url") or "",
                req_id=str(j.get("shortcode") or ""),
                location=loc,
                remote=bool(tele) if tele is not None else None,
                posted=iso_date(j.get("published_on") or j.get("created_at")),
                employment=employment_of(j.get("employment_type")),
                text=html_to_text(j.get("description")),
                extra={"board": board, "department": j.get("department", "") or "", "code": j.get("code", "") or "",
                       "experience": j.get("experience", "") or "", "function": j.get("function", "") or "",
                       "industry": j.get("industry", "") or ""},
            ))
        return out
