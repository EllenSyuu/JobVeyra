import pytest

from jobveyra.evaluate import comp


@pytest.mark.parametrize("text,expected", [
    ("Salary: $90k-$120k", (90000, 120000, "USD", "year")),
    ("$90-120k base", (90000, 120000, "USD", "year")),
    ("CA$85,000 – 95,000 per year", (85000, 95000, "CAD", "year")),
    ("€45.000 - €55.000 brut annuel", (45000, 55000, "EUR", "year")),
    ("45 000 € brut par an", (45000, 45000, "EUR", "year")),
    ("£400/day outside IR35", (104000, 104000, "GBP", "day")),
    ("USD 40-55 per hour", (83200, 114400, "USD", "hour")),
    ("CHF 120 000 annually", (120000, 120000, "CHF", "year")),
    ("¥6,000,000 per year", (6000000, 6000000, "JPY", "year")),
    ("EUR 3,500 per month", (42000, 42000, "EUR", "month")),
    ("Pay range: 70,000 to 80,000 GBP", (70000, 80000, "GBP", "year")),
    ("between $50k and $70k", (50000, 70000, "USD", "year")),
    ("€1.2M budget", (1200000, 1200000, "EUR", "year")),
])
def test_parse_salary(text, expected):
    assert comp.parse_salary(text) == expected


def test_no_salary():
    assert comp.parse_salary("3+ years of experience, 2 days remote, 401k match") == (None, None, "", "")
    assert comp.parse_salary("") == (None, None, "", "")


def test_default_dollar_and_unstated_period():
    assert comp.parse_salary("$60-70/hr", default_dollar="CAD")[2:] == ("CAD", "hour")
    lo, hi, cur, period = comp.parse_salary("Compensation: $45")
    assert period == "hour" and lo == 45 * 2080


def test_year_next_to_currency_code_is_skipped():
    assert comp.parse_salary("EUR 2026 budget; salary EUR 50,000")[:3] == (50000, 50000, "EUR")


def test_annualise_and_convert():
    assert comp.annualise(10, "hour") == 20800
    assert comp.annualise(100, "week") == 5200
    assert comp.annualise(None, "year") is None
    assert comp.convert(100, "EUR", "EUR") == 100
    assert 100 < comp.convert(100, "GBP", "EUR") < 130
    assert comp.convert(100, "EUR", "XXX") is None
