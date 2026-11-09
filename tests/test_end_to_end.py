"""The whole loop through the CLI, offline: init, discover, evaluate, package, review, approve,
next, clicked, done, outcome, digest. Also the three submission policies."""
import json
from pathlib import Path

import pytest
import yaml

from jobveyra import approvals, cli, config, queue

FIX = Path(__file__).parent / "fixtures" / "sources"


def run(*args, capsys=None):
    code = cli.main(list(args))
    out = capsys.readouterr().out if capsys else ""
    return code, out


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBVEYRA_HOME", str(tmp_path))
    monkeypatch.setenv("JOBQUEUE_NOW", "2026-03-10T09:00:00")
    assert cli.main(["init", str(tmp_path)]) == 0
    raw = yaml.safe_load((tmp_path / "jobveyra.yml").read_text())
    raw["sources"] = [{"type": "greenhouse", "board": "examplelabs"}, {"type": "lever", "board": "globex"}]
    raw["focus"]["regions"] = []
    raw["focus"]["exclude_titles"] = []
    raw["focus"]["seniority_min"], raw["focus"]["seniority_max"] = "intern", "executive"
    raw["policy"]["exclude_below"] = 0
    (tmp_path / "jobveyra.yml").write_text(yaml.safe_dump(raw))
    (tmp_path / "cv" / "master.md").write_text("# Alex Rivera\nPython, SQL, statistics, machine learning, "
                                                 "forecasting, experimentation. 2019 to 2025 at Example Corp.\n")
    return tmp_path


def _set_policy(ws, mode):
    raw = yaml.safe_load((ws / "jobveyra.yml").read_text())
    raw["policy"]["submission"] = mode
    (ws / "jobveyra.yml").write_text(yaml.safe_dump(raw))


def _pipeline(ws, capsys):
    assert run("discover", "--offline", str(FIX), capsys=capsys)[0] == 0
    code, out = run("evaluate", capsys=capsys)
    assert code == 0
    q = queue.Queue(ws / "state")
    eligible = q.all("eligible")
    assert eligible, json.loads(out)
    for j in eligible:
        pkg = ws / "packages" / j["id"].replace(":", "_")
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "cover.md").write_text("I have used Python and SQL since 2019.")
        assert run("package", j["id"], str(pkg), capsys=capsys)[0] == 0
    return queue.Queue(ws / "state")


def test_doctor_on_a_fresh_workspace(ws, capsys):
    code, out = run("doctor", capsys=capsys)
    assert "policy: batch_approve" in out


def test_batch_approve_loop(ws, capsys):
    q = _pipeline(ws, capsys)
    ready = q.all("ready_to_submit")
    assert ready
    code, out = run("next", capsys=capsys)
    assert "wait for approval" in out                     # nothing may run before review
    code, out = run("review", capsys=capsys)
    batch = out.split()[1].rstrip(":")
    assert (ws / "reports" / f"review-{batch}.html").exists()
    assert run("approve", batch, capsys=capsys)[0] == 0
    code, out = run("next", capsys=capsys)
    card = json.loads(out)
    assert card["may_submit"] is True
    run("clicked", card["id"], capsys=capsys)
    run("done", card["id"], "--confirmation", "Thanks for applying", capsys=capsys)
    assert queue.Queue(ws / "state").get(card["id"])["state"] == "submitted"
    run("outcome", card["id"], "interview", capsys=capsys)
    code, out = run("digest", "--json", capsys=capsys)
    dg = json.loads(out)
    assert dg["totals"]["submitted"] == 1 and dg["totals"]["interviews"] == 1


def test_changed_posting_needs_new_approval(ws, capsys):
    q = _pipeline(ws, capsys)
    _code, out = run("review", capsys=capsys)
    batch = out.split()[1].rstrip(":")
    run("approve", batch, capsys=capsys)
    cfg = config.load(ws)
    job = q.all("ready_to_submit")[0]
    assert approvals.allowed(job, cfg)[0]
    q.update_meta(job["id"], content_hash="changed")
    assert approvals.allowed(queue.Queue(ws / "state").get(job["id"]), cfg) == (
        False, "posting changed after approval; review it again")


def test_auto_and_fill_only(ws, capsys):
    _pipeline(ws, capsys)
    _set_policy(ws, "auto")
    card = json.loads(run("next", capsys=capsys)[1])
    assert card["may_submit"] is True
    _set_policy(ws, "fill_only")
    card = json.loads(run("next", capsys=capsys)[1])
    assert card["may_submit"] is False
    assert any("stop before Submit" in r for r in card["rules"])


def test_daily_cap(ws, capsys):
    _pipeline(ws, capsys)
    raw = yaml.safe_load((ws / "jobveyra.yml").read_text())
    raw["policy"].update(submission="auto", max_per_day=1)
    (ws / "jobveyra.yml").write_text(yaml.safe_dump(raw))
    card = json.loads(run("next", capsys=capsys)[1])
    run("clicked", card["id"], capsys=capsys)
    run("done", card["id"], "--confirmation", "ok", capsys=capsys)
    out = json.loads(run("next", capsys=capsys)[1])
    assert "daily cap" in out["idle"]


def test_check_materials_blocks_invented_numbers(ws, capsys):
    pkg = ws / "packages" / "x"
    pkg.mkdir(parents=True)
    (pkg / "cover.md").write_text("I grew revenue by 340% at Initech in 2017.")
    code, out = run("check-materials", str(pkg), capsys=capsys)
    assert code == 1 and "BLOCK" in out


def test_init_writes_agent_rules_and_they_match_the_repo(ws):
    repo = Path(__file__).resolve().parent.parent
    assert (ws / "AGENTS.md").read_text() == (repo / "AGENTS.md").read_text()
    assert (repo / "src/jobveyra/templates/AGENTS.md").read_text() == (repo / "AGENTS.md").read_text()
