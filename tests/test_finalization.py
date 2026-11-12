"""The last page of an application: finalize policy, holding pen and duplicate-safe submits.

A mocked portal stands in for the browser; nothing is submitted anywhere."""
import json

import pytest

from jobveyra import board, cli, config, consistency, finalize, queue

DECL = {"kind": "accuracy_declaration", "required": True,
        "text": "I certify that the information provided in this application is true and complete."}
TERMS = {"kind": "terms", "required": True, "text": "I accept the Data Privacy Statement"}
ANSWERS = [{"kind": "answer", "text": "Salary expectation", "source": "answers"}]
SUBMIT = {"kind": "submit", "text": "Apply"}
WORDS = "Alex Rivera, 2026-03-10: I agree to every application's accuracy statement and required terms"


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBVEYRA_HOME", str(tmp_path))
    monkeypatch.setenv("JOBQUEUE_NOW", "2026-03-10T09:00:00")
    assert cli.main(["init", str(tmp_path)]) == 0
    cfg = config.load(tmp_path)
    queue.configure(cfg)
    return cfg


def _ready(q, jid, url=None):
    url = url or f"https://jobs.lever.co/globex/{jid}"
    q.upsert({"id": jid, "employer": "Globex", "title": "Data Scientist", "url": url, "apply_url": url})
    q.screen(jid, 75, reason="test")
    q.package_built(jid, f"packages/{jid}")
    return jid


def _lease(q, jid):
    j = q.claim(owner="t", accept=lambda x: x["id"] == jid)
    assert j and j["id"] == jid
    return j


class Portal:
    def __init__(self):
        self.presses = []

    def run(self, q, jid, page, *, confirm=True):
        out = finalize.finalize(q, jid, page, page="https://example.org/review", saved="draft_saved", recon="yes")
        if out["click"]:
            self.presses.append(jid)
            if confirm:
                q.mark_submitted(jid, "Thank you for applying")
            else:
                q.mark_uncertain(jid, "no confirmation page")
        return out


def test_completed_form_without_consent_is_parked_and_the_batch_continues(ws):
    q = queue.Queue(ws.state_dir)
    a, b = _ready(q, "a"), _ready(q, "b")
    p = Portal()
    _lease(q, a)
    out = p.run(q, a, ANSWERS + [DECL, TERMS, SUBMIT])
    assert out["decision"] == "parked" and not out["click"]
    j = q.get(a)
    assert (j["state"], j["final_stage"]) == ("blocked_human", queue.AWAITING_FINAL)
    assert j["final_page"] and j["final_need"] and j["recovery"] and j["form_saved"] == "draft_saved"
    assert queue.holding_category(j) == "FINAL APPROVAL REQUIRED"
    _lease(q, b)
    assert p.run(q, b, ANSWERS + [SUBMIT])["click"]
    assert p.presses == [b]
    assert q.all("in_progress") == []


def test_standing_consent_ticks_and_releases_parked_jobs(ws):
    q = queue.Queue(ws.state_dir)
    a = _ready(q, "a")
    _lease(q, a)
    Portal().run(q, a, [DECL, TERMS, SUBMIT])
    assert finalize.authorize_consent(q, "accuracy_declaration", WORDS) == []          # terms still uncovered
    assert finalize.authorize_consent(q, "application_terms", WORDS) == [a]
    assert q.get(a)["state"] == "ready_to_submit"
    _lease(q, a)
    p = Portal()
    out = p.run(q, a, [DECL, TERMS, SUBMIT])
    assert out["click"] and DECL["text"] in out["tick"]
    assert q.get(a)["final_stage"] == queue.SUBMISSION_CONFIRMED


def test_board_approval_is_authorization_not_submission(ws):
    q = queue.Queue(ws.state_dir)
    a = _ready(q, "a")
    _lease(q, a)
    Portal().run(q, a, [DECL, SUBMIT])
    body = board.render(ws, q)
    line = next(x for x in body.splitlines() if "jv:final:" in x)
    board.apply(ws, q, line.replace("[ ]", "[x]"))
    j = q.get(a)
    assert j["state"] == "ready_to_submit" and "board" in j["final_grant"]
    _lease(q, a)
    assert Portal().run(q, a, [DECL, SUBMIT])["click"]


def test_false_required_declaration_excludes_without_asking(ws):
    (ws.state_dir / "claims.json").write_text(json.dumps(
        [{"pattern": r"\b(citizen|permanent resident)\b", "true": False, "why": "not a citizen (fact base)"}]))
    q = queue.Queue(ws.state_dir)
    finalize.grant("accuracy_declaration", WORDS, q.dir)
    a = _ready(q, "a")
    _lease(q, a)
    out = Portal().run(q, a, [{"kind": "accuracy_declaration", "required": True,
                              "text": "I declare that I am a citizen or permanent resident"}, SUBMIT])
    assert out["decision"] == "excluded"
    assert q.get(a)["state"] == "excluded" and q.get(a)["reason"].startswith("ineligible:")
    assert queue.holding_category(q.get(a)) == ""
    opt = finalize.decide([{"kind": "accuracy_declaration", "required": False, "text": "I am a citizen"}, DECL],
                          {"accuracy_declaration": {}}, claims=finalize.known_claims(q.dir))
    assert opt["decision"] == "submit" and "I am a citizen" in opt["leave"]


def test_unknown_claims_unverified_answers_and_platform_walls(ws):
    c = {"accuracy_declaration": {}, "application_terms": {}}
    assert finalize.decide([{"kind": "accuracy_declaration", "text": "I have 5+ years of experience"}], c, claims=[])["kind"] == "unknown_claim"
    assert finalize.decide([{"kind": "answer", "source": "unverified"}, DECL], c, claims=[])["kind"] == "unverified_answers"
    assert finalize.decide([{"kind": "captcha"}], c, claims=[])["decision"] == "technical"
    assert finalize.decide([{"kind": "mfa"}], c, claims=[])["decision"] == "auth"
    assert finalize.decide([DECL, {"kind": "chrome_permission"}], c, claims=[])["kind"] == "chrome_permission"
    assert finalize.decide([{"kind": "optional_consent", "text": "talent pool"}, DECL], c, claims=[])["decision"] == "submit"


def test_attempt_record_is_idempotent_and_crash_after_click_is_never_resubmitted(ws):
    q = queue.Queue(ws.state_dir)
    a = _ready(q, "a")
    _lease(q, a)
    assert q.begin_submit(a)["click"]
    assert q.begin_submit(a) == {"status": "already_attempted", "click": False, "attempt_id": q.get(a)["attempt_id"]}
    import os
    os.environ["JOBQUEUE_NOW"] = "2026-03-10T11:00:00"
    assert q.recover()["uncertain"] == [a]
    assert q.get(a)["final_stage"] == queue.SUBMISSION_UNCERTAIN
    assert q.claim(owner="t") is None
    assert q.resolve_check(a, found_on_portal=False, evidence="portal list: nothing for Globex") == "ready_to_submit"
    assert q.get(a)["prior_attempt_cleared"]
    _lease(q, a)
    assert q.begin_submit(a)["click"]


def test_unreconciled_attempt_blocks_a_second_click(ws):
    q = queue.Queue(ws.state_dir)
    a = _ready(q, "a")
    _lease(q, a)
    q.begin_submit(a)
    q.set_state(a, "blocked_technical", "x", reason="x", action="x", clicked=0)
    q.unblock(jid=a)
    _lease(q, a)
    assert q.begin_submit(a)["status"] == "check_portal"
    assert q.get(a)["state"] == "needs_check"


def test_manual_tick_needs_portal_evidence(ws):
    q = queue.Queue(ws.state_dir)
    a = _ready(q, "a")
    q.claim(owner="t"); q.block(a, "captcha")
    board.apply(ws, q, f"- [x] I applied myself <!-- jv:manual:{a} -->")
    assert (q.get(a)["state"], q.get(a)["evidence_level"]) == ("needs_check", "candidate_reported")


def test_migration_is_additive_idempotent_and_reversible(ws):
    rows = [{"id": "s:1", "employer": "Initech", "state": "submitted", "confirmation": "legacy: imported"},
            {"id": "s:2", "employer": "Globex", "state": "submitted", "confirmation": "Thank you"},
            {"id": "c:3", "employer": "Umbrella", "state": "needs_check", "reason": "uncertain:x", "action": "check"}]
    (ws.state_dir / "queue.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    q = queue.Queue(ws.state_dir)
    before = {j["id"]: (j["state"], j.get("confirmation")) for j in q.all()}
    assert q.migrate_finalization()
    assert q.get("s:1")["evidence_level"] == "legacy" and q.get("c:3")["final_stage"] == queue.SUBMISSION_UNCERTAIN
    assert q.migrate_finalization() == {}
    assert not [p for p in consistency.check(ws, q) if p["kind"].startswith("final")]
    q.rollback_finalization()
    text = (ws.state_dir / "queue.jsonl").read_text()
    assert not any(f'"{f}"' in text for f in queue.FINAL_FIELDS)
    assert {j["id"]: (j["state"], j.get("confirmation")) for j in queue.Queue(ws.state_dir).all()} == before


def test_cli_finalize_exit_codes(ws, capsys):
    q = queue.Queue(ws.state_dir)
    a = _ready(q, "a")
    _lease(q, a)
    assert cli.main(["finalize", a, "--elements", json.dumps([DECL, SUBMIT])]) == 5
    assert cli.main(["authorize", a, "--evidence", WORDS]) == 0
    _lease(queue.Queue(ws.state_dir), a)
    assert cli.main(["finalize", a, "--elements", json.dumps([DECL, SUBMIT])]) == 0
    assert cli.main(["holding"]) == 0
