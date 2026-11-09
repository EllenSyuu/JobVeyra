"""The local web dashboard: every page and API route, the action endpoints, CSRF and origin
checks, read-only mode, loopback-only binding and HTML escaping. Offline: the server listens on
127.0.0.1 with a free port and the workspace is built from recorded fixtures."""
import http.client
import json
import threading
import urllib.parse
from pathlib import Path

import pytest
import yaml

from jobveyra import approvals, cli, config, queue
from jobveyra import outcomes as oc
from jobveyra.dashboard import markdown, server

FIX = Path(__file__).parent / "fixtures" / "sources"
EVIL = '<script>alert("x")</script> Labs'
EVIL_TITLE = '"><img src=x onerror=alert(1)> Analyst'


@pytest.fixture
def ws(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JOBVEYRA_HOME", str(tmp_path))
    monkeypatch.setenv("JOBQUEUE_NOW", "2026-03-10T09:00:00")
    assert cli.main(["init", str(tmp_path)]) == 0
    raw = yaml.safe_load((tmp_path / "jobveyra.yml").read_text())
    raw["candidate"]["name"] = "Alex Rivera"
    raw["sources"] = [{"type": "greenhouse", "board": "examplelabs"}, {"type": "lever", "board": "globex"}]
    raw["focus"]["regions"] = []
    raw["focus"]["exclude_titles"] = []
    raw["focus"]["seniority_min"], raw["focus"]["seniority_max"] = "intern", "executive"
    raw["policy"]["exclude_below"] = 0
    (tmp_path / "jobveyra.yml").write_text(yaml.safe_dump(raw))
    (tmp_path / "cv" / "master.md").write_text("# Alex Rivera\nPython, SQL, statistics, machine learning.\n")
    assert cli.main(["discover", "--offline", str(FIX)]) == 0
    assert cli.main(["evaluate"]) == 0
    q = queue.Queue(tmp_path / "state")
    for j in q.all("eligible"):
        pkg = tmp_path / "packages" / j["id"].replace(":", "_")
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "cover.md").write_text("I have used Python and SQL.")
        q.package_built(j["id"], str(pkg))
    ready = q.all("ready_to_submit")
    assert len(ready) >= 3, "the fixtures should give at least three ready jobs"
    # one confirmed submission with an interview, one uncertain result, one question on hold
    sub = ready[0]["id"]
    q.claim(owner="test", accept=lambda j: j["id"] == sub)
    q.clicked(sub)
    q.mark_submitted(sub, "Thanks for applying")
    oc.record(tmp_path / "state", sub, "interview", "first round")
    chk = ready[1]["id"]
    q.claim(owner="test", accept=lambda j: j["id"] == chk)
    q.mark_uncertain(chk, "no confirmation page")
    hold = ready[2]["id"]
    q.block(hold, "hold:salary expectations")
    # a hostile employer name and title from a scraped page
    evil, _ = q.upsert({"employer": EVIL, "title": EVIL_TITLE, "url": "https://jobs.example.com/evil",
                        "source": "jsonld", "location": "<b>Remote</b>"})
    q.screen(evil, 60)
    q.close()
    capsys.readouterr()
    return {"root": tmp_path, "submitted": sub, "check": chk, "hold": hold, "evil": evil}


class Client:
    def __init__(self, srv):
        self.srv = srv
        self.port = srv.server_address[1]
        self.token = srv.dashboard.csrf

    def request(self, method, path, body=None, *, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        payload = None
        if body is not None:
            payload = body if isinstance(body, (bytes, str)) else json.dumps(body)
            if isinstance(payload, str):
                payload = payload.encode()
            h.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=payload, headers=h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), data.decode("utf-8", "replace")

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def get_json(self, path):
        status, _h, text = self.get(path)
        assert status == 200, text
        return json.loads(text)

    def post(self, path, body, *, token=True, headers=None, **kw):
        h = dict(headers or {})
        if token:
            h["X-CSRF-Token"] = self.token if token is True else token
        return self.request("POST", path, body, headers=h, **kw)


def _serve(root, **kw):
    srv = server.make_server(root, "127.0.0.1", 0, **kw)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    return srv, t


@pytest.fixture
def client(ws):
    srv, t = _serve(ws["root"])
    yield Client(srv)
    srv.shutdown()
    srv.server_close()
    t.join(5)


def path_of(jid):
    return "/job/" + urllib.parse.quote(jid, safe="")


def state_of(ws, jid):
    q = queue.Queue(ws["root"] / "state")
    try:
        return q.get(jid)["state"]
    finally:
        q.close()


# ---------------------------------------------------------------- pages and API

@pytest.mark.parametrize("path", ["/", "/queue", "/review", "/insights", "/queue?state=needs_check&sort=employer"])
def test_pages_render(client, path):
    status, headers, text = client.get(path)
    assert status == 200, text[-600:]
    assert headers["Content-Type"].startswith("text/html")
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert f'<meta name="csrf-token" content="{client.token}">' in text
    assert "Submission: batch approve" in text


def test_overview_numbers_and_attention(client, ws):
    status, _h, text = client.get("/")
    assert "Needs attention" in text and "Coming up" in text
    assert "<svg" in text and "Applications sent per day" in text
    assert path_of(ws["check"]) in text and path_of(ws["hold"]) in text
    dg = client.get_json("/api/digest")
    assert dg["totals"]["submitted"] == 1 and dg["totals"]["interviews"] == 1
    assert dg["needs"]["needs_check"] == 1 and dg["needs"]["human"] == 1
    assert len(dg["series"]) == 14
    assert [j["id"] for j in dg["attention"]["needs_check"]] == [ws["check"]]


def test_queue_page_and_jobs_api(client, ws):
    jobs = client.get_json("/api/jobs")["jobs"]
    ids = {j["id"] for j in jobs}
    assert {ws["submitted"], ws["check"], ws["hold"], ws["evil"]} <= ids
    held = next(j for j in jobs if j["id"] == ws["hold"])
    assert held["state"] == "blocked_human" and held["reason"] == "hold:salary expectations"
    _s, _h, text = client.get("/queue")
    assert 'id="f-state"' in text and 'label for="f-state"' in text
    assert "hold:salary expectations" in text and held["action"] in text
    _s, _h, filtered = client.get("/queue?state=blocked_human")
    assert f"Showing 1 of {len(jobs)} jobs" in filtered


def test_job_detail_page_and_api(client, ws):
    jid = ws["submitted"]
    status, _h, text = client.get(path_of(jid))
    assert status == 200
    assert "Evaluation" in text and '<table class="md-table">' in text   # the Markdown report as a table
    assert "Cached posting text" in text
    assert "first round" in text                                         # the outcome note
    assert 'action="/api/outcome"' in text
    d = client.get_json("/api/job/" + urllib.parse.quote(jid, safe=""))
    assert d["job"]["state"] == "submitted"
    assert [e["to"] for e in d["events"]][-1] == "submitted"
    assert d["outcomes"][0]["outcome"] == "interview"
    assert d["evaluation"]["job_id"] == jid and d["posting"]["text"]
    _s, _h, chk = client.get(path_of(ws["check"]))
    assert 'action="/api/check"' in chk and "Found on the portal" in chk


def test_unknown_job_and_route(client):
    assert client.get("/job/nope:missing")[0] == 404
    assert client.get("/api/job/nope%3Amissing")[0] == 404
    assert client.get("/api/job/" + "x" * 400)[0] == 404
    assert client.get("/does-not-exist")[0] == 404
    status, _h, text = client.get("/api/nothing")
    assert status == 404 and json.loads(text)["ok"] is False


def test_insights(client):
    ins = client.get_json("/api/insights")
    assert ins["funnel"]["counts"]["submitted"] == 1
    assert {"buckets", "brier", "auc", "recommendation"} <= set(ins["calibration"])
    assert ins["patterns"] and {"low", "high", "signal"} <= set(ins["patterns"][0])
    assert ins["skills"]["postings"] >= 1 and ins["skills"]["demand"]
    _s, _h, text = client.get("/insights")
    assert "Score calibration" in text and "Brier score" in text and "95% interval" in text
    assert "Positive-response rate by fit bucket" in text


def test_review_api(client):
    r = client.get_json("/api/review")
    assert r["policy"]["submission"] == "batch_approve"
    assert r["ready"] >= 1 and r["staged"] == [] and r["live"] == []


def test_static_assets(client):
    status, headers, css = client.get("/static/dashboard.css")
    assert status == 200 and headers["Content-Type"].startswith("text/css") and "prefers-color-scheme: dark" in css
    status, headers, js = client.get("/static/dashboard.js")
    assert status == 200 and "X-CSRF-Token" in js
    assert client.get("/static/fonts/inter-latin-400-normal.woff2")[0] == 200
    assert client.get("/static/../server.py")[0] == 404
    assert client.get("/static/fonts/../../cli.py")[0] == 404


# ---------------------------------------------------------------- escaping

def test_malicious_employer_is_escaped_everywhere(client, ws):
    pages = ["/", "/queue", path_of(ws["evil"]), "/review", "/insights"]
    for p in pages:
        status, _h, text = client.get(p)
        assert status == 200, p
        assert "<script>alert" not in text, p
        assert "<img src=x" not in text, p
        assert "<b>Remote</b>" not in text, p
    _s, _h, queue_page = client.get("/queue")
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; Labs" in queue_page
    assert "&quot;&gt;&lt;img src=x onerror=alert(1)&gt; Analyst" in queue_page
    status, _h, raw = client.get("/job/%3Cscript%3E")
    assert status == 404 and "<script>" not in raw.replace('<script src="/static/dashboard.js" defer></script>', "")


def test_markdown_renderer_is_safe():
    md = ("# Title <b>x</b>\n\n**Fit 70/100** · `code<>` [ok](https://example.com/a?b=1&c=2) "
          "[bad](javascript:alert(1)) [worse](javascript:void0) https://example.org/x.\n\n| A | B |\n|---|---:|\n| <i>1</i> | 2 |\n\n"
          "- one\n- **two**\n\n1. first\n2. second\n\n<script>alert(1)</script>\n")
    out = markdown.render(md)
    assert "<h2>Title &lt;b&gt;x&lt;/b&gt;</h2>" in out
    assert "<strong>Fit 70/100</strong>" in out and "<code>code&lt;&gt;</code>" in out
    assert 'href="https://example.com/a?b=1&amp;c=2"' in out
    assert 'href="javascript' not in out and "<a" not in out.split("worse")[0].rsplit("</a>", 1)[-1]
    assert " worse " in out                                   # the label stays, the link goes
    assert '<a href="https://example.org/x" rel="noopener noreferrer">https://example.org/x</a>.' in out
    assert '<th scope="col" class="num">B</th>' in out and "<td>&lt;i&gt;1&lt;/i&gt;</td>" in out
    assert "<ul><li>one</li><li><strong>two</strong></li></ul>" in out
    assert "<ol><li>first</li><li>second</li></ol>" in out
    assert "<script>" not in out and "&lt;script&gt;alert(1)&lt;/script&gt;" in out


# ---------------------------------------------------------------- CSRF, origin, host

def test_post_without_csrf_token_is_refused(client, ws):
    body = {"id": ws["submitted"], "outcome": "offer"}
    status, _h, text = client.post("/api/outcome", body, token=False)
    assert status == 403 and "CSRF" in json.loads(text)["error"]
    status, _h, _t = client.post("/api/outcome", body, token="wrong-token")
    assert status == 403
    assert [r["outcome"] for r in oc.load(ws["root"] / "state")] == ["interview"]
    status, _h, text = client.post("/api/outcome", body)
    assert status == 200 and json.loads(text)["recorded"]["outcome"] == "offer"
    assert [r["outcome"] for r in oc.load(ws["root"] / "state")] == ["interview", "offer"]


@pytest.mark.parametrize("action", ["outcome", "block", "unblock", "check", "stage", "approve", "revoke"])
def test_every_action_needs_the_token(client, action):
    status, _h, _t = client.post(f"/api/{action}", {"id": "x", "batch": "b1"}, token=False)
    assert status == 403


def test_cross_origin_and_bad_host_are_refused(client, ws):
    body = {"id": ws["hold"]}
    status, _h, text = client.post("/api/unblock", body, headers={"Origin": "http://evil.example"})
    assert status == 403 and "cross-origin" in json.loads(text)["error"]
    status, _h, _t = client.post("/api/unblock", body, headers={"Origin": "null"})
    assert status == 403
    status, _h, _t = client.post("/api/unblock", body, headers={"Referer": "http://evil.example/page"})
    assert status == 403
    assert state_of(ws, ws["hold"]) == "blocked_human"
    assert client.get("/", host="evil.example")[0] == 421                    # DNS rebinding
    assert client.get("/api/jobs", host=f"evil.example:{client.port}")[0] == 421
    assert client.post("/api/unblock", body, host="evil.example")[0] == 421
    status, _h, _t = client.post("/api/unblock", body, headers={"Origin": f"http://127.0.0.1:{client.port}"})
    assert status == 200 and state_of(ws, ws["hold"]) == "ready_to_submit"
    assert client.get("/", host=f"localhost:{client.port}")[0] == 200


def test_form_post_redirects_back(client, ws):
    nxt = path_of(ws["submitted"])
    form = urllib.parse.urlencode({"csrf": client.token, "id": ws["submitted"], "outcome": "reply",
                                   "note": "", "next": nxt})
    status, headers, _t = client.request("POST", "/api/outcome", form,
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert status == 303 and headers["Location"] == nxt
    bad = urllib.parse.urlencode({"csrf": client.token, "id": ws["submitted"], "outcome": "reply",
                                  "next": "//evil.example/"})
    status, headers, _t = client.request("POST", "/api/outcome", bad,
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert status == 303 and headers["Location"] == "/"
    status, headers, text = client.request("POST", "/api/outcome", urllib.parse.urlencode({"id": ws["submitted"]}),
                                           headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert status == 403 and headers["Content-Type"].startswith("text/html") and "CSRF" in text


# ---------------------------------------------------------------- actions

def test_block_and_unblock(client, ws):
    jid = ws["evil"]
    status, _h, text = client.post("/api/block", {"id": jid, "reason": "hold:needs a portfolio link"})
    assert status == 200 and json.loads(text)["state"] == "blocked_human"
    status, _h, text = client.post("/api/unblock", {"id": jid})
    assert status == 200 and json.loads(text)["unblocked"] == [jid]
    assert client.post("/api/unblock", {"id": jid})[0] == 409                  # not blocked any more
    assert client.post("/api/block", {"id": jid, "reason": ""})[0] == 400
    assert client.post("/api/block", {"id": jid, "reason": "has spaces: x"})[0] == 400
    assert client.post("/api/block", {"id": ws["submitted"], "reason": "captcha"})[0] == 409
    assert client.post("/api/block", {"id": "nobody:here", "reason": "captcha"})[0] == 404


def test_outcome_validation(client, ws):
    assert client.post("/api/outcome", {"id": ws["submitted"], "outcome": "accepted!"})[0] == 400
    assert client.post("/api/outcome", {"id": "unknown:job", "outcome": "reply"})[0] == 404
    assert client.post("/api/outcome", {"outcome": "reply"})[0] == 400
    assert client.post("/api/outcome", {"id": ws["submitted"], "outcome": "reply", "note": "a\x00b"})[0] == 400
    assert client.post("/api/outcome", "[1, 2]")[0] == 400
    assert client.post("/api/outcome", "{not json")[0] == 400


def test_resolve_check_not_found_then_found(client, ws):
    jid = ws["check"]
    status, _h, text = client.post("/api/check", {"id": jid, "found": False})
    assert status == 200 and json.loads(text)["state"] == "ready_to_submit"
    assert client.post("/api/check", {"id": jid, "found": True})[0] == 409     # no longer needs_check
    q = queue.Queue(ws["root"] / "state")
    q.claim(owner="test", accept=lambda j: j["id"] == jid)
    q.mark_uncertain(jid, "timeout")
    q.close()
    status, _h, text = client.post("/api/check", {"id": jid, "found": "1", "evidence": "listed under My Applications"})
    assert status == 200 and json.loads(text)["state"] == "submitted"
    q = queue.Queue(ws["root"] / "state")
    assert q.get(jid)["confirmation"] == "listed under My Applications"
    q.close()
    assert client.post("/api/check", {"id": ws["hold"], "found": "maybe"})[0] == 409


def test_stage_approve_with_exclusion_and_revoke(client, ws):
    q = queue.Queue(ws["root"] / "state")
    q.package_built(ws["evil"], str(ws["root"] / "packages" / "evil"))
    q.close()
    status, _h, text = client.post("/api/stage", {})
    assert status == 200
    st = json.loads(text)
    batch, ids = st["batch"], st["jobs"]
    assert batch and ids and Path(st["review_page"]).is_file()
    r = client.get_json("/api/review")
    assert [b["batch"] for b in r["staged"]] == [batch]
    _s, _h, page = client.get("/review")
    assert f'value="{batch}"' in page and 'name="exclude"' in page and "Approve batch" in page

    assert client.post("/api/approve", {"batch": "b-missing"})[0] == 404
    assert client.post("/api/approve", {"batch": batch, "exclude": ["not:in-batch"]})[0] == 400
    assert client.post("/api/approve", {"batch": "../etc"})[0] == 400
    assert len(ids) >= 2
    assert client.post("/api/approve", {"batch": batch, "exclude": ids})[0] == 409   # nothing left
    leave_out = ids[0]
    status, _h, text = client.post("/api/approve", {"batch": batch, "exclude": [leave_out]})
    assert status == 200 and json.loads(text)["excluded"] == [leave_out]

    cfg = config.load(ws["root"])
    q = queue.Queue(cfg.state_dir)
    live = approvals.live(cfg.state_dir)
    covered = {jid for rec in live for jid, _h in rec["items"]}
    assert leave_out not in covered and set(ids[1:]) <= covered
    assert approvals.allowed(q.get(ids[1]), cfg)[0] is True
    assert approvals.allowed(q.get(leave_out), cfg)[0] is False
    assert live[0]["by"] == "Alex Rivera"
    q.close()
    r = client.get_json("/api/review")
    assert r["staged"] == [] and [b["batch"] for b in r["live"]] == [batch]

    status, _h, _t = client.post("/api/revoke", {"batch": batch})
    assert status == 200 and approvals.live(cfg.state_dir) == []
    assert client.post("/api/revoke", {"batch": "b-unknown"})[0] == 404
    assert client.post("/api/approve", {"batch": batch})[0] == 409            # revoked: stage again


def test_stage_and_approve_follow_the_policy(ws):
    raw = yaml.safe_load((ws["root"] / "jobveyra.yml").read_text())
    raw["policy"]["submission"] = "fill_only"
    (ws["root"] / "jobveyra.yml").write_text(yaml.safe_dump(raw))
    srv, t = _serve(ws["root"])
    c = Client(srv)
    try:
        status, _h, text = c.post("/api/stage", {})
        assert status == 409 and "fill_only" in json.loads(text)["error"]
        _s, _h, page = c.get("/review")
        assert "<code>fill_only</code>" in page and "Forms are filled and stop before Submit" in page
        assert 'action="/api/stage"' not in page
        assert "Submission: fill only" in c.get("/")[2]
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(5)


def test_no_endpoint_submits_or_handles_credentials():
    from jobveyra.dashboard import data
    assert set(data.ACTIONS) == {"outcome", "block", "unblock", "check", "stage", "approve", "revoke"}
    src = (Path(server.__file__).parent / "data.py").read_text() + Path(server.__file__).read_text()
    for forbidden in ("claim(", "clicked(", "worker", "password", "release_auth"):
        assert forbidden not in src.replace("never submits", ""), forbidden


# ---------------------------------------------------------------- read-only and binding

def test_read_only_mode(ws):
    srv, t = _serve(ws["root"], read_only=True)
    c = Client(srv)
    try:
        status, _h, text = c.post("/api/unblock", {"id": ws["hold"]})
        assert status == 403 and "read-only" in json.loads(text)["error"]
        assert c.post("/api/stage", {})[0] == 403
        assert state_of(ws, ws["hold"]) == "blocked_human"
        _s, _h, page = c.get(path_of(ws["hold"]))
        assert "Read-only mode" in page and "data-api" not in page
        _s, _h, review = c.get("/review")
        assert "data-api" not in review and "Read-only" in review
        assert c.get_json("/api/jobs")["jobs"]
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(5)


def test_loopback_only_unless_explicit(ws):
    assert server.is_loopback("127.0.0.1") and server.is_loopback("::1") and server.is_loopback("localhost")
    assert not server.is_loopback("0.0.0.0") and not server.is_loopback("192.168.1.20")
    with pytest.raises(ValueError, match="non-loopback"):
        server.check_host("0.0.0.0", explicit=False)
    with pytest.raises(ValueError):
        server.make_server(ws["root"], "0.0.0.0", 0)
    assert server.check_host("127.0.0.1", explicit=False) == ""
    assert "warning" in server.check_host("0.0.0.0", explicit=True)


class _FakeServer:
    def __init__(self, url):
        self.dashboard = type("D", (), {"url": url})()
        self.served = False

    def serve_forever(self):
        self.served = True

    def server_close(self):
        pass


def test_cli_dashboard_command(ws, monkeypatch, capsys):
    calls = []

    def fake_make(workspace, host, port, *, explicit_host, read_only):
        calls.append((Path(workspace), host, port, explicit_host, read_only))
        return _FakeServer(f"http://{host}:{port or 8765}/")

    opened = []
    monkeypatch.setattr(server, "make_server", fake_make)
    monkeypatch.setattr(server.webbrowser, "open", lambda url: opened.append(url))
    assert cli.main(["dashboard", "--no-browser", "--read-only"]) == 0
    out = capsys.readouterr()
    assert "dashboard: http://127.0.0.1:8765/" in out.out and "read-only" in out.out and not out.err
    assert calls[-1] == (ws["root"], "127.0.0.1", 8765, False, True) and opened == []

    assert cli.main(["dashboard", "--host", "0.0.0.0", "--port", "9000"]) == 0
    out = capsys.readouterr()
    assert "warning" in out.err and "0.0.0.0" in out.err
    assert calls[-1][1:4] == ("0.0.0.0", 9000, True) and opened == ["http://0.0.0.0:9000/"]


def test_cli_dashboard_starts_a_real_server(ws, monkeypatch, capsys):
    seen = {}

    def stop_at_once(self, *a, **kw):
        seen["port"] = self.server_address[1]
        seen["host"] = self.server_address[0]

    monkeypatch.setattr(server._Server, "serve_forever", stop_at_once)
    assert cli.main(["dashboard", "--port", "0", "--no-browser"]) == 0
    out = capsys.readouterr().out
    assert seen["host"] == "127.0.0.1" and f"http://127.0.0.1:{seen['port']}/" in out
