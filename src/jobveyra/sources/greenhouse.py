"""Greenhouse job boards (public Job Board API, no key).

GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
spec: ``board`` (required), ``employer`` (display name; default: the board's company name).
"""
from __future__ import annotations

from urllib.parse import quote

from ..models import Posting
from .base import Source, clean_title, employment_of, html_to_text, iso_date, num, register, remote_hint, require


@register
class Greenhouse(Source):
    name = "greenhouse"

    def fetch(self, spec: dict, http) -> list[Posting]:
        board = str(require(spec, "board"))
        d = http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{quote(board)}/jobs?content=true")
        out = []
        for j in d.get("jobs") or []:
            loc = (j.get("location") or {}).get("name", "") or ""
            meta = {str(m.get("name", "")).lower(): m.get("value") for m in j.get("metadata") or [] if m}
            employment = employment_of(next((v for k, v in meta.items() if "employment" in k or "job type" in k), ""))
            pay = next(iter(j.get("pay_input_ranges") or []), None) or {}
            lo, hi = num(pay.get("min_cents")), num(pay.get("max_cents"))
            offices = [o.get("name", "") for o in j.get("offices") or [] if o]
            out.append(Posting(
                source=self.name,
                employer=spec.get("employer") or j.get("company_name") or board,
                title=clean_title(j.get("title")),
                url=j.get("absolute_url") or "",
                req_id=str(j.get("id") or ""),
                location=loc,
                remote=remote_hint(loc, *offices),
                posted=iso_date(j.get("first_published") or j.get("updated_at")),
                employment=employment,
                salary_min=lo / 100 if lo is not None else None,
                salary_max=hi / 100 if hi is not None else None,
                salary_currency=pay.get("currency_type", "") or "",
                lang=(j.get("language") or "")[:2],
                text=html_to_text(j.get("content")),
                extra={"board": board, "requisition_id": j.get("requisition_id") or "",
                       "departments": [x.get("name", "") for x in j.get("departments") or [] if x],
                       "offices": offices, "updated_at": j.get("updated_at") or ""},
            ))
        return out
