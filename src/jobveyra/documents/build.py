"""Compile a CV or letter and check the PDF the way an employer's system will read it.

``compile_tex`` runs lualatex (or xelatex) in a private build folder and returns the PDF.
``check_pdf`` reads it back: page count, a clean text layer, the contact details as literal text,
ASCII date ranges, posting keywords, and the layout checks in ``layout.py``.

Every check result is a dict ``{"check", "ok", "detail"}`` with ``ok`` one of True, False or
None (skipped because a tool is missing); a skipped check never passes silently, it is reported.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from . import layout, pdfcheck

ENGINES = ("lualatex", "xelatex")


class BuildError(RuntimeError):
    pass


def find_engine(prefer: str = "auto") -> str | None:
    names = ENGINES if prefer in ("auto", "") else (prefer,)
    for n in names:
        path = shutil.which(n)
        if path:
            return path
    return None


def compile_tex(tex: Path, *, engine: str = "auto", timeout: int = 180) -> Path:
    """Compile ``tex`` next to itself; the PDF lands beside the source, logs in ``build/``.

    With ``engine="auto"`` lualatex is tried first and xelatex next, so a broken font cache in
    one engine does not stop the build."""
    names = ENGINES if engine in ("auto", "") else (engine,)
    exes = [shutil.which(n) for n in names]
    exes = [e for e in exes if e]
    if not exes:
        raise BuildError("no LaTeX engine found: install TeX Live or MiKTeX (lualatex or xelatex)")
    errors = []
    for exe in exes:
        try:
            return _compile(Path(tex).resolve(), exe, timeout)
        except BuildError as e:
            errors.append(str(e))
    raise BuildError(" | ".join(errors))


def _compile(tex: Path, exe: str, timeout: int) -> Path:
    build = tex.parent / "build"
    build.mkdir(exist_ok=True)
    pdf = tex.with_suffix(".pdf")
    if pdf.exists():
        pdf.unlink()
    cmd = [exe, "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={build}", tex.name]
    env = dict(os.environ, SOURCE_DATE_EPOCH=os.environ.get("SOURCE_DATE_EPOCH", "0"))
    try:
        res = subprocess.run(cmd, cwd=tex.parent, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout, env=env)
    except subprocess.TimeoutExpired as e:
        raise BuildError(f"{Path(exe).name} timed out after {timeout}s on {tex.name}") from e
    out = build / pdf.name
    if res.returncode != 0 or not out.is_file():
        errors = [l for l in (res.stdout or "").splitlines() if l.startswith("!")]
        raise BuildError(f"{Path(exe).name} failed on {tex.name}: " + ("; ".join(errors[:3]) or f"exit {res.returncode}"
                                                                     + f" (log: {build / tex.with_suffix('.log').name})"))
    shutil.move(str(out), pdf)
    return pdf


def _r(check: str, ok, detail: str = "") -> dict:
    return {"check": check, "ok": ok, "detail": detail}


NOISE = re.compile(r"\(cid:\d+\)|�")


def check_pdf(pdf: Path, *, pages: int | None = 1, contains: list[str] = (), keywords: list[str] = (),
              ascii_dates: bool = True, check_layout: bool = True,
              footer: bool = False) -> tuple[list[dict], str]:
    """Run every PDF check. Returns (results, extracted text)."""
    results: list[dict] = []
    try:
        extractor, text, n = pdfcheck.verify_pdf(pdf)
    except pdfcheck.VerificationError as e:
        return [_r("text_layer", None if "not found" in str(e) else False, str(e))], ""
    results.append(_r("pages", n == pages if pages else True, f"{n} page(s)" + (f", expected {pages}" if pages else "")))
    noise = NOISE.findall(text)
    results.append(_r("text_layer", not noise and len(text.strip()) > 50,
                      f"{extractor}; " + (f"{len(noise)} unreadable glyph(s)" if noise else "clean")))
    norm = pdfcheck.normalize_text(text)
    missing = [c for c in contains if c and pdfcheck.normalize_text(c) not in norm]
    results.append(_r("contact_text", not missing,
                      "missing as literal text: " + ", ".join(missing) if missing else "email and phone readable"))
    if ascii_dates:
        hits = pdfcheck.find_non_ascii_date_ranges(text)
        results.append(_r("ascii_dates", not hits, "; ".join(f"U+{ord(d):04X} in {l[:60]!r}" for l, d in hits)
                          or "date ranges use ASCII hyphens"))
    if keywords:
        low = norm.lower()
        miss = [k for k in keywords if k.lower() not in low]
        results.append(_r("keywords", None if miss else True,
                          f"{len(keywords) - len(miss)}/{len(keywords)} present"
                          + (f"; absent: {', '.join(miss)} (add only where your fact base supports it)" if miss else "")))
    if check_layout:
        try:
            problems = layout.report(layout.parse_pdf(Path(pdf)), footer=footer)
            results.append(_r("layout", not problems, "; ".join(problems) or "clean"))
        except RuntimeError as e:
            results.append(_r("layout", None, f"skipped: {e}"))
    return results, text


def passed(results: list[dict]) -> bool:
    return all(r["ok"] is not False for r in results)
