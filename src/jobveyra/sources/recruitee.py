"""Recruitee career sites (public Careers Site API, no key).

GET https://{board}.recruitee.com/api/offers/
spec: ``board`` (required, the company subdomain), ``employer``.
"""
from __future__ import annotations

import re

from ..models import Posting
from .base import Source, SourceError, clean_title, employment_of, html_to_text, iso_date, join, num, register, require


@register
class Recruitee(Source):
    name = "recruitee"

    def fetch(self, spec: dict, http) -> list[Posting]:
        board = str(require(spec, "board")).lower()
        if not re.fullmatch(r"[a-z0-9-]+", board):
            raise SourceError(f"recruitee: board {board!r} must be a subdomain (letters, digits, -)")
        d = http.get_json(f"https://{board}.recruitee.com/api/offers/")
        out = []
        for j in d.get("offers") or []:
            if j.get("status") not in (None, "", "published"):
                continue
            sal = j.get("salary") or {}
            remote = True if j.get("remote") else False if (j.get("hybrid") or j.get("on_site")) else None
            text = "\n\n".join(t for t in (html_to_text(j.get("description")),
                                           html_to_text(j.get("requirements"))) if t)
            out.append(Posting(
                source=self.name,
                employer=spec.get("employer") or j.get("company_name") or board,
                title=clean_title(j.get("title")),
                url=j.get("careers_url") or f"https://{board}.recruitee.com/o/{j.get('slug', '')}",
                apply_url=j.get("careers_apply_url") or "",
                req_id=str(j.get("id") or ""),
                location=j.get("location") or join(j.get("city"), j.get("state_name"), j.get("country")),
                remote=remote,
                posted=iso_date(j.get("published_at") or j.get("created_at")),
                deadline=iso_date(j.get("close_at")),
                employment=employment_of(j.get("employment_type_code")),
                salary_min=num(sal.get("min")),
                salary_max=num(sal.get("max")),
                salary_currency=(sal.get("currency") or "").upper(),
                text=text,
                extra={"board": board, "department": j.get("department", "") or "",
                       "salary_period": sal.get("period", "") or "",
                       "experience": j.get("experience_code", "") or ""},
            ))
        return out
