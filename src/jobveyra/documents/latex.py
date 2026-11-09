"""Render a CV or cover letter to LaTeX in the "classic" style.

One page, black and white, a serif face (XCharter when installed, else TeX Gyre or Latin Modern),
letter-spaced small-caps section titles over a hairline rule, dates right-aligned, no icons and
no photo. The choices that matter for applicant-tracking systems are fixed here rather than left
to taste:

- kerning is off, so text extractors do not split words (``EDUCA TION``) or emails;
- contact details are literal text, not icons or link-only;
- date ranges use a spaced ASCII hyphen, because some ATS date parsers drop an en dash;
- no math mode and no hyphenation in the letter, so keywords stay whole in the text layer;
- the PDF title and author are set, which also avoids a Poppler crash on empty Info fields.

The CV layout follows Jake Gutierrez's resume template (MIT).
"""
from __future__ import annotations

import datetime as dt
import functools
import re
import shutil
import subprocess

from .content import CV, ENTRY_SECTIONS, Letter, CLOSING, SALUTATION, letter_date

PAPER = ("letter", "a4")

_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
        "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
_ESC_RE = re.compile(r"[\\&%$#_{}~^]")


def esc(s: str) -> str:
    """Escape LaTeX specials, then turn **bold** and *italic* into commands."""
    s = _ESC_RE.sub(lambda m: _ESC[m.group(0)], str(s))
    s = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\\textit{\1}", s)
    # an en/em dash typed between two years becomes the ASCII range the parsers read
    s = re.sub(r"((?:19|20)\d\d)\s*[\u2013\u2014]\s*", r"\1 - ", s)
    return s


def _url(link: str) -> tuple[str, str]:
    shown = re.sub(r"^https?://(www\.)?", "", link).rstrip("/")
    href = link if re.match(r"^[a-z]+:", link) else f"https://{shown}"
    return href.replace("%", r"\%").replace("#", r"\#"), esc(shown)


def _contact(h, *, links: bool = True) -> str:
    parts = [esc(x) for x in (h.city, h.phone) if x]
    if h.email:
        parts.append(rf"\href{{mailto:{h.email}}}{{{esc(h.email)}}}")
    if links:
        for link in h.links:
            href, shown = _url(link)
            parts.append(rf"\href{{{href}}}{{{shown}}}")
    return r" \sep ".join(parts)


PREFERRED_FONTS = ("XCharter", "TeX Gyre Pagella", "TeX Gyre Termes", "Latin Modern Roman")
_FONT_FILES = {"XCharter": "XCharter-Roman.otf", "TeX Gyre Pagella": "texgyrepagella-regular.otf",
               "TeX Gyre Termes": "texgyretermes-regular.otf", "Latin Modern Roman": "lmroman10-regular.otf"}


@functools.cache
def pick_font(wanted: str = "auto") -> str:
    """The first installed serif face: XCharter, then TeX Gyre, then Latin Modern (always in TeX)."""
    if wanted and wanted != "auto":
        return wanted
    for name in PREFERRED_FONTS:
        f = _FONT_FILES[name]
        if shutil.which("kpsewhich"):
            r = subprocess.run(["kpsewhich", f], capture_output=True, text=True)
            if r.stdout.strip():
                return name
        if shutil.which("fc-list"):
            r = subprocess.run(["fc-list", f":family={name}"], capture_output=True, text=True)
            if r.stdout.strip():
                return name
    return "Latin Modern Roman"


def _font(font: str = "auto") -> str:
    # Kerning=Off keeps the text layer clean: kerning pairs make extractors split words.
    return rf"\setmainfont{{{pick_font(font)}}}[Kerning=Off]"


def _preamble(paper: str, margins: str, title: str, author: str, font: str = "auto") -> str:
    if paper not in PAPER:
        raise ValueError(f"paper must be one of {', '.join(PAPER)}")
    return "\n".join([
        rf"\documentclass[{paper}paper,11pt]{{article}}",
        rf"\usepackage[{paper}paper,{margins}]{{geometry}}",
        r"\usepackage{fontspec}",
        _font(font),
        r"\usepackage{titlesec}",
        r"\usepackage{enumitem}",
        r"\usepackage[hidelinks]{hyperref}",
        rf"\hypersetup{{pdftitle={{{esc(title)}}},pdfauthor={{{esc(author)}}},pdfcreator={{}},pdfproducer={{}}}}",
        r"\pagestyle{empty}",
        r"\urlstyle{same}",
        r"\raggedright",
        r"\setlength{\parindent}{0pt}",
        r"\setlength{\tabcolsep}{0in}",
        r"\newcommand{\sep}{\unskip\ \textbar\ \ignorespaces}",
    ])


def render_cv(cv: CV, *, paper: str = "letter", font: str = "auto") -> str:
    h = cv.header
    out = [_preamble(paper, "top=0.55in,bottom=0.5in,left=0.55in,right=0.55in", f"{h.name} - CV", h.name, font), r"""
\flushbottom
\linespread{1.04}
\titleformat{\section}{\large\scshape\addfontfeature{LetterSpace=5}}{}{0em}{}[{\vspace{1pt}\titlerule[0.6pt]}]
\titlespacing*{\section}{0pt}{9pt plus 5pt minus 2pt}{5pt plus 1pt}
\newcommand{\entry}[4]{%
  \item
  \begin{tabular*}{\linewidth}[t]{l@{\extracolsep{\fill}}r}
    \textbf{#1} & #2 \\
    \textit{\small #3} & \textit{\small #4} \\
  \end{tabular*}}
\newenvironment{entries}{\begin{itemize}[leftmargin=0.15in,label={},topsep=0pt,partopsep=0pt,parsep=0pt,itemsep=5pt plus 3pt]}{\end{itemize}}
\newenvironment{bullets}{\begin{itemize}[leftmargin=1.5em,labelsep=0.5em,label={\small\textbullet},topsep=2pt plus 1pt,partopsep=0pt,parsep=0pt,itemsep=1pt plus 1pt]}{\end{itemize}}
\newcommand{\hangpara}[1]{{\small\hangindent=1.5em\hangafter=1 #1\par}}
\newenvironment{plainsection}{\par\leftskip=0.15in\parskip=1pt plus 1pt}{\par}
\begin{document}
\begin{center}\setlength{\topsep}{0pt}"""]
    out.append(rf"  {{\Huge\bfseries\scshape {esc(h.name)}}}\\[5pt]")
    out.append(rf"  \small {_contact(h)}")
    out.append(r"\end{center}")
    for key in cv.order:
        if key in ENTRY_SECTIONS:
            entries = getattr(cv, key)
            if not entries:
                continue
            out.append(rf"\section{{{esc(cv.heading(key))}}}")
            out.append(r"\begin{entries}")
            for e in entries:
                dates = r"~-~".join(esc(x) for x in (e.start, e.end) if x)
                out.append(rf"  \entry{{{esc(e.org)}}}{{{dates}}}{{{esc(e.title)}}}{{{esc(e.city)}}}")
                if e.bullets:
                    out.append(r"  \begin{bullets}")
                    out += [rf"    \item\small {esc(b)}" for b in e.bullets]
                    out.append(r"  \end{bullets}")
            out.append(r"\end{entries}")
        elif key in ("publications", "awards"):
            items = getattr(cv, key)
            if items:
                out.append(rf"\section{{{esc(cv.heading(key))}}}")
                out.append(r"\begin{plainsection}")
                out += [rf"\hangpara{{{esc(x)}}}" for x in items]
                out.append(r"\end{plainsection}")
        elif key == "skills" and cv.skills:
            out.append(rf"\section{{{esc(cv.heading('skills'))}}}")
            out.append(r"\begin{plainsection}")
            out += [rf"\hangpara{{\textbf{{{esc(a)}}}: {esc(b)}}}" for a, b in cv.skills]
            out.append(r"\end{plainsection}")
        elif key == "custom":
            for title, lines in cv.custom:
                out.append(rf"\section{{{esc(title)}}}")
                out.append(r"\begin{plainsection}")
                out += [rf"\hangpara{{{esc(x)}}}" for x in lines]
                out.append(r"\end{plainsection}")
    out.append(r"\par\penalty-10000")
    out.append(r"\end{document}")
    return "\n".join(out) + "\n"


def render_letter(letter: Letter, header, *, paper: str = "letter", today: dt.date | None = None,
                  font: str = "auto") -> str:
    lang = letter.lang
    out = [_preamble(paper, "top=0.8in,bottom=0.8in,left=0.9in,right=0.9in",
                     f"{header.name} - Cover Letter", header.name, font), r"""
\hyphenpenalty=10000
\exhyphenpenalty=10000
\setlength{\parskip}{8pt}
\linespread{1.08}
\begin{document}
\begin{center}"""]
    out.append(rf"  {{\Huge\bfseries\scshape {esc(header.name)}}}\\[5pt]")
    out.append(rf"  \small {_contact(header)}")
    out.append(r"\end{center}")
    out.append(r"\vspace{2pt}\rule{\linewidth}{0.6pt}")
    out.append(r"\vspace{6pt}")
    out.append("")
    out.append(esc(letter_date(letter, today or dt.date.today())))
    out.append("")
    if letter.recipient:
        out.append(r"\\".join(esc(x) for x in letter.recipient))
        out.append("")
    if letter.re:
        out.append(rf"\textbf{{{'Objet' if lang == 'fr' else 'Re'}: {esc(letter.re)}}}")
        out.append("")
    out.append(esc(letter.salutation or SALUTATION.get(lang, SALUTATION["en"])))
    out.append("")
    for p in letter.paragraphs:
        out.append(esc(p))
        out.append("")
    out.append(rf"{esc(letter.closing or CLOSING.get(lang, CLOSING['en']))}\\[14pt]")
    out.append(esc(header.name))
    out.append(r"\end{document}")
    return "\n".join(out) + "\n"
