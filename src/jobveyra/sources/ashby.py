"""Ashby job boards (public Posting API, no key).

GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true
spec: ``board`` (required), ``employer``.
"""
from __future__ import annotations

from urllib.parse import quote

from ..models import Posting
from .base import Source, clean_title, employment_of, html_to_text, iso_date, join, num, register, remote_hint, require


@register
class Ashby(Source):
    name = "ashby"

    def fetch(self, spec: dict, http) -> list[Posting]:
        board = str(require(spec, "board"))
        d = http.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{quote(board)}?includeCompensation=true")
        out = []
        for j in d.get("jobs") or []:
            if j.get("isListed") is False:
                continue
            addr = ((j.get("address") or {}).get("postalAddress") or {})
            secondary = [s.get("location", "") for s in j.get("secondaryLocations") or [] if s]
            loc = join(j.get("location"), *secondary, sep="; ") or join(
                addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry"))
            wt = (j.get("workplaceType") or "").lower()
            remote = True if j.get("isRemote") or wt == "remote" else False if wt in ("onsite", "hybrid") \
                else remote_hint(loc)
            comp = j.get("compensation") or {}
            sal = next((c for c in comp.get("summaryComponents") or []
                        if (c.get("compensationType") or "").lower() == "salary"), {}) or {}
            url = j.get("jobUrl") or ""
            out.append(Posting(
                source=self.name,
                employer=spec.get("employer") or board,
                title=clean_title(j.get("title")),
                url=url,
                apply_url=j.get("applyUrl") or "",
                req_id=str(j.get("id") or url.rstrip("/").rsplit("/", 1)[-1]),
                location=loc,
                remote=remote,
                posted=iso_date(j.get("publishedAt")),
                employment=employment_of(j.get("employmentType")),
                salary_min=num(sal.get("minValue")),
                salary_max=num(sal.get("maxValue")),
                salary_currency=sal.get("currencyCode", "") or "",
                text=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
                extra={"board": board, "department": j.get("department", ""), "team": j.get("team", ""),
                       "salary_interval": sal.get("interval", ""),
                       "compensation_summary": comp.get("compensationTierSummary", "") or ""},
            ))
        return out
