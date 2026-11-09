"""SmartRecruiters companies (public Posting API, no key).

GET https://api.smartrecruiters.com/v1/companies/{board}/postings?limit=100&offset=N
GET https://api.smartrecruiters.com/v1/companies/{board}/postings/{id}   (description, links)
spec: ``board`` (required), ``employer``, ``details`` (default true), ``max_details`` (default 200),
``max_pages`` (default 10).
"""
from __future__ import annotations

from urllib.parse import quote

from ..models import Posting
from .base import Source, clean_title, employment_of, html_to_text, iso_date, join, register, require
from .http import HttpError

PAGE = 100
SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


@register
class SmartRecruiters(Source):
    name = "smartrecruiters"

    def fetch(self, spec: dict, http) -> list[Posting]:
        board = str(require(spec, "board"))
        base = f"https://api.smartrecruiters.com/v1/companies/{quote(board)}/postings"
        items, offset = [], 0
        for _ in range(int(spec.get("max_pages", 10))):
            d = http.get_json(f"{base}?limit={PAGE}&offset={offset}")
            content = d.get("content") or []
            items.extend(content)
            offset += PAGE
            total = d.get("totalFound")
            if not content or (total is not None and offset >= int(total)):
                break
        out, details_left = [], int(spec.get("max_details", 200)) if spec.get("details", True) else 0
        for j in items:
            detail = {}
            if details_left > 0 and j.get("id"):
                details_left -= 1
                try:
                    detail = http.get_json(f"{base}/{quote(str(j['id']))}") or {}
                except HttpError:
                    detail = {}
            out.append(self._posting(j, detail, board, spec))
        return out

    def _posting(self, j: dict, detail: dict, board: str, spec: dict) -> Posting:
        loc = j.get("location") or {}
        sections = ((detail.get("jobAd") or {}).get("sections") or {})
        text = "\n\n".join(f"{(sections[k].get('title') or '').strip()}\n{html_to_text(sections[k].get('text'))}".strip()
                             for k in SECTIONS if (sections.get(k) or {}).get("text"))
        emp = j.get("typeOfEmployment") or {}
        jid = str(j.get("id") or "")
        remote = loc.get("remote")
        return Posting(
            source=self.name,
            employer=spec.get("employer") or (j.get("company") or {}).get("name") or board,
            title=clean_title(j.get("name")),
            url=detail.get("postingUrl") or f"https://jobs.smartrecruiters.com/{board}/{jid}",
            apply_url=detail.get("applyUrl") or "",
            req_id=jid,
            location=loc.get("fullLocation") or join(loc.get("city"), loc.get("region"), loc.get("country")),
            remote=False if loc.get("hybrid") else (bool(remote) if remote is not None else None),
            posted=iso_date(j.get("releasedDate")),
            employment=employment_of(emp.get("label") or emp.get("id")),
            lang=((j.get("language") or {}).get("code") or "")[:2],
            text=text.strip(),
            extra={"board": board, "ref_number": j.get("refNumber", "") or "",
                   "experience_level": (j.get("experienceLevel") or {}).get("label", ""),
                   "department": (j.get("department") or {}).get("label", "")},
        )
