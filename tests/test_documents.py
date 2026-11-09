"""CV and cover-letter generation: content files, LaTeX rendering, language choice, the package
flow (tailor, build) and the PDF checks. Compiling needs a TeX engine and is skipped without one."""
import datetime as dt
import json
import shutil
from pathlib import Path

import pytest
import yaml

from jobveyra import cli, config, queue
from jobveyra.documents import build as docbuild
from jobveyra.documents import content, latex, layout, package, pdfcheck
from jobveyra.models import Posting

FIX = Path(__file__).parent / "fixtures" / "sources"
HAS_TEX = bool(docbuild.find_engine("auto"))
HAS_POPPLER = bool(shutil.which("pdftotext"))

MASTER = """# Alex Rivera
Lisbon, Portugal · alex.rivera@example.com · +351 555 0100

## Experience
### Data Scientist · Example Labs · Lisbon
Jan 2023 to present
- Built a weekly demand forecast for 1,200 stores that cut stock-outs by 18%.
- Designed and analysed 40 pricing experiments with the product team.
### Research Assistant · Example University · Lisbon
Sep 2021 to Dec 2022
- Wrote an open-source package for survival models, used in 3 published studies.

## Education
### M.Sc. Statistics · Example University · Sep 2020 to Jul 2022

## Skills
python, sql, statistics, forecasting, experimentation, survival analysis
"""

POSTING_EN = """Example Retail is a leading grocery chain. Our mission is to make fresh food affordable.
We are hiring a Data Scientist to build forecasting models for our stores.

Requirements
- Strong Python and SQL
- Experience with forecasting and experimentation
- Kubernetes experience

Nice to have
- Spark
"""

POSTING_FR = """Nous sommes une entreprise de commerce de détail et nous recherchons un scientifique des données
pour notre équipe à Montréal. Vous travaillerez avec les équipes produit sur les prévisions de la demande.

Exigences
- Maîtrise de Python et SQL
- Expérience en prévision et expérimentation
- Français requis
"""


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBVEYRA_HOME", str(tmp_path))
    monkeypatch.setenv("JOBQUEUE_NOW", "2026-03-10T09:00:00")
    assert cli.main(["init", str(tmp_path)]) == 0
    raw = yaml.safe_load((tmp_path / "jobveyra.yml").read_text(encoding="utf-8"))
    raw["candidate"].update(name="Alex Rivera", email="alex.rivera@example.com", phone="+351 555 0100",
                            location="Lisbon, Portugal", links=["github.com/example"])
    raw["materials"]["languages"] = ["en", "fr"]
    (tmp_path / "jobveyra.yml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    (tmp_path / "cv" / "master.md").write_text(MASTER, encoding="utf-8")
    fr = (tmp_path / "cv" / "example.yml").read_text(encoding="utf-8").replace("lang: en", "lang: fr")
    (tmp_path / "cv" / "example.fr.yml").write_text(fr, encoding="utf-8")
    return tmp_path


def _cfg(ws):
    cfg = config.load(ws)
    queue.configure(cfg)
    return cfg


def _posting(ws, jid, text, title="Data Scientist", employer="Example Retail", lang=""):
    from jobveyra.discover import save_posting
    p = Posting(source="greenhouse", employer=employer, title=title, url="https://example.com/jobs/1",
                apply_url="https://example.com/jobs/1/apply", req_id="R-77", location="Lisbon", text=text, lang=lang)
    save_posting(ws, jid, p)
    q = queue.Queue(ws / "state")
    q.upsert({**p.to_queue(), "id": jid})
    return p


def _write_letter(pkg: Path, body: str):
    text = (pkg / "letter.md").read_text(encoding="utf-8")
    head = text[: text.index("---\n", 4) + 4]
    (pkg / "letter.md").write_text(head + body, encoding="utf-8")


GOOD_LETTER = ("I am applying for the Data Scientist role at Example Retail because fresh food that people can "
               "afford is a forecasting problem before it is anything else, and it is the problem I have worked "
               "on every week since January 2023.\n\n"
               "At Example Labs I built a weekly demand forecast for 1,200 stores that cut stock-outs by 18%. "
               "I own it end to end: the data checks, the models, and the review with store managers who use it "
               "to plan orders. The same work taught me to explain uncertainty in terms a planner can act on.\n\n"
               "I also designed and analysed 40 pricing experiments with the product team, from the power "
               "calculation to the readout. Before that, as a research assistant at Example University, I wrote "
               "an open-source package for survival models that was used in 3 published studies, which is where "
               "I learned to write code other people rely on.\n\n"
               "I would welcome the chance to talk about how this experience fits your forecasting plans for the "
               "stores, and I can start on a timeline that suits the team. Thank you for your time and for "
               "reading my application; I look forward to hearing from you about the next steps in the process.\n")


# ---------------------------------------------------------------- content and rendering

def test_cv_yaml_round_trip_and_validation():
    cv = content.cv_from_dict({"lang": "fr", "experience": [{"org": "A & B", "title": "Analyste", "start": "2020",
                                                             "end": "2021", "bullets": ["Cut cost by 10%"]}],
                               "skills": [{"label": "Outils", "items": ["Python", "R"]}]},
                              content.Header(name="X Y", email="x@example.com"))
    assert cv.heading("experience") == "Expérience"
    assert cv.skills == [("Outils", "Python, R")]
    assert "Cut cost by 10%" in cv.text()
    with pytest.raises(content.ContentError, match="unknown key"):
        content.cv_from_dict({"experiance": []})
    with pytest.raises(content.ContentError, match="'org' is required"):
        content.cv_from_dict({"experience": [{"title": "x"}]})
    with pytest.raises(content.ContentError, match="order"):
        content.cv_from_dict({"order": ["hobbies"]})


def test_latex_escaping_markup_and_ascii_dates():
    assert latex.esc("R&D 50% $5 #1 a_b") == r"R\&D 50\% \$5 \#1 a\_b"
    assert latex.esc("**bold** and *it*") == r"\textbf{bold} and \textit{it}"
    assert latex.esc("2019–2021") == "2019 - 2021"
    tex = latex.render_cv(content.cv_from_dict({"experience": [{"org": "Org", "start": "Jan 2020", "end": "Present"}]},
                                               content.Header(name="Alex", email="a@example.com", phone="1")))
    assert "Jan 2020~-~Present" in tex and "Kerning=Off" in tex and "pdftitle={Alex - CV}" in tex
    assert "–" not in tex and "$" not in tex.split(r"\begin{document}")[1]


def test_letter_front_matter_comments_and_defaults():
    letter = content.parse_letter("---\nlang: fr\nre: Analyste (R-1)\nrecipient: [Équipe, Org]\n---\n"
                                  "<!-- a note -->\nPremier paragraphe.\n\nSecond.\n")
    assert letter.paragraphs == ["Premier paragraphe.", "Second."] and letter.words() == 3
    tex = latex.render_letter(letter, content.Header(name="Alex"), today=dt.date(2026, 3, 1))
    assert "1er mars 2026" in tex and "Madame, Monsieur," in tex and "Objet: Analyste (R-1)" in tex
    assert "a note" not in tex and r"\hyphenpenalty=10000" in tex
    assert content.format_date(dt.date(2026, 3, 9), "de") == "9. März 2026"
    with pytest.raises(content.ContentError):
        content.parse_letter("---\nsubject: x\n---\nbody")


def test_cv_variant_resolves_language_file(tmp_path):
    base = tmp_path / "ds.yml"
    base.write_text("lang: en\n", encoding="utf-8")
    assert content.cv_variant(base, "fr") == base
    (tmp_path / "ds.fr.yml").write_text("lang: fr\n", encoding="utf-8")
    assert content.cv_variant(base, "fr") == tmp_path / "ds.fr.yml"


def test_materials_config_validation(ws):
    raw = yaml.safe_load((ws / "jobveyra.yml").read_text(encoding="utf-8"))
    for bad, msg in (({"paper": "a5"}, "paper"), ({"languages": ["xx"]}, "languages"),
                     ({"letter_words": [300, 200]}, "letter_words"), ({"engine": "pdflatex"}, "engine")):
        r = dict(raw, materials={**raw["materials"], **bad})
        with pytest.raises(config.ConfigError, match=msg):
            config.from_dict(r, ws)


# ---------------------------------------------------------------- language choice

def test_language_follows_posting_then_requirement_then_default(ws):
    cfg = _cfg(ws)
    assert package.choose_language(cfg, Posting("x", "E", "T", "u", text=POSTING_EN))[0] == "en"
    assert package.choose_language(cfg, Posting("x", "E", "T", "u", text=POSTING_FR))[0] == "fr"
    de = Posting("x", "E", "T", "u", text="Wir suchen eine Person für unser Team und die Arbeit mit Daten.", lang="de")
    lang, why = package.choose_language(cfg, de)
    assert lang == "en" and "first document language" in why


# ---------------------------------------------------------------- package flow

def test_tailor_writes_package_in_posting_language(ws, capsys):
    _posting(ws, "greenhouse:fr1", POSTING_FR, title="Scientifique des données", lang="fr")
    assert cli.main(["tailor", "greenhouse:fr1"]) == 1          # French title: no track matches
    assert "--track" in capsys.readouterr().out
    assert cli.main(["tailor", "greenhouse:fr1", "--track", "ds"]) == 0
    pkg = ws / "packages" / "greenhouse_fr1"
    assert yaml.safe_load((pkg / "cv.yml").read_text(encoding="utf-8"))["lang"] == "fr"
    letter = (pkg / "letter.md").read_text(encoding="utf-8")
    assert "lang: fr" in letter and "Scientifique des données (R-77)" in letter
    assert cli.main(["tailor", "greenhouse:fr1", "--track", "ds"]) == 1   # exists without --force
    assert cli.main(["tailor", "greenhouse:fr1", "--track", "ds", "--force"]) == 0


def test_brief_keeps_gaps_out_of_the_documents(ws):
    _posting(ws, "greenhouse:en1", POSTING_EN)
    cfg = _cfg(ws)
    r = package.tailor(cfg, "greenhouse:en1")
    assert r["lang"] == "en"
    pkg = Path(r["dir"])
    brief = (pkg / "brief.md").read_text(encoding="utf-8")
    assert "Kubernetes" in brief.split("## Not shown by your fact base")[1]
    for f in ("cv.yml", "letter.md"):
        assert "kubernetes" not in (pkg / f).read_text(encoding="utf-8").lower()


def test_build_blocks_placeholders_fabrication_and_self_negative_wording(ws):
    _posting(ws, "greenhouse:en1", POSTING_EN)
    cfg = _cfg(ws)
    pkg = Path(package.tailor(cfg, "greenhouse:en1")["dir"])
    r = package.build(cfg, "greenhouse:en1", compile_pdf=False)
    assert not r["pass"]
    letter_checks = {c["check"]: c for c in r["documents"]["letter"]["checks"]}
    assert letter_checks["placeholders"]["ok"] is False
    _write_letter(pkg, "Although I lack Spark experience, I led a team of 25 people since 2015.\n")
    r = package.build(cfg, "greenhouse:en1", compile_pdf=False)
    checks = {c["check"]: c for c in r["documents"]["letter"]["checks"]}
    assert checks["fabrication"]["ok"] is False and "25" in checks["fabrication"]["detail"]
    assert checks["wording"]["ok"] is False
    assert checks["letter_words"]["ok"] is None                    # short letter: warning only


def test_build_text_checks_pass_on_honest_documents(ws):
    _posting(ws, "greenhouse:en1", POSTING_EN)
    cfg = _cfg(ws)
    pkg = Path(package.tailor(cfg, "greenhouse:en1")["dir"])
    _write_letter(pkg, GOOD_LETTER)
    r = package.build(cfg, "greenhouse:en1", compile_pdf=False)
    bad = [c for d in r["documents"].values() for c in d["checks"] if c["ok"] is False]
    assert r["pass"], bad
    assert json.loads((pkg / "report.json").read_text(encoding="utf-8"))["pass"]


@pytest.mark.skipif(not HAS_TEX, reason="no LaTeX engine")
def test_build_compiles_checks_and_marks_ready(ws, capsys):
    _posting(ws, "greenhouse:en1", POSTING_EN)
    cfg = _cfg(ws)
    q = queue.Queue(ws / "state")
    q.screen("greenhouse:en1", 80, reason="test")
    pkg = Path(package.tailor(cfg, "greenhouse:en1")["dir"])
    _write_letter(pkg, GOOD_LETTER)
    code = cli.main(["build", "greenhouse:en1"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert (pkg / "cv.pdf").is_file() and (pkg / "letter.pdf").is_file()
    assert "[PASS] pages: 1 page(s)" in out and "[PASS] contact_text" in out
    assert "[WARN] keywords" in out and "kubernetes" in out.lower()     # reported, never stuffed
    assert queue.Queue(ws / "state").get("greenhouse:en1")["state"] in ("ready_to_submit", "blocked_auth")
    assert "alex.rivera@example.com" in (pkg / "cv.txt").read_text(encoding="utf-8")


@pytest.mark.skipif(not HAS_TEX, reason="no LaTeX engine")
def test_two_page_cv_fails_the_page_limit(ws, capsys):
    cv = yaml.safe_load((ws / "cv" / "example.yml").read_text(encoding="utf-8"))
    cv["experience"] = cv["experience"] * 12
    (ws / "cv" / "long.yml").write_text(yaml.safe_dump(cv), encoding="utf-8")
    assert cli.main(["render", str(ws / "cv" / "long.yml")]) == 1
    assert "[FAIL] pages" in capsys.readouterr().out


# ---------------------------------------------------------------- PDF checks (no TeX needed)

def test_non_ascii_date_ranges_are_found_but_quantities_are_not():
    assert pdfcheck.find_non_ascii_date_ranges("Data Scientist  Jan 2020 – Mar 2022")
    assert not pdfcheck.find_non_ascii_date_ranges("Budget EUR 1500–2000 per month")
    assert not pdfcheck.find_non_ascii_date_ranges("Jan 2020 - Mar 2022")
    assert pdfcheck.normalize_text("Master’s  2016–2024") == "Master's 2016-2024"


def test_layout_finds_a_hole_and_an_orphaned_header():
    L = layout.Line
    lines = [L(top=50 + 14 * i, bottom=60 + 14 * i, left=50, height=10, text=f"line {i}") for i in range(10)]
    lines.append(L(top=400, bottom=410, left=50, height=10, text="after the hole"))
    problems = layout.report([layout.Page(792, lines)])
    assert any("hole" in p for p in problems)
    p1 = layout.Page(792, [L(top=50, bottom=60, left=50, height=10, text="Body"),
                           L(top=680, bottom=690, left=50, height=10, text="Employer   2020 - 2022")])
    p2 = layout.Page(792, [L(top=50, bottom=60, left=72, height=10, text="a bullet that belongs above"),
                           L(top=64, bottom=74, left=72, height=10, text="another bullet")])
    assert any("orphaned" in p for p in layout.find_orphans([p1, p2]))


def test_doctor_reports_document_tooling(ws, capsys):
    cli.main(["doctor"])
    out = capsys.readouterr().out
    if not HAS_TEX:
        assert "no LaTeX engine" in out
