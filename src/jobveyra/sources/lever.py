"""Lever postings (public Postings API, no key).

GET https://api.lever.co/v0/postings/{board}?mode=json&skip=N&limit=100
spec: ``board`` (required), ``employer``, ``region`` ("eu" uses api.eu.lever.co), ``max_pages``.
"""
from __future__ import annotations

from urllib.parse import quote

from ..models import Posting
from .base import Source, clean_title, employment_of, html_to_text, iso_date, join, num, register, remote_hint, require

PAGE = 100


@register
class Lever(Source):
    name = "lever"

    def fetch(self, spec: dict, http) -> list[Posting]:
        board = str(require(spec, "board"))
        host = "api.eu.lever.co" if str(spec.get("region", "")).lower() == "eu" else "api.lever.co"
        out, skip = [], 0
        for _ in range(int(spec.get("max_pages", 10))):
            page = http.get_json(f"https://{host}/v0/postings/{quote(board)}?mode=json&skip={skip}&limit={PAGE}")
            if not isinstance(page, list):
                break
            out.extend(self._posting(j, board, spec) for j in page)
            if len(page) < PAGE:
                break
            skip += PAGE
        return out

    def _posting(self, j: dict, board: str, spec: dict) -> Posting:
        cat = j.get("categories") or {}
        loc = cat.get("location") or join(*(cat.get("allLocations") or []), sep="; ")
        wt = (j.get("workplaceType") or "").lower()
        remote = True if wt == "remote" else False if wt in ("onsite", "on-site", "hybrid") else remote_hint(loc)
        parts = [j.get("descriptionPlain") or html_to_text(j.get("description"))]
        for lst in j.get("lists") or []:
            parts.append(f"{lst.get('text', '')}\n{html_to_text(lst.get('content'))}")
        parts.append(j.get("additionalPlain") or html_to_text(j.get("additional")))
        sal = j.get("salaryRange") or {}
        return Posting(
            source=self.name,
            employer=spec.get("employer") or board,
            title=clean_title(j.get("text")),
            url=j.get("hostedUrl") or "",
            apply_url=j.get("applyUrl") or "",
            req_id=str(j.get("id") or ""),
            location=loc or "",
            remote=remote,
            posted=iso_date(j.get("createdAt")),
            employment=employment_of(cat.get("commitment")),
            salary_min=num(sal.get("min")),
            salary_max=num(sal.get("max")),
            salary_currency=sal.get("currency", "") or "",
            text="\n\n".join(p.strip() for p in parts if p and p.strip()),
            extra={"board": board, "team": cat.get("team", ""), "department": cat.get("department", ""),
                   "country": j.get("country", "") or "", "salary_interval": sal.get("interval", ""),
                   "workplace_type": wt},
        )
