"""Answer memory, the board, the daily retrospective and learnings, email outcomes, the
consistency check and the phone page."""
import datetime as dt
import json
import re

import pytest
import yaml

from jobveyra import board, cli, config, consistency, inbox, outcomes, queue, retro
from jobveyra.answers import Memory
from jobveyra.report import phone

TODAY = dt.date(2026, 3, 10)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBVEYRA_HOME", str(tmp_path))
    monkeypatch.setenv("JOBQUEUE_NOW", "2026-03-10T09:00:00")
    assert cli.main(["init", str(tmp_path)]) == 0
    return tmp_path


def _cfg(ws):
    cfg = config.load(ws)
    queue.configure(cfg)
    return cfg


def _job(q, jid, employer="Acme Analytics", title="Data Scientist", url=None, req="", deadline="", state="eligible"):
    url = url or f"https://jobs.lever.co/acme/{jid}"
    q.upsert({"id": jid, "employer": employer, "title": title, "url": url, "apply_url": url, "req_id": req,
              "deadline": deadline})
    q.screen(jid, 75, reason="test")
    if state in ("ready_to_submit", "submitted", "needs_check"):
        q.package_built(jid, f"packages/{jid}")
    if state == "submitted":
        q.mark_submitted(jid, "Thanks, application received")
    if state == "needs_check":
        q.claim()
        q.clicked(jid)
        q.mark_uncertain(jid, "no confirmation page")
    return q.get(jid)


# ---------------------------------------------------------------- answers

def test_init_writes_an_empty_answers_file(ws):
    assert (ws / "answers.yml").is_file()
    assert Memory(ws).rules() == []


def test_standing_rules_then_employer_memory_then_one_question_per_employer(ws):
    (ws / "answers.yml").write_text(yaml.safe_dump([{"match": "authori[sz]ed to work", "answer": "Yes",
                                                      "note": "work authorization"}]), encoding="utf-8")
    m = Memory(ws)
    assert m.lookup("Are you legally authorized to work here?")[0] == "Yes"
    assert m.ask("What is your notice period?", "Acme", "j1", TODAY) == ("hold", "Q1")
    assert m.ask("Do you have a valid driver licence?", "Acme", "j2", TODAY) == ("hold", "Q1")   # merged
    assert m.ask("What is your notice period?", "Globex", "j3", TODAY) == ("hold", "Q2")
    q1 = m.open_questions()[0]
    assert "also: Do you have a valid driver licence" in q1["question"] and q1["jobs"] == "j1,j2"
    m.reply("Q1", "Two weeks", TODAY)
    assert m.lookup("What is your notice period?", "Acme")[0] == "Two weeks"
    assert [x["id"] for x in m.open_questions()] == ["Q2"]


def test_personal_questions_are_never_answered_from_memory(ws):
    m = Memory(ws)
    m.record("Acme", "Please indicate your gender", "Woman", TODAY)
    assert m.lookup("Please indicate your gender", "Acme") is None
    m.record("Acme", "I certify that the information is true", "Yes", TODAY)
    assert m.lookup("I certify that the information is true", "Acme") is None


def test_answers_cli_holds_the_job_and_reply_releases_it(ws, capsys):
    cfg = _cfg(ws)
    q = queue.Queue(cfg.state_dir)
    _job(q, "j1", state="ready_to_submit")
    assert cli.main(["answers", "ask", "--question", "Notice period?", "--job", "j1"]) == 3
    j = queue.Queue(cfg.state_dir).get("j1")
    assert j["state"] == "blocked_human" and j["reason"] == "hold:Q1"
    assert cli.main(["answers", "reply", "Q1", "--answer", "Two weeks"]) == 0
    assert queue.Queue(cfg.state_dir).get("j1")["state"] == "ready_to_submit"
    assert cli.main(["answers", "lookup", "--question", "Notice period?", "--company", "Acme Analytics"]) == 0


# ---------------------------------------------------------------- board

def test_board_renders_and_applies_ticks_once(ws):
    cfg = _cfg(ws)
    q = queue.Queue(cfg.state_dir)
    _job(q, "auth1", url="https://acme.wd3.myworkdayjobs.com/en-US/Careers/job/X_1", state="ready_to_submit",
         deadline="2026-03-14")
    q.block("auth1", "auth:workday:acme")
    _job(q, "chk", state="needs_check")
    _job(q, "sent", state="submitted")
    _job(q, "stuck", state="ready_to_submit")
    q.block("stuck", "captcha")
    body = board.render(cfg, q, TODAY)
    for heading in ("## Sign in", "## Check on the portal", "## Stuck", "## Heard back?"):
        assert heading in body
    ticked = body
    for marker in ("jv:signedin:workday:acme", "jv:found:chk", "jv:skip:stuck"):
        ticked = re.sub(r"\[ \]( [^\n]*?<!-- " + re.escape(marker) + ")", r"[x]\1", ticked)
    ticked = ticked.replace("[ ] interview <!-- jv:outcome:interview:sent", "[x] interview <!-- jv:outcome:interview:sent")
    done = board.apply(cfg, q, ticked)
    assert len(done) == 4, done
    q = queue.Queue(cfg.state_dir)
    assert q.get("chk")["state"] == "submitted" and q.get("stuck")["state"] == "excluded"
    assert [r["outcome"] for r in outcomes.load(cfg.state_dir) if r["job_id"] == "sent"] == ["interview"]
    assert board.apply(cfg, q, ticked) == []               # idempotent
    assert "jv:found:chk" not in board.render(cfg, q, TODAY)


def test_board_comment_answers_only_the_named_question(ws):
    cfg = _cfg(ws)
    q = queue.Queue(cfg.state_dir)
    m = Memory(ws)
    for i in range(1, 11):
        _job(q, f"j{i}", employer=f"E{i}", state="ready_to_submit")
        _, qid = m.ask(f"Question {i}?", f"E{i}", f"j{i}", TODAY)
        q.block(f"j{i}", f"hold:{qid}")
    done = board.comment(cfg, q, "Q1: yes\nthanks!", TODAY)
    assert done == ["Q1 answered; 1 job(s) back in the queue"]
    assert queue.Queue(cfg.state_dir).get("j10")["state"] == "blocked_human"     # hold:Q10 is not hold:Q1


def test_board_says_when_nothing_needs_you(ws):
    cfg = _cfg(ws)
    assert "Nothing needs you right now." in board.render(cfg, queue.Queue(cfg.state_dir), TODAY)


# ---------------------------------------------------------------- retro and learnings

def test_retro_writes_review_and_learnings_accumulate(ws, capsys):
    cfg = _cfg(ws)
    q = queue.Queue(cfg.state_dir)
    _job(q, "s1", state="submitted")
    assert cli.main(["learn", "UN", "portals", "need", "a", "P11", "profile", "first"]) == 0
    path, text = retro.review(cfg, q, TODAY)
    assert path.name == "2026-03-10.md" and "## Reply rate by segment" in text
    assert "UN portals need a P11 profile first" in text
    assert retro.learnings(cfg)[-1].startswith("- 2026-")


# ---------------------------------------------------------------- inbox

@pytest.mark.parametrize("subject,body,kind", [
    ("Your application", "Unfortunately we have decided to move forward with other candidates.", "rejected"),
    ("Interview", "We would like to invite you to an interview next week.", "interview"),
    ("Candidature", "Nous avons bien reçu votre candidature pour le poste.", "confirmation"),
    ("Next step", "Please complete the online test on HackerRank.", "assessment"),
    ("Offer", "We are pleased to offer you the position.", "offer"),
    ("Newsletter", "Our latest product news.", "other"),
])
def test_classify(subject, body, kind):
    assert inbox.classify(subject, body) == kind


def test_inbox_records_outcomes_only_for_a_single_match(ws, tmp_path, capsys):
    cfg = _cfg(ws)
    q = queue.Queue(cfg.state_dir)
    _job(q, "a1", employer="Acme Analytics", title="Data Scientist", req="R-5521", state="submitted")
    _job(q, "chk", employer="Globex", title="Analyst", state="needs_check")
    _job(q, "b1", employer="Initech", title="Analyst", state="submitted")
    _job(q, "b2", employer="Initech", title="Statistician", state="submitted")
    mails = tmp_path / "mail"
    mails.mkdir()
    (mails / "1.txt").write_text("From: talent@acme.example\nSubject: Update on R-5521\n\n"
                                 "Unfortunately we will not move forward.\n", encoding="utf-8")
    (mails / "2.txt").write_text("From: jobs@globex.example\nSubject: Globex - Analyst\n\n"
                                 "Thank you for applying to Globex.\n", encoding="utf-8")
    (mails / "3.txt").write_text("From: hr@initech.example\nSubject: Initech\n\n"
                                 "We would like to invite you to an interview.\n", encoding="utf-8")
    assert cli.main(["inbox", str(mails)]) == 0
    assert outcomes.load(cfg.state_dir) == []                     # dry run
    assert cli.main(["inbox", str(mails), "--apply"]) == 0
    res = json.loads(capsys.readouterr().out.split("\n[", 1)[1].rsplit("]", 1)[0].join("[]"))
    assert [r["recorded"] for r in res] == ["rejected", "submitted", "ambiguous: not recorded"]
    assert queue.Queue(cfg.state_dir).get("chk")["state"] == "submitted"


# ---------------------------------------------------------------- consistency

def test_consistency_reports_disagreements(ws, capsys):
    cfg = _cfg(ws)
    q = queue.Queue(cfg.state_dir)
    _job(q, "r1", state="ready_to_submit", deadline="2026-03-01")
    _job(q, "e1")
    outcomes.record(cfg.state_dir, "e1", "interview")
    outcomes.record(cfg.state_dir, "ghost", "reply")
    (ws / "packages" / "orphan").mkdir(parents=True)
    kinds = {p["kind"] for p in consistency.check(cfg, q, TODAY)}
    assert {"ready_without_package", "deadline_passed", "outcome_for_unsent", "outcome_unknown_job",
            "orphan_package"} <= kinds
    assert cli.main(["consistency"]) == 1


def test_consistency_is_clean_on_a_fresh_workspace(ws):
    assert cli.main(["consistency"]) == 0


# ---------------------------------------------------------------- phone

def test_phone_page_is_self_contained_and_has_no_contact_details(ws):
    cfg = _cfg(ws)
    raw = yaml.safe_load((ws / "jobveyra.yml").read_text(encoding="utf-8"))
    raw["candidate"].update(email="someone@example.com", phone="+1 555 0199")
    (ws / "jobveyra.yml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    cfg = _cfg(ws)
    q = queue.Queue(cfg.state_dir)
    _job(q, "s1", employer="Acme <script>", state="submitted")
    html = phone.render(cfg, q, TODAY)
    assert "someone@example.com" not in html and "555 0199" not in html
    assert "<script>alert" not in html and "Acme <script>" not in html.split('id="data">')[0]
    assert "http" not in re.sub(r'"url": "[^"]*"', "", html.split('id="data">')[1])     # no external resources
    assert 'name="viewport"' in html and "prefers-color-scheme:dark" in html
    assert cli.main(["phone"]) == 0 and (ws / "reports" / "phone.html").is_file()
