"""Source adapters and the Http layer, offline against tests/fixtures/sources."""
from __future__ import annotations

import email.message
import shutil
import urllib.error
from pathlib import Path

import pytest

from jobveyra import sources
from jobveyra.sources import base
from jobveyra.sources.http import Http, HttpError, RobotsDisallowed, fixture_name

FIX = Path(__file__).parent / "fixtures" / "sources"


@pytest.fixture
def http():
    return Http(fixtures=FIX)


def fetch(type_name, http, **spec):
    return sources.get(type_name).fetch({"type": type_name, **spec}, http)


def by_title(postings):
    return {p.title: p for p in postings}


# ---------------------------------------------------------------- registry

def test_registry_has_every_adapter():
    assert set(base.ADAPTERS) <= set(sources.REGISTRY)
    for name in base.ADAPTERS:
        assert sources.get(name).name == name


def test_unknown_type_raises_keyerror():
    with pytest.raises(KeyError, match="unknown source type"):
        sources.get("monster")


# ---------------------------------------------------------------- adapters

def test_greenhouse(http):
    ps = by_title(fetch("greenhouse", http, board="examplelabs"))
    assert set(ps) == {"Data Scientist", "Senior Machine Learning Engineer", "Director of Analytics"}
    ds = ps["Data Scientist"]
    assert ds.source == "greenhouse" and ds.employer == "Example Labs"
    assert ds.url == "https://boards.greenhouse.io/examplelabs/jobs/4012345" and ds.req_id == "4012345"
    assert ds.location == "Lisbon, Portugal" and ds.remote is None
    assert ds.posted == "2026-10-20" and ds.employment == "full_time" and ds.lang == "en"
    assert (ds.salary_min, ds.salary_max, ds.salary_currency) == (55000, 70000, "EUR")
    assert "<" not in ds.text and "&lt;" not in ds.text
    assert "energy grids." in ds.text and "- Build demand forecasting models in Python" in ds.text
    assert "€55,000 – €70,000" in ds.text
    assert ds.extra["requisition_id"] == "DS-2026-014"
    assert ps["Senior Machine Learning Engineer"].remote is True


def test_greenhouse_employer_override(http):
    ps = fetch("greenhouse", http, board="examplelabs", employer="Example Labs Europe")
    assert {p.employer for p in ps} == {"Example Labs Europe"}


def test_greenhouse_needs_board(http):
    with pytest.raises(base.SourceError, match="board"):
        fetch("greenhouse", http)


def test_lever(http):
    ps = by_title(fetch("lever", http, board="globex", employer="Globex"))
    da = ps["Data Analyst"]
    assert da.employer == "Globex" and da.req_id == "a1b2c3d4-0000-4000-8000-000000000001"
    assert da.apply_url.endswith("/apply") and da.location == "Madrid, Spain"
    assert da.remote is False and da.employment == "full_time" and da.posted == "2026-10-28"
    assert (da.salary_min, da.salary_max, da.salary_currency) == (42000, 52000, "EUR")
    assert "Requirements" in da.text and "- SQL and Python" in da.text and "Madrid office" in da.text
    assert ps["Analytics Intern"].employment == "internship"


class _Pages:
    """A fake Http that serves Lever-style pages and records the URLs asked for."""

    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get_json(self, url, headers=None):
        self.urls.append(url)
        return self.pages[len(self.urls) - 1]


def test_lever_paginates_until_a_short_page():
    def job(i):
        return {"id": f"id-{i}", "text": f"Role {i}", "hostedUrl": f"https://jobs.lever.co/x/id-{i}", "categories": {}}
    fake = _Pages([[job(i) for i in range(100)], [job(i) for i in range(100, 105)]])
    ps = sources.get("lever").fetch({"board": "x"}, fake)
    assert len(ps) == 105
    assert "skip=0&limit=100" in fake.urls[0] and "skip=100&limit=100" in fake.urls[1]


def test_lever_eu_region_host():
    fake = _Pages([[]])
    sources.get("lever").fetch({"board": "x", "region": "eu"}, fake)
    assert fake.urls[0].startswith("https://api.eu.lever.co/v0/postings/x?")


def test_ashby(http):
    ps = by_title(fetch("ashby", http, board="initech", employer="Initech"))
    assert "Hidden Role" not in ps                       # isListed: false is skipped
    a = ps["Applied Scientist"]
    assert a.location == "Lisbon; Porto" and a.remote is False and a.employment == "full_time"
    assert (a.salary_min, a.salary_max, a.salary_currency) == (60000, 80000, "EUR")
    assert a.extra["salary_interval"] == "1 YEAR" and a.posted == "2026-10-22"
    assert a.apply_url.endswith("/application") and a.req_id == "5f0c1e2d-1111-4222-8333-444455556666"
    assert ps["Data Engineer"].employment == "contract"


def test_workable(http):
    ps = by_title(fetch("workable", http, board="umbrella-analytics"))
    bi = ps["Business Intelligence Analyst"]
    assert bi.employer == "Umbrella Analytics" and bi.req_id == "AB12CD34EF"
    assert bi.location == "Porto, Portugal" and bi.remote is False and bi.employment == "full_time"
    assert bi.posted == "2026-10-27" and "- Power BI" in bi.text
    assert bi.apply_url.endswith("/apply/")
    remote = ps["Remote Data Analyst"]
    assert remote.remote is True and remote.employment == "part_time" and remote.location == "Portugal"


def test_smartrecruiters_with_details(http):
    ps = by_title(fetch("smartrecruiters", http, board="Hooli"))
    q = ps["Quantitative Analyst"]
    assert q.employer == "Hooli" and q.req_id == "744000012345678"
    assert q.url.endswith("744000012345678-quantitative-analyst") and q.apply_url.endswith("oga=true")
    assert q.location == "Lisbon, pt"
    assert q.remote is False and q.employment == "full_time" and q.posted == "2026-10-29"
    assert "PD/LGD" in q.text and "- Statistics degree" in q.text and "Additional Information" not in q.text
    assert q.extra["ref_number"] == "REF1234X"
    ds = ps["Data Scientist"]                            # its detail fixture is missing: no text, no failure
    assert ds.text == "" and ds.remote is True and ds.url == "https://jobs.smartrecruiters.com/Hooli/744000012345679"


def test_smartrecruiters_without_details(http):
    ps = fetch("smartrecruiters", http, board="Hooli", details=False)
    assert all(p.text == "" for p in ps)
    assert not any("/postings/7440" in u for _, u in http.requests)


def test_recruitee(http):
    ps = fetch("recruitee", http, board="vandelay")
    assert [p.title for p in ps] == ["Data Scientist"]          # the draft offer is skipped
    p = ps[0]
    assert p.employer == "Vandelay Industries" and p.req_id == "1550001"
    assert p.remote is False and p.employment == "full_time"
    assert (p.posted, p.deadline) == ("2026-10-25", "2026-12-15")
    assert (p.salary_min, p.salary_max, p.salary_currency) == (50000, 65000, "EUR")
    assert "- Time series" in p.text and p.apply_url.endswith("/c/new")


def test_recruitee_rejects_bad_board(http):
    with pytest.raises(base.SourceError):
        fetch("recruitee", http, board="evil.example/x")


def test_un_careers_posts_each_keyword_and_dedupes(http):
    ps = by_title(fetch("un_careers", http, keywords=["statistics", "data"]))
    assert set(ps) == {"Statistician", "Associate Statistician", "Intern - Data Science"}
    st = ps["Statistician"]
    assert st.employer == "United Nations" and st.req_id == "245001"
    assert st.url == "https://careers.un.org/jobSearchDescription/245001?language=en"
    assert (st.location, st.posted, st.deadline) == ("NEW YORK", "2026-10-15", "2026-12-01")
    assert st.extra["level"] == "P-3" and st.extra["department"] == "Example Statistics Division"
    assert ps["Intern - Data Science"].employment == "internship"
    posts = [u for m, u in http.requests if m == "POST"]
    assert len(posts) == 2


def test_usajobs_requires_credentials(http, monkeypatch):
    monkeypatch.delenv("USAJOBS_API_KEY", raising=False)
    monkeypatch.delenv("USAJOBS_EMAIL", raising=False)
    with pytest.raises(base.SourceError, match="USAJOBS_API_KEY"):
        fetch("usajobs", http, keyword="statistician")


def test_usajobs(http, monkeypatch):
    monkeypatch.setenv("USAJOBS_API_KEY", "test-key")
    monkeypatch.setenv("USAJOBS_EMAIL", "someone@example.com")
    ps = fetch("usajobs", http, keyword="statistician")
    assert len(ps) == 1
    p = ps[0]
    assert p.employer == "Federal Example Agency" and p.title == "Mathematical Statistician"
    assert p.req_id == "FEA-26-0101" and p.url == "https://www.usajobs.gov/job/800100"
    assert p.apply_url.endswith("/apply") and p.remote is False and p.employment == "full_time"
    assert (p.salary_min, p.salary_max, p.salary_currency) == (86962, 113047, "USD")
    assert (p.posted, p.deadline) == ("2026-10-30", "2026-11-20")
    assert "- Design survey samples" in p.text and "24 semester hours" in p.text


def test_remotive(http):
    ps = by_title(fetch("remotive", http, category="data", currency="USD"))
    sde = ps["Senior Data Engineer"]
    assert sde.employer == "Globex" and sde.remote is True and sde.location == "Europe"
    assert (sde.salary_min, sde.salary_max, sde.salary_currency) == (90000, 120000, "USD")
    assert sde.employment == "full_time" and sde.posted == "2026-10-28" and sde.text == "Own our lakehouse pipelines."
    assert ps["Data Analyst"].salary_min is None and ps["Data Analyst"].employment == "contract"
    assert ps["Machine Learning Consultant"].employment == "contract"          # freelance


def test_jsonld_graph_list_and_itemlist(http):
    ps = by_title(fetch("jsonld", http, urls=["https://careers.example.org/jobs", "https://careers.globex.example/jobs"]))
    assert set(ps) == {"Survey Statistician", "Remote Data Engineer", "Analytics Engineer"}
    s = ps["Survey Statistician"]
    assert s.source == "jsonld" and s.employer == "Example Org" and s.req_id == "EO-311"
    assert s.url == "https://careers.example.org/jobs/eo-311"                  # relative url resolved
    assert (s.location, s.posted, s.deadline, s.employment) == ("Lisbon, Portugal", "2026-10-18", "2026-12-01", "full_time")
    assert (s.salary_min, s.salary_max, s.salary_currency) == (48000, 58000, "EUR")
    assert s.text == "Design household surveys." and s.lang == "en"
    r = ps["Remote Data Engineer"]
    assert r.remote is True and r.employment == "contract" and r.location == "Portugal" and r.employer == "Example Org"
    a = ps["Analytics Engineer"]
    assert a.employer == "Globex" and a.location == "Madrid, Spain" and a.salary_min == a.salary_max == 52000


def test_jsonld_all_pages_failing_raises(http):
    with pytest.raises(base.SourceError):
        fetch("jsonld", http, urls=["https://careers.example.org/missing"])


def test_jsonld_one_page_failing_is_skipped(http):
    ps = fetch("jsonld", http, urls=["https://careers.example.org/missing", "https://careers.globex.example/jobs"])
    assert [p.title for p in ps] == ["Analytics Engineer"]


@pytest.mark.parametrize("name", ["alert.html", "alert.txt", "alert.eml"])
def test_linkedin_alert_formats(name):
    ps = sources.get("linkedin_alert").fetch({"path": str(FIX / "linkedin" / name)}, None)
    got = {(p.title, p.employer, p.location, p.remote) for p in ps}
    assert got == {("Data Scientist", "Example Labs", "Lisbon, Portugal", False),
                   ("Senior Data Analyst", "Globex", "Portugal", True),
                   ("Machine Learning Engineer", "Initech", "Madrid, Spain", None)}
    urls = sorted(p.url for p in ps)
    assert urls[0] == "https://www.linkedin.com/jobs/view/3900000001/"
    assert all(p.source == "linkedin_alert" and p.text == "" for p in ps)


def test_linkedin_alert_never_uses_http():
    class NoNetwork:
        def __getattr__(self, name):
            raise AssertionError("linkedin_alert must not make requests")
    ps = sources.get("linkedin_alert").fetch({"path": str(FIX / "linkedin" / "alert.html")}, NoNetwork())
    assert len(ps) == 3


def test_linkedin_alert_folder_relative_to_workspace(tmp_path):
    d = tmp_path / "alerts"
    d.mkdir()
    shutil.copy(FIX / "linkedin" / "alert.html", d / "a.html")
    shutil.copy(FIX / "linkedin" / "alert.txt", d / "b.txt")
    ps = sources.get("linkedin_alert").fetch({"path": "alerts", "_workspace": str(tmp_path)}, None)
    assert len(ps) == 3                                   # same jobs in both files, deduplicated


def test_linkedin_alert_missing_path(tmp_path):
    with pytest.raises(base.SourceError):
        sources.get("linkedin_alert").fetch({"path": str(tmp_path / "nope.eml")}, None)


# ---------------------------------------------------------------- helpers

def test_html_to_text():
    assert base.html_to_text("<p>One</p><p>Two &amp; <b>three</b></p><ul><li>a</li><li>b</li></ul>") == \
        "One\n\nTwo & three\n\n- a\n- b"
    assert base.html_to_text("&lt;p&gt;Escaped&lt;/p&gt;") == "Escaped"
    assert base.html_to_text("<script>var x=1</script><style>p{}</style>Body") == "Body"
    assert base.html_to_text(None) == ""


@pytest.mark.parametrize("label,want", [
    ("Full-time", "full_time"), ("FullTime", "full_time"), ("permanent", "full_time"), ("Temps plein", "full_time"),
    ("Part-time", "part_time"), ("Contract", "contract"), ("CONTRACTOR", "contract"), ("freelance", "contract"),
    ("Temporary", "temporary"), ("Fixed term", "temporary"), ("CDD", "temporary"), ("Internship", "internship"),
    ("INTERN", "internship"), ("Stage", "internship"), ("", ""), ("Other", ""), (["FULL_TIME", "PART_TIME"], "part_time"),
])
def test_employment_of(label, want):
    assert base.employment_of(label) == want


@pytest.mark.parametrize("text,want", [
    ("$80k - $100k", (80000, 100000, "")),
    ("USD 90,000 to 120,000 per year", (90000, 120000, "USD")),
    ("€50.000–€60.000", (50000, 60000, "EUR")),
    ("CA$85,000 - CA$95,000", (85000, 95000, "CAD")),
    ("65 000 $ - 75 000 $", (65000, 75000, "")),
    ("£45,000", (45000, 45000, "GBP")),
    ("no pay info", None),
])
def test_money_range(text, want):
    assert base.money_range(text) == want


def test_iso_date():
    assert base.iso_date("2026-10-20T09:15:00-04:00") == "2026-10-20"
    assert base.iso_date(1793145600000) == "2026-10-28"
    assert base.iso_date(1793145600) == "2026-10-28"
    assert base.iso_date("10/28/2026") == "2026-10-28"
    assert base.iso_date("") == "" and base.iso_date("soon") == ""


def test_remote_hint():
    assert base.remote_hint("Remote - Europe") is True
    assert base.remote_hint("Lisbon (Hybrid)") is False
    assert base.remote_hint("Télétravail") is True
    assert base.remote_hint("Lisbon") is None


# ---------------------------------------------------------------- Http: fixtures

def test_fixture_name_scheme():
    assert fixture_name("https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true") == \
        "boards-api.greenhouse.io_v1_boards_acme_jobs_content_true"
    assert fixture_name("https://acme.recruitee.com/api/offers/") == "acme.recruitee.com_api_offers"
    assert fixture_name("https://x.example/api", "POST") == "post__x.example_api"
    long = fixture_name("https://x.example/" + "a" * 300)
    assert len(long) == 111 and long == fixture_name("https://x.example/" + "a" * 300)


def test_fixture_mode_missing_status_and_head(http):
    with pytest.raises(HttpError) as e:
        http.get_text("https://jobs.example.com/not-there")
    assert e.value.status == 404
    with pytest.raises(HttpError) as e:
        http.get_text("https://jobs.example.com/gone")
    assert e.value.status == 410
    assert http.head("https://jobs.example.com/gone") == 410
    assert http.head("https://jobs.example.com/filled") == 200
    assert http.head("https://jobs.example.com/not-there") == 404


def test_rejects_non_http_urls(http):
    with pytest.raises(HttpError):
        http.get_text("file:///etc/passwd")


# ---------------------------------------------------------------- Http: network logic (stubbed)

class StubHttp(Http):
    """Http whose single network call is replaced by a scripted list of responses."""

    def __init__(self, script, **kw):
        self.slept: list[float] = []
        kw.setdefault("sleep", self.slept.append)
        kw.setdefault("clock", lambda: 1000.0)
        kw.setdefault("min_interval", 0.0)
        super().__init__(**kw)
        self.script, self.sent = script, []

    def _open(self, req):
        self.sent.append((req.get_method(), req.full_url, dict(req.header_items())))
        step = self.script(req.full_url, len(self.sent)) if callable(self.script) else self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def _http_error(url, code, retry_after=None):
    hdrs = email.message.Message()
    if retry_after is not None:
        hdrs["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError(url, code, "err", hdrs, None)


def test_retries_with_exponential_backoff():
    u = "https://api.example.com/x"
    h = StubHttp([_http_error(u, 503), _http_error(u, 429), (200, b'{"ok": 1}', "application/json")],
                 respect_robots=False, backoff=1.0)
    assert h.get_json(u) == {"ok": 1}
    assert h.slept == [1.0, 2.0]
    assert h.sent[0][2]["User-agent"] == "jobveyra/0.1 (+https://github.com/jobveyra)"


def test_retry_after_is_honoured():
    u = "https://api.example.com/x"
    h = StubHttp([_http_error(u, 429, retry_after=7), (200, b"[]", "")], respect_robots=False)
    assert h.get_json(u) == [] and h.slept == [7.0]


def test_client_errors_are_not_retried():
    u = "https://api.example.com/x"
    h = StubHttp([_http_error(u, 404)], respect_robots=False)
    with pytest.raises(HttpError) as e:
        h.get_json(u)
    assert e.value.status == 404 and len(h.sent) == 1 and h.slept == []


def test_network_errors_exhaust_retries():
    u = "https://api.example.com/x"
    h = StubHttp(lambda url, n: urllib.error.URLError("down"), respect_robots=False, retries=3)
    with pytest.raises(HttpError) as e:
        h.get_text(u)
    assert e.value.status == 0 and len(h.sent) == 4 and h.slept == [1.0, 2.0, 4.0]


def test_post_json_sends_body_and_headers():
    h = StubHttp([(200, b'{"data": {}}', "application/json")], respect_robots=False)
    assert h.post_json("https://api.example.com/q", {"a": 1}, headers={"X-Key": "k"}) == {"data": {}}
    method, _, headers = h.sent[0]
    assert method == "POST" and headers["Content-type"] == "application/json" and headers["X-key"] == "k"


def test_header_override_user_agent():
    h = StubHttp([(200, b"{}", "")], respect_robots=False)
    h.get_json("https://api.example.com/q", headers={"User-Agent": "someone@example.com"})
    assert h.sent[0][2]["User-agent"] == "someone@example.com"


def test_per_host_min_interval():
    clock = {"t": 100.0}
    slept: list[float] = []
    h = StubHttp(lambda url, n: (200, b"{}", ""), respect_robots=False, min_interval=2.0,
                 clock=lambda: clock["t"], sleep=slept.append)
    h.get_json("https://a.example.com/1")
    h.get_json("https://a.example.com/2")
    h.get_json("https://b.example.com/1")
    assert slept == [2.0]


def _robots_site(robots):
    def script(url, n):
        if url.endswith("/robots.txt"):
            if isinstance(robots, int):
                raise _http_error(url, robots)
            return 200, robots.encode(), "text/plain"
        return 200, b"<html>ok</html>", "text/html"
    return script


def test_robots_disallow_blocks_request():
    h = StubHttp(_robots_site("User-agent: *\nDisallow: /private\n"))
    assert h.get_text("https://site.example/jobs") == "<html>ok</html>"
    with pytest.raises(RobotsDisallowed):
        h.get_text("https://site.example/private/1")
    assert sum(1 for _, u, _ in h.sent if u.endswith("/robots.txt")) == 1      # cached per host


def test_robots_agent_specific_group():
    h = StubHttp(_robots_site("User-agent: jobveyra\nDisallow: /\n\nUser-agent: *\nAllow: /\n"))
    with pytest.raises(RobotsDisallowed):
        h.get_text("https://site.example/jobs")


def test_robots_missing_means_allowed():
    h = StubHttp(_robots_site(404))
    assert h.get_text("https://site.example/jobs") == "<html>ok</html>"


def test_robots_unreachable_means_refused():
    h = StubHttp(_robots_site(503))
    with pytest.raises(RobotsDisallowed):
        h.get_text("https://site.example/jobs")


def test_head_falls_back_to_get_when_head_refused():
    def script(url, n):
        return _http_error(url, 405) if n == 1 else (200, b"", "")
    h = StubHttp(script, respect_robots=False)
    assert h.head("https://site.example/job") == 200
    assert [m for m, _, _ in h.sent] == ["HEAD", "GET"]
