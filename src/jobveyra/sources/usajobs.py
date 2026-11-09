"""US federal jobs (USAJOBS Search API; free key from developer.usajobs.gov).

GET https://data.usajobs.gov/api/search?Keyword=...&LocationName=...&ResultsPerPage=N&Page=P
Headers: Authorization-Key from $USAJOBS_API_KEY, User-Agent = the email in $USAJOBS_EMAIL
(the API requires the email the key was issued to).
spec: ``keywords`` / ``keyword``, ``location``, ``remote`` (true adds RemoteIndicator=True),
``per_page`` (default 250), ``max_pages`` (default 4).
"""
from __future__ import annotations

import os
from urllib.parse import urlencode

from ..models import Posting
from .base import Source, SourceError, as_list, clean_title, employment_of, iso_date, join, num, register

API = "https://data.usajobs.gov/api/search"
CURRENCY = "USD"


@register
class USAJobs(Source):
    name = "usajobs"

    def fetch(self, spec: dict, http) -> list[Posting]:
        key, email = os.environ.get("USAJOBS_API_KEY", ""), os.environ.get("USAJOBS_EMAIL", "")
        if not key or not email:
            raise SourceError("usajobs needs the USAJOBS_API_KEY and USAJOBS_EMAIL environment variables "
                              "(request a free key at developer.usajobs.gov)")
        headers = {"Authorization-Key": key, "User-Agent": email}
        seen: dict[str, Posting] = {}
        per_page = int(spec.get("per_page", 250))
        for kw in as_list(spec.get("keywords")) or as_list(spec.get("keyword")) or [""]:
            for page in range(1, int(spec.get("max_pages", 4)) + 1):
                q = {"Keyword": kw, "LocationName": spec.get("location", ""), "ResultsPerPage": per_page,
                     "Page": page}
                if spec.get("remote"):
                    q["RemoteIndicator"] = "True"
                q = {k: v for k, v in q.items() if v not in ("", None)}
                d = http.get_json(f"{API}?{urlencode(q)}", headers=headers) or {}
                res = d.get("SearchResult") or {}
                for item in res.get("SearchResultItems") or []:
                    p = self._posting(item)
                    if p.req_id and p.req_id not in seen:
                        seen[p.req_id] = p
                pages = int(((res.get("UserArea") or {}).get("NumberOfPages")) or 1)
                if page >= pages:
                    break
        return list(seen.values())

    def _posting(self, item: dict) -> Posting:
        m = item.get("MatchedObjectDescriptor") or {}
        details = ((m.get("UserArea") or {}).get("Details") or {})
        pay = next(iter(m.get("PositionRemuneration") or []), {}) or {}
        sched = [s.get("Name", "") for s in m.get("PositionSchedule") or []]
        offer = [s.get("Name", "") for s in m.get("PositionOfferingType") or []]
        employment = employment_of(offer) if employment_of(offer) in ("temporary", "internship") else employment_of(sched)
        duties = details.get("MajorDuties") or []
        text = "\n\n".join(t for t in (details.get("JobSummary", ""), "\n".join(f"- {x}" for x in as_list(duties)),
                                       m.get("QualificationSummary", "")) if t)
        remote = details.get("RemoteIndicator")
        return Posting(
            source=self.name,
            employer=m.get("OrganizationName") or m.get("DepartmentName") or "US Federal Government",
            title=clean_title(m.get("PositionTitle")),
            url=m.get("PositionURI") or "",
            apply_url=next(iter(m.get("ApplyURI") or []), "") or "",
            req_id=str(m.get("PositionID") or item.get("MatchedObjectId") or ""),
            location=m.get("PositionLocationDisplay") or join(
                *[x.get("LocationName", "") for x in m.get("PositionLocation") or []], sep="; "),
            remote=bool(remote) if remote is not None else None,
            posted=iso_date(m.get("PublicationStartDate")),
            deadline=iso_date(m.get("ApplicationCloseDate")),
            employment=employment,
            salary_min=num(pay.get("MinimumRange")),
            salary_max=num(pay.get("MaximumRange")),
            salary_currency=CURRENCY if pay else "",
            lang="en",
            text=text,
            extra={"department": m.get("DepartmentName", ""), "salary_period": pay.get("Description", "")
                   or pay.get("RateIntervalCode", ""), "grade": join(*[
                       f"{g.get('Code', '')}" for g in m.get("JobGrade") or []]),
                   "matched_object_id": str(item.get("MatchedObjectId") or "")},
        )
