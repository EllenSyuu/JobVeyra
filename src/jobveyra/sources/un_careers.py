"""United Nations Secretariat job openings (careers.un.org public search API, no login).

POST https://careers.un.org/api/public/opening/jo/list/filteredV2/en
     {"filterConfig": {"keyword": kw}, "pagination": {"page": p, "itemPerPage": 100,
      "sortBy": "startDate", "sortDirection": -1}}
Posting page: https://careers.un.org/jobSearchDescription/{jobId}?language=en
spec: ``keywords`` (list) or ``keyword``; ``employer`` (default "United Nations"); ``max_pages``.
"""
from __future__ import annotations

from ..models import Posting
from .base import Source, as_list, clean_title, fold, html_to_text, iso_date, join, register

API = "https://careers.un.org/api/public/opening/jo/list/filteredV2/en"
PAGE = 100


def _employment(level: str, title: str) -> str:
    s = fold(f"{level} {title}")
    if s.startswith("i ") or "intern" in s:
        return "internship"
    if "consult" in s or "individual contractor" in s:
        return "contract"
    if "temporary" in s:
        return "temporary"
    return ""


@register
class UNCareers(Source):
    name = "un_careers"

    def fetch(self, spec: dict, http) -> list[Posting]:
        keywords = as_list(spec.get("keywords")) or as_list(spec.get("keyword")) or [""]
        seen: dict[str, Posting] = {}
        for kw in keywords:
            for page in range(int(spec.get("max_pages", 5))):
                body = {"filterConfig": {"keyword": kw},
                        "pagination": {"page": page, "itemPerPage": PAGE, "sortBy": "startDate", "sortDirection": -1}}
                d = http.post_json(API, body) or {}
                data = d.get("data") or {}
                items = data.get("list") or []
                for j in items:
                    jid = str(j.get("jobId") or "")
                    if jid and jid not in seen:
                        seen[jid] = self._posting(j, jid, spec)
                if len(items) < PAGE:
                    break
        return list(seen.values())

    def _posting(self, j: dict, jid: str, spec: dict) -> Posting:
        level = str(j.get("jobLevel") or "")
        title = clean_title(j.get("postingTitle"))
        stations = [s.get("description", "") for s in j.get("dutyStation") or [] if isinstance(s, dict)]
        url = f"https://careers.un.org/jobSearchDescription/{jid}?language=en"
        text = html_to_text(j.get("jobDescription") or j.get("description") or "")
        return Posting(
            source=self.name,
            employer=spec.get("employer") or "United Nations",
            title=title,
            url=url,
            apply_url=url,
            req_id=jid,
            location=join(*stations, sep="; "),
            remote=None,
            posted=iso_date(j.get("startDate")),
            deadline=iso_date(j.get("endDate")),
            employment=_employment(level, title),
            lang="en",
            text=text,
            extra={"level": level, "department": j.get("departmentDescr", "") or "",
                   "job_family": j.get("jobFamily", "") or "", "job_network": j.get("jobNetwork", "") or ""},
        )
