import datetime as dt
import email
import email.policy
import json
import sys
import urllib.error
from pathlib import Path

import pytest
import yaml

from jobveyra import config
from jobveyra import outcomes as oc
from jobveyra import queue as qmod
from jobveyra.report import calendar, digest, newsletter, notify, status

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "jobveyra.yml"
TODAY = dt.date(2026, 3, 15)
WD = "https://globex.wd5.myworkdayjobs.com/en-US/careers/job/Lisbon/"


@pytest.fixture
def cfg(tmp_path):
    return config.from_dict(yaml.safe_load(EXAMPLE.read_text()), tmp_path)


def at(monkeypatch, ts):
    monkeypatch.setenv("JOBQUEUE_NOW", ts)


@pytest.fixture
def q(tmp_path, monkeypatch):
    """A queue built through the real API; times set via the queue clock."""
    at(monkeypatch, "2026-03-01T08:00:00")
    q = qmod.Queue(tmp_path / "state")

    def add(employer, title, url, fit, family="ds", source="greenhouse", deadline=""):
        jid, _ = q.upsert({"employer": employer, "title": title, "url": url, "source": source,
                           "family": family, "deadline": deadline})
        q.screen(jid, fit)
        return jid

    ids = {}
    ids["b"] = add("Globex", "Data Analyst", "https://jobs.lever.co/globex/" + "b" * 36, 60, "analytics", "lever")
    ids["c"] = add("Example Labs", "Data Scientist", "https://boards.greenhouse.io/examplelabs/jobs/1002", 76)
    ids["a"] = add("Example Labs", "Senior Data Scientist", "https://boards.greenhouse.io/examplelabs/jobs/1001", 80)
    ids["d"] = add("Globex", "Data Scientist", WD + "Data-Scientist_R-12345", 70, deadline="2026-03-20")
    ids["e"] = add("Globex", "Analyst", WD + "Analyst_R-12346", 55, "analytics", deadline="2026-03-18")
    ids["f"] = add("Example Labs", "ML Engineer", "https://boards.greenhouse.io/examplelabs/jobs/1003", 66)
    ids["g"] = add("Example Labs", "Analytics Lead", "https://boards.greenhouse.io/examplelabs/jobs/1004", 68,
                   "analytics", deadline="2026-03-25")
    ids["j"] = add("Globex", "Statistician", "https://boards.greenhouse.io/globex/jobs/2001", 58)
    ids["h"] = add("Globex", "Intern", "https://boards.greenhouse.io/globex/jobs/2002", 30)
    ids["i"], _ = q.upsert({"employer": "Globex", "title": "Researcher", "url": "https://boards.greenhouse.io/globex/jobs/2003",
                            "deadline": "2026-03-10"})

    q.mark_submitted(ids["b"], "Application received")
    at(monkeypatch, "2026-03-10T09:00:00")
    q.mark_submitted(ids["c"], "Thanks for applying")
    at(monkeypatch, "2026-03-14T09:00:00")
    q.mark_submitted(ids["a"], "Thanks for applying")
    q.block(ids["d"], "auth:workday:globex")                    # moves e (same sign-in) too
    q.block(ids["f"], "hold:visa question")
    q.package_built(ids["j"], "packages/j")
    q.claim()
    q.clicked(ids["j"])
    q.mark_uncertain(ids["j"], "no confirmation page")
    q.package_built(ids["g"], "packages/g")
    q.update_meta(ids["b"], tracker_row="7")                    # bumps updated_at; event log still wins

    oc.record(q.dir, ids["c"], "reply", at="2026-03-12T10:00:00")
    oc.record(q.dir, ids["c"], "interview", "first round", at="2026-03-14T10:00:00")
    oc.record(q.dir, ids["a"], "reply", at="2026-03-15T07:00:00")
    q.ids = ids
    return q


# ---------------------------------------------------------------- digest

def test_digest_numbers(cfg, q):
    dg = digest.build(cfg, q, TODAY)
    assert dg["date"] == "2026-03-15"
    t = dg["totals"]
    assert (t["submitted"], t["replies"], t["interviews"], t["offers"], t["reply_rate"]) == (3, 2, 1, 0, 67)
    assert dg["last7"] == 2
    assert len(dg["series"]) == 14 and dg["series"][-1]["date"] == "2026-03-15"
    sent = {s["date"]: s["sent"] for s in dg["series"]}
    assert sent["2026-03-10"] == 1 and sent["2026-03-14"] == 1 and sent["2026-03-02"] == 0
    assert sum(sent.values()) == 2                              # 03-01 is outside the 14 days
    assert [y["title"] for y in dg["yesterday"]] == ["Senior Data Scientist"]

    tracks = {r["track"]: r for r in dg["by_track"]}
    assert tracks["ds"] == {"track": "ds", "label": "Data science", "sent": 2, "replies": 2, "avg_fit": 78}
    assert tracks["analytics"]["sent"] == 1 and tracks["analytics"]["replies"] == 0

    n = dg["needs"]
    assert n["auth"] == [{"scope": "workday:globex", "count": 2, "best_fit": 70, "earliest_deadline": "2026-03-18",
                          "action": n["auth"][0]["action"]}]
    assert "workday:globex" in n["auth"][0]["action"]
    assert (n["human"], n["needs_check"], n["approvals_pending"]) == (1, 1, 1)

    dls = dg["coming_up"]["deadlines"]
    assert [(d["date"], d["days_left"]) for d in dls] == [("2026-03-18", 3), ("2026-03-20", 5), ("2026-03-25", 10)]
    fu = dg["coming_up"]["followups"]
    assert [f["employer"] for f in fu] == ["Globex"] and fu[0]["days_waiting"] == 14
    assert fu[0]["suggested_message"].rstrip().endswith("Alex Rivera")
    assert dg["flags"]["counts"]["deadline_passed"] == 1
    assert dg["funnel"]["counts"]["submitted"] == 3
    json.dumps(dg)                                              # plain data only


def test_digest_policy_changes_approvals(cfg, q):
    cfg.policy.submission = "auto"
    assert digest.build(cfg, q, TODAY)["needs"]["approvals_pending"] == 0


def test_digest_source_concentration_warning(cfg, tmp_path, monkeypatch):
    at(monkeypatch, "2026-03-14T09:00:00")
    q = qmod.Queue(tmp_path / "s2")
    for i in range(5):
        jid, _ = q.upsert({"employer": "Example Labs", "title": f"Role {i}", "source": "greenhouse",
                           "url": f"https://boards.greenhouse.io/examplelabs/jobs/{300 + i}"})
        q.screen(jid, 60)
        q.mark_submitted(jid, "ok")
    w = digest.build(cfg, q, TODAY)["flags"]["warnings"]
    assert any("greenhouse supplied 5 of 5" in x for x in w)


# ---------------------------------------------------------------- chart

def test_chart_frames(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    from jobveyra.report import chart
    series = [{"date": (TODAY - dt.timedelta(days=13 - k)).isoformat(), "sent": k % 4} for k in range(14)]
    light, dark = chart.render_pair(series, tmp_path)
    im = Image.open(light)
    assert im.size == (1200, 400)
    assert im.n_frames == 16
    first = im.convert("RGB").tobytes()
    im.seek(1)
    assert im.convert("RGB").tobytes() != first                 # the animation starts from empty bars
    im.seek(im.n_frames - 1)
    assert im.convert("RGB").tobytes() == first                 # frame 0 is the finished chart
    dk = Image.open(dark).convert("RGB")
    assert dk.getpixel((2, 2)) == (13, 17, 23)
    assert Image.open(light).convert("RGB").getpixel((2, 2)) == (255, 255, 255)


def test_chart_font_and_missing_pillow(monkeypatch):
    pytest.importorskip("PIL")
    from jobveyra.report import chart
    assert chart.font(600, 20) is not None
    monkeypatch.setitem(sys.modules, "PIL", None)
    with pytest.raises(ImportError, match="pip install"):
        chart.render([], "x.gif")


# ---------------------------------------------------------------- newsletter

def test_newsletter_build_files(cfg, q, tmp_path):
    pytest.importorskip("PIL")
    out = tmp_path / "news"
    res = newsletter.build(cfg, q, TODAY, out)
    assert res["charts"] is True
    for name in ("newsletter.html", "preview.html", "newsletter.txt", "chart.gif", "chart-dark.gif", "digest.json"):
        assert (out / name).is_file(), name
    assert res["subject"] == "Job search · Mar 15 · 3 submitted, 1 interview"
    html = (out / "newsletter.html").read_text()
    assert 'src="cid:chart"' in html and 'src="cid:chartdark"' in html
    assert "@media (prefers-color-scheme: dark)" in html and ".dark-img{display:none;}" in html
    assert 'class="dark-img"' in html and "display:none;max-height:0" in html
    assert 'role="presentation"' in html and "<table" in html
    assert "Sign in to workday:globex: 2 jobs waiting, best fit 70, earliest deadline Wed Mar 18" in html
    assert "1 application ready for your approval" in html
    assert "Data science" in html and "78 / 100" in html
    prev = (out / "preview.html").read_text()
    assert 'src="chart.gif"' in prev and 'src="chart-dark.gif"' in prev
    txt = (out / "newsletter.txt").read_text()
    assert "Submitted 3 · last 7 days 2 · replies 2 · interviews 1 · offers 0" in txt
    assert "Follow up · Globex, Data Analyst (14 days since applying)" in txt
    assert json.loads((out / "digest.json").read_text())["subject"] == res["subject"]


def test_newsletter_without_pillow(cfg, q, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "PIL", None)
    res = newsletter.build(cfg, q, TODAY, tmp_path / "n")
    assert res["charts"] is False
    assert "<img" not in (tmp_path / "n" / "newsletter.html").read_text()
    assert not (tmp_path / "n" / "chart.gif").exists()


def test_render_html_escapes():
    dg = {"date": "2026-03-15", "totals": {"submitted": 0, "replies": 0, "interviews": 0, "offers": 0, "reply_rate": 0},
          "last7": 0, "yesterday": [{"employer": "<script>", "title": "x"}], "series": [], "by_track": [],
          "needs": {"auth": [], "human": 0, "technical": 0, "needs_check": 0, "approvals_pending": 0},
          "coming_up": {"deadlines": [], "followups": []}, "flags": {"counts": {}, "warnings": []}}
    html = newsletter.render_html(dg, "", "", None)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "0 submitted applications" in html


@pytest.fixture
def built(cfg, q, tmp_path):
    out = tmp_path / "news"
    newsletter.build(cfg, q, TODAY, out)
    return out


ENV = {"SMTP_HOST": "smtp.example.com", "SMTP_USER": "alex.rivera@example.com", "SMTP_PASSWORD": "pw",
       "NEWSLETTER_TO": "alex.rivera@example.com, coach@example.org", "NEWSLETTER_FROM": "alex.rivera@example.com"}


def test_send_missing_settings_sends_nothing(built, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("SMTP must not be used")
    monkeypatch.setattr(newsletter.smtplib, "SMTP", boom)
    msg = newsletter.send(built, env={"SMTP_HOST": "smtp.example.com"})
    assert msg.startswith("Not sent: missing") and "NEWSLETTER_TO" in msg
    assert newsletter.send(built.parent / "nothing", env=ENV).startswith("Not sent")


def test_send_dry_run_writes_eml(built, monkeypatch):
    pytest.importorskip("PIL")
    monkeypatch.setattr(newsletter.smtplib, "SMTP", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    res = newsletter.send(built, env=ENV, dry_run=True)
    assert res.startswith("Dry run")
    m = email.message_from_bytes((built / "newsletter.eml").read_bytes(), policy=email.policy.default)
    assert m.get_content_type() == "multipart/alternative"
    assert m["Subject"] == "Job search · Mar 15 · 3 submitted, 1 interview"
    plain, related = m.get_payload()
    assert plain.get_content_type() == "text/plain"
    assert related.get_content_type() == "multipart/related"
    parts = related.get_payload()
    assert [p.get_content_type() for p in parts] == ["text/html", "image/gif", "image/gif"]
    assert {p["Content-ID"] for p in parts[1:]} == {"<chart>", "<chartdark>"}
    assert parts[1].get_payload(decode=True)[:6] == b"GIF89a"


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.calls = host, port, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, pw):
        self.calls.append(("login", user))

    def send_message(self, msg, from_addr=None, to_addrs=None):
        self.calls.append(("send", tuple(to_addrs)))
        self.msg = msg


def test_send_uses_starttls(built, monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(newsletter.smtplib, "SMTP", FakeSMTP)
    res = newsletter.send(built, env=ENV)
    s = FakeSMTP.instances[0]
    assert (s.host, s.port) == ("smtp.example.com", 587)
    assert s.calls[:3] == ["ehlo", "starttls", "ehlo"]
    assert ("login", "alex.rivera@example.com") in s.calls
    assert s.calls[-1] == ("send", ("alex.rivera@example.com", "coach@example.org"))
    assert res.startswith("Sent") and "2 recipient(s)" in res


def test_send_reports_smtp_failure(built, monkeypatch):
    def refuse(*a, **k):
        raise ConnectionRefusedError("refused")
    monkeypatch.setattr(newsletter.smtplib, "SMTP", refuse)
    assert newsletter.send(built, env={**ENV, "SMTP_PORT": "2525"}).startswith("Not sent: ConnectionRefusedError")


# ---------------------------------------------------------------- notify

class FakeResponse:
    def __init__(self, body=b'{"ok": true}', status=200):
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body

    def getcode(self):
        return self.status


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(req, timeout=None):
        seen.append(req)
        return FakeResponse()
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake)
    return seen


def test_telegram(calls):
    r = notify.telegram("hello", env={"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "42"})
    assert r and r == True  # noqa: E712
    req = calls[0]
    assert req.full_url == "https://api.telegram.org/bot123:abc/sendMessage"
    assert json.loads(req.data) == {"chat_id": "42", "text": "hello", "disable_web_page_preview": True}


def test_notify_noop_without_settings(calls):
    assert notify.telegram("x", env={}) == False  # noqa: E712
    assert notify.webhook("x", env={}) == False  # noqa: E712
    assert calls == []


def test_webhook_body_and_env(calls):
    assert notify.webhook("done", "https://hooks.example.com/T1")
    assert json.loads(calls[0].data) == {"text": "done", "content": "done"}
    assert notify.webhook("x", env={"JOBVEYRA_WEBHOOK": "https://hooks.example.com/T2"})
    assert calls[1].full_url == "https://hooks.example.com/T2"


def test_notify_never_raises(monkeypatch):
    def down(req, timeout=None):
        raise urllib.error.URLError("network down")
    monkeypatch.setattr(notify.urllib.request, "urlopen", down)
    r = notify.telegram("x", env={"TELEGRAM_BOT_TOKEN": "123:secret", "TELEGRAM_CHAT_ID": "1"})
    assert r == False and "network down" in r.error and "secret" not in r.error  # noqa: E712
    monkeypatch.setattr(notify.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResponse(b'{"ok": false}'))
    assert notify.telegram("x", env={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}) == False  # noqa: E712

    def http500(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "err", {}, None)
    monkeypatch.setattr(notify.urllib.request, "urlopen", http500)
    r = notify.webhook("x", "https://hooks.example.com/T3")
    assert not r and r.error == "HTTP 500"


def test_notify_summary(cfg, q):
    text = notify.summary(digest.build(cfg, q, TODAY))
    assert text.startswith("Job search · Mar 15 · 3 submitted")
    assert "Needs attention:" in text and "Sign in to workday:globex" in text


# ---------------------------------------------------------------- status

def test_status_markdown(cfg, q):
    dg = digest.build(cfg, q, TODAY)
    md = status.markdown(dg, "chart.gif", "chart-dark.gif", limit=2, more_link="docs/STATUS.md")
    assert md.startswith('<picture><source media="(prefers-color-scheme: dark)" srcset="chart-dark.gif">'
                         '<img src="chart.gif"')
    assert "**Sun Mar 15** · 3 submitted · 2 in the last 7 days · 2 replies (67%) · 1 interview · 0 offers" in md
    assert "| Data science | 2 | 2 | 78 |" in md
    needs = md.split("### Needs attention")[1].split("###")[0]
    assert needs.count("\n- ") == 3 and "[and " in needs and "more](docs/STATUS.md)" in needs
    coming = md.split("### Coming up")[1]
    assert "[and 2 more](docs/STATUS.md)" in coming
    full = status.markdown(dg, "", "")
    assert "<picture>" not in full and " more" not in full
    assert full.split("### Coming up")[1].count("\n- ") == 4      # 3 deadlines + 1 follow-up, uncapped


def test_update_block(tmp_path):
    p = tmp_path / "README.md"
    p.write_text("# Title\n\nintro\n<!-- JOBVEYRA:STATUS:START -->\nold\n<!-- JOBVEYRA:STATUS:END -->\nfooter\n")
    assert status.update_block(p, "new line 1\nnew line 2\n") is True
    assert p.read_text() == ("# Title\n\nintro\n<!-- JOBVEYRA:STATUS:START -->\nnew line 1\nnew line 2\n"
                             "<!-- JOBVEYRA:STATUS:END -->\nfooter\n")
    assert status.update_block(p, "new line 1\nnew line 2") is False          # unchanged
    q = tmp_path / "plain.md"
    q.write_text("no markers here\n")
    assert status.update_block(q, "x") is False and q.read_text() == "no markers here\n"
    assert status.update_block(tmp_path / "missing.md", "x") is False


# ---------------------------------------------------------------- calendar

def test_ics(cfg, q):
    stamp = dt.datetime(2026, 3, 15, 8, 0, tzinfo=dt.timezone.utc)
    ev = calendar.events_from_digest(digest.build(cfg, q, TODAY), interviews=[
        {"summary": "Interview: Example Labs, Data Scientist", "start": "2026-03-17T14:00:00+01:00",
         "duration_min": 45, "location": "Video call", "url": "https://example.com/call"}])
    ev.append({"kind": "deadline", "date": "2026-04-01",
               "summary": "Deadline: Globex, Data Scientist; Lisbon, " + "very long title " * 6})
    text = calendar.ics(ev, stamp=stamp)
    assert text.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:")
    assert text.endswith("END:VCALENDAR\r\n")
    assert "\n" not in text.replace("\r\n", "")
    lines = text.split("\r\n")
    assert all(len(x.encode()) <= 75 for x in lines)
    assert text.count("BEGIN:VEVENT") == len(ev) == 6
    uids = [x for x in lines if x.startswith("UID:")]
    assert len(set(uids)) == len(uids)
    assert text.count("DTSTAMP:20260315T080000Z") == len(ev)
    assert "DTSTART;VALUE=DATE:20260318\r\nDTEND;VALUE=DATE:20260319" in text
    assert "DTSTART:20260317T130000Z\r\nDTEND:20260317T134500Z" in text
    assert "CATEGORIES:Follow up" in text and "TRIGGER:-P2D" in text
    unfolded = text.replace("\r\n ", "")
    assert "SUMMARY:Deadline: Globex\\, Data Scientist\\; Lisbon\\, very long" in unfolded
    assert "DESCRIPTION:Subject: Following up" in unfolded and "\\n\\nHello" in unfolded
    again = calendar.ics(ev, stamp=stamp)
    assert again == text                                          # stable UIDs


def test_ics_requires_date():
    with pytest.raises(ValueError):
        calendar.ics([{"kind": "deadline", "summary": "x"}])
    assert "DTSTART:20260317T140000\r\n" in calendar.ics([{"kind": "interview", "start": "2026-03-17T14:00"}])
