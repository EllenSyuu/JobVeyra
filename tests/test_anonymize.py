from jobveyra.config import Candidate
from jobveyra.evaluate import anonymize

CAND = Candidate(name="Alex Rivera", email="alex.rivera@example.com", phone="+351 912 345 678",
                 links=["https://github.com/alexr-example", "https://linkedin.com/in/alex-rivera-example"])


def test_masks_everything_and_round_trips():
    text = ("Alex Rivera (alex.rivera@example.com, +351 912-345-678) applies to Globex. "
            "See github.com/alexr-example and https://www.linkedin.com/in/alex-rivera-example/. "
            "Contact the recruiter at jobs@globex.example or +44 20 7946 0958. Alex led the project; "
            "Ms. Rivera presented it.")
    masked, mapping = anonymize.mask(text, CAND)
    for secret in ("Alex", "Rivera", "alex.rivera@example.com", "912", "alexr-example", "alex-rivera-example",
                   "jobs@globex.example", "7946"):
        assert secret not in masked, secret
    assert "[NAME]" in masked and "[FIRST_NAME]" in masked and "[LAST_NAME]" in masked
    assert "[EMAIL_1]" in masked and "[EMAIL_2]" in masked
    assert "[PHONE_1]" in masked and "[PHONE_2]" in masked
    assert "[LINK_1]" in masked and "[LINK_2]" in masked
    assert mapping["[EMAIL_1]"] == "alex.rivera@example.com"
    assert mapping["[PHONE_1]"] == "+351 912 345 678"
    assert "Globex" in masked                       # employers are not personal data
    back = anonymize.unmask(masked, mapping)
    assert "alex.rivera@example.com" in back and "jobs@globex.example" in back and "Alex Rivera" in back


def test_case_and_accent_insensitive_name():
    cand = Candidate(name="Zoë Martín-López")
    masked, mapping = anonymize.mask("ZOE MARTIN-LOPEZ wrote this; zoë said hi; Martin agreed.", cand)
    assert masked.startswith("[NAME] wrote this")
    assert "[FIRST_NAME] said hi" in masked
    assert "Martin" not in masked and "zoë" not in masked.lower()
    assert mapping["[NAME]"] == "Zoë Martín-López"


def test_phone_formats_normalised():
    cand = Candidate(name="Alex Rivera", phone="(212) 555-0100")
    masked, _ = anonymize.mask("Call +1 212.555.0100 or 212 555 0100.", cand)
    assert masked == "Call [PHONE_1] or [PHONE_1]."


def test_does_not_mask_years_or_short_numbers():
    masked, mapping = anonymize.mask("From 2019-2024 I handled 1,200 tickets and 40% growth.", CAND)
    assert masked == "From 2019-2024 I handled 1,200 tickets and 40% growth."
    assert mapping == {}


def test_same_email_same_token():
    masked, mapping = anonymize.mask("a@b.example then A@B.example then c@d.example", Candidate())
    assert masked == "[EMAIL_1] then [EMAIL_1] then [EMAIL_2]"
    assert set(mapping) == {"[EMAIL_1]", "[EMAIL_2]"}


def test_empty_candidate_and_text():
    assert anonymize.mask("", CAND) == ("", {})
    assert anonymize.unmask("no tokens", {"[NAME]": "x"}) == "no tokens"
