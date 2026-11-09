"""Market packs, the stretch / out-of-reach check, sign-in handling and portal playbooks."""
import pytest
import yaml

from jobveyra import cli, config, markets, queue, signins
from jobveyra.evaluate import rubric
from jobveyra.models import Posting


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBVEYRA_HOME", str(tmp_path))
    monkeypatch.setenv("JOBQUEUE_NOW", "2026-03-10T09:00:00")
    assert cli.main(["init", str(tmp_path)]) == 0
    return tmp_path


def _cfg(ws, **changes):
    raw = yaml.safe_load((ws / "jobveyra.yml").read_text(encoding="utf-8"))
    for section, values in changes.items():
        raw.setdefault(section, {}).update(values)
    (ws / "jobveyra.yml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    cfg = config.load(ws)
    queue.configure(cfg)
    return cfg


def P(text="", title="Data Scientist", location="Montréal, QC", employment="full_time"):
    return Posting("greenhouse", "Example Co", title, "https://example.com/j/1", location=location,
                   employment=employment, text=text)


# ---------------------------------------------------------------- packs

def test_builtin_packs_load_and_validate():
    have = markets.available()
    assert {"canada-quebec", "united-states", "united-kingdom", "un-system"} <= set(have)
    markets.load(sorted(have))
    with pytest.raises(markets.PackError, match="verdict"):
        markets.parse({"name": "x", "rules": [{"id": "a", "match": "x", "verdict": "maybe"}]})
    with pytest.raises(markets.PackError, match="needs match"):
        markets.parse({"name": "x", "rules": [{"id": "a", "verdict": "flag"}]})
    with pytest.raises(markets.PackError, match="regex"):
        markets.parse({"name": "x", "rules": [{"id": "a", "match": "(", "verdict": "flag"}]})


def test_location_matching_uses_whole_tokens():
    us, ca = markets.load(["united-states", "canada-quebec"])
    assert us.applies("San Jose, CA") and not us.applies("Toronto, Canada")
    assert ca.applies("Montréal, QC") and ca.applies("Ottawa, ON, Canada") and not ca.applies("Bogotá, Colombia")


def test_status_tags_decide_citizenship_rules():
    ca = markets.load(["canada-quebec"])
    p = P("Applicants must be Canadian citizens or permanent residents at the time of application.")
    hits = markets.check(ca, p, [])
    assert hits[0]["rule"] == "citizen_or_pr_required" and hits[0]["verdict"] == "fail"
    assert "Canadian citizens" in hits[0]["quote"]
    assert not markets.check(ca, p, ["permanent_resident"])
    # a pack only applies to its own market
    assert not markets.check(ca, P(p.text, location="London, UK"), [])


def test_if_status_rules_apply_only_to_tagged_candidates():
    ca = markets.load(["canada-quebec"])
    p = P("We are unable to provide sponsorship for this role.")
    assert not [h for h in markets.check(ca, p, []) if h["rule"] == "no_lmia"]
    assert [h for h in markets.check(ca, p, ["needs_employer_permit"]) if h["rule"] == "no_lmia"]


def test_market_fail_excludes_and_flag_warns_in_the_evaluation(ws):
    cfg = _cfg(ws, focus={"markets": ["canada-quebec"]})
    ev = rubric.evaluate(P("Must be a Canadian citizen. Reliability status required."), cfg, job_id="j1")
    assert "market:citizen_or_pr_required" in ev.blockers and ev.lane == "excluded"
    assert "market:reliability_status" in ev.flags
    md = rubric.report_markdown(ev, P())
    assert "## Market rules" in md and "> Must be a Canadian citizen" in md


def test_unknown_market_is_a_config_error(ws):
    with pytest.raises(config.ConfigError, match="unknown market pack"):
        _cfg(ws, focus={"markets": ["atlantis"]})


def test_workspace_pack_overrides_and_extends(ws):
    (ws / "markets").mkdir()
    (ws / "markets" / "my-rules.yml").write_text(yaml.safe_dump({
        "name": "my-rules", "rules": [{"id": "short_contract", "match_employment": "contract|temporary",
                                        "verdict": "flag", "note": "short contract"}]}), encoding="utf-8")
    cfg = _cfg(ws, focus={"markets": ["my-rules"]})
    ev = rubric.evaluate(P("A role.", employment="contract"), cfg, job_id="j1")
    assert "market:short_contract" in ev.flags


def test_market_document_defaults_reach_the_letter():
    ca = markets.load(["canada-quebec"])
    d = markets.document_defaults(ca, "Montréal, QC", "fr")
    assert d["headings"]["experience"] == "Expérience professionnelle"
    assert d["salutation"] == "Madame, Monsieur," and d["guidance"]


# ---------------------------------------------------------------- reach

def test_titles_two_levels_above_are_out_of_reach(ws):
    cfg = _cfg(ws, candidate={"level": "junior"}, focus={"seniority_min": "intern", "seniority_max": "executive"})
    assert "out_of_reach:lead" in rubric.evaluate(P("x", title="Lead Data Scientist"), cfg, job_id="a").blockers
    ev = rubric.evaluate(P("x", title="Senior Data Scientist"), cfg, job_id="b")
    assert "out_of_reach:senior" in ev.blockers
    cfg = _cfg(ws, candidate={"level": "mid"})
    ev = rubric.evaluate(P("x", title="Senior Data Scientist"), cfg, job_id="c")
    assert "stretch:senior" in ev.flags and not ev.blockers


def test_required_years_beyond_experience(ws):
    cfg = _cfg(ws, candidate={"years_experience": 2})
    text = "Requirements\n- 7+ years of experience in data science is required\n"
    assert "out_of_reach:7y" in rubric.evaluate(P(text), cfg, job_id="a").blockers
    text = "Requirements\n- 3+ years of experience in data science is required\n"
    assert "stretch:3y" in rubric.evaluate(P(text), cfg, job_id="b").flags


def test_bad_candidate_level_is_rejected(ws):
    with pytest.raises(config.ConfigError, match="candidate.level"):
        _cfg(ws, candidate={"level": "wizard"})


# ---------------------------------------------------------------- sign-ins

def _blocked(ws, n=3):
    q = queue.Queue(ws / "state")
    for i, (url, dl) in enumerate([("https://acme.wd3.myworkdayjobs.com/en-US/Careers/job/A_1", "2026-03-20"),
                                   ("https://acme.wd3.myworkdayjobs.com/en-US/Careers/job/B_2", "2026-03-14"),
                                   ("https://globex.taleo.net/careersection/2/jobdetail.ftl?job=9", "")][:n]):
        jid = f"j{i}"
        q.upsert({"id": jid, "employer": f"E{i}", "title": "Analyst", "url": url, "apply_url": url, "deadline": dl})
        q.screen(jid, 80, reason="test")
        q.package_built(jid, f"packages/{jid}")
    q.block("j0", "auth:workday:acme")
    q.block("j2", "auth:taleo:globex")
    return queue.Queue(ws / "state")


def test_waiting_groups_by_scope_with_earliest_deadline_first(ws):
    _cfg(ws)
    rows = signins.waiting(_blocked(ws))
    assert [r["scope"] for r in rows] == ["workday:acme", "taleo:globex"]
    acme = rows[0]
    assert len(acme["jobs"]) == 2 and acme["earliest_deadline"] == "2026-03-14"
    assert acme["portal"] == "Workday" and acme["open"] == "https://acme.wd3.myworkdayjobs.com/Careers"


def test_signal_survives_until_verified_then_releases_jobs(ws, capsys):
    cfg = _cfg(ws)
    q = _blocked(ws)
    assert signins.pending(cfg.state_dir) == []
    assert cli.main(["signed-in", "workday:acme"]) == 0
    assert [s["scope"] for s in signins.pending(cfg.state_dir)] == ["workday:acme"]
    assert cli.main(["wait-signin", "--timeout", "0"]) == 0
    assert cli.main(["verify-auth", "workday:acme", "--failed", "login page shown"]) == 0
    assert signins.pending(cfg.state_dir) == []
    assert q.get("j0")["state"] == "blocked_auth"
    signins.signal(cfg.state_dir, "workday:acme")
    r = signins.verify(q, cfg.state_dir, "workday:acme", ok=True, evidence="email in header")
    assert sorted(r["released"]) == ["j0", "j1"]
    assert queue.Queue(ws / "state").get("j0")["state"] == "ready_to_submit"
    assert queue.Queue(ws / "state").get("j2")["state"] == "blocked_auth"


def test_wait_times_out_without_a_signal(ws):
    cfg = _cfg(ws)
    t = [0.0]
    out = signins.wait(cfg.state_dir, interval=10, timeout=25, sleep=lambda s: t.__setitem__(0, t[0] + s),
                       clock=lambda: t[0])
    assert out == [] and t[0] >= 25
    assert cli.main(["wait-signin", "--timeout", "0"]) == 2


def test_verify_auth_needs_exactly_one_outcome(ws, capsys):
    _cfg(ws)
    assert cli.main(["verify-auth", "workday:acme"]) == 1
    assert cli.main(["verify-auth", "workday:acme", "--ok", "a", "--failed", "b"]) == 1


def test_signins_command_prints_groups(ws, capsys):
    _cfg(ws)
    _blocked(ws)
    assert cli.main(["signins"]) == 0
    out = capsys.readouterr().out
    assert "Workday [workday:acme]: 2 waiting, earliest deadline 2026-03-14" in out
    assert "Create Account" in out


# ---------------------------------------------------------------- playbooks

def test_playbook_combines_general_portal_and_user_notes(ws, capsys):
    _cfg(ws)
    _blocked(ws)
    (ws / "playbooks").mkdir()
    (ws / "playbooks" / "workday.md").write_text("## My notes\n- Acme asks about relatives.\n", encoding="utf-8")
    assert cli.main(["playbook", "j0"]) == 0
    out = capsys.readouterr().out
    assert out.index("# Every portal") < out.index("# Workday") < out.index("Acme asks about relatives")
    assert signins.playbook_name("https://jobs.lever.co/x/1") == "lever"
    assert signins.playbook_name("https://example.org/careers") == ""


def test_markets_command_lists_and_shows(ws, capsys):
    _cfg(ws, focus={"markets": ["un-system"]})
    assert cli.main(["markets"]) == 0
    out = capsys.readouterr().out
    assert "* un-system" in out and "  canada-quebec" in out
    assert cli.main(["markets", "canada-quebec"]) == 0
    assert "citizen_or_pr_required" in capsys.readouterr().out
