"""Remotive remote jobs (public API; Remotive asks callers to link back and to fetch sparingly,
a few times a day at most).

GET https://remotive.com/api/remote-jobs?category=...&search=...&limit=...
spec: ``category``, ``search``, ``limit``, ``currency`` (assumed for a bare "$" salary).
"""
from __future__ import annotations

from urllib.parse import urlencode

from ..models import Posting
from .base import Source, clean_title, employment_of, html_to_text, iso_date, money_range, register

API = "https://remotive.com/api/remote-jobs"


@register
class Remotive(Source):
    name = "remotive"

    def fetch(self, spec: dict, http) -> list[Posting]:
        q = {k: spec[k] for k in ("category", "search", "limit") if spec.get(k) not in (None, "")}
        d = http.get_json(API + (f"?{urlencode(q)}" if q else ""))
        out = []
        for j in d.get("jobs") or []:
            sal = money_range(j.get("salary") or "", spec.get("currency", ""))
            out.append(Posting(
                source=self.name,
                employer=j.get("company_name") or "",
                title=clean_title(j.get("title")),
                url=j.get("url") or "",
                req_id=str(j.get("id") or ""),
                location=j.get("candidate_required_location") or "",
                remote=True,
                posted=iso_date(j.get("publication_date")),
                employment=employment_of(j.get("job_type")),
                salary_min=sal[0] if sal else None,
                salary_max=sal[1] if sal else None,
                salary_currency=sal[2] if sal else "",
                text=html_to_text(j.get("description")),
                extra={"category": j.get("category", ""), "tags": j.get("tags") or [],
                       "salary_text": j.get("salary", "") or ""},
            ))
        return out
