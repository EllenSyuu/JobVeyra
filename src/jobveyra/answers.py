"""Answer memory: every form question is looked up here before anyone asks the candidate.

Three sources, first match wins:

1. ``answers.yml`` in the workspace: standing answers the candidate wrote once::

       - match: 'authori[sz]ed to work|right to work'
         answer: "Yes"
         note: work authorization
       - match: 'salary|compensation'
         answer: "The midpoint of the posted range"

2. ``state/answers.csv``: what was answered before, per employer (``record``).
3. ``state/questions.csv``: questions the candidate already answered (``reply``).

A question with no answer becomes ONE open question per employer: a second unknown question for the
same employer is merged into it, and every job waiting on it is blocked as ``hold:Q<n>``. When the
candidate replies, the answer is remembered and those jobs go back to the queue.

Questions that are the candidate's alone (legal attestations, signatures, voluntary demographic
self-identification) are never answered from memory unless ``answers.yml`` has an explicit rule.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from pathlib import Path

QFIELDS = ["id", "date", "question", "company", "jobs", "status", "answer"]
AFIELDS = ["date", "company", "question", "answer"]
PERSONAL = re.compile(r"attest|certify that|i certify|signature|sign here|electronic signature|gender|ethnic|race\b|"
                      r"disabilit|veteran|indigenous|aboriginal|visible minorit|sexual orientation|pronoun", re.I)
STOP = set("the a an of to in for and or you your are is have has at this with do did does on be been we our any "
           "le la les des de du et ou vous votre est".split())


def _words(s: str) -> set[str]:
    s = (s or "").lower()
    return {x for x in re.findall(r"[a-zà-ÿ0-9]+", s) if x not in STOP and len(x) > 1} | set(re.findall(r"[一-鿿]", s))


def similarity(a: str, b: str) -> float:
    A, B = _words(a), _words(b)
    return len(A & B) / max(1, min(len(A), len(B))) if A and B else 0.0


def _co(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().split("(")[0])[:16]


def _read(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    with p.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write(p: Path, fields: list[str], rows: list[dict]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n", extrasaction="ignore", restval="")
    w.writeheader()
    w.writerows(rows)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(buf.getvalue(), encoding="utf-8")


class Memory:
    def __init__(self, workspace: Path):
        self.ws = Path(workspace)
        self.rules_path = self.ws / "answers.yml"
        self.answers_path = self.ws / "state" / "answers.csv"
        self.questions_path = self.ws / "state" / "questions.csv"

    def rules(self) -> list[dict]:
        import yaml
        if not self.rules_path.is_file():
            return []
        raw = yaml.safe_load(self.rules_path.read_text(encoding="utf-8")) or []
        if not isinstance(raw, list):
            raise ValueError("answers.yml must be a list of {match, answer, note}")
        out = []
        for i, r in enumerate(raw):
            if not isinstance(r, dict) or "match" not in r or "answer" not in r:
                raise ValueError(f"answers.yml[{i}]: needs match and answer")
            re.compile(r["match"])
            out.append({"match": str(r["match"]), "answer": str(r["answer"]), "note": str(r.get("note") or "")})
        return out

    def lookup(self, question: str, company: str = "") -> tuple[str, str] | None:
        for r in self.rules():
            if re.search(r["match"], question or "", re.I):
                return r["answer"], f"answers.yml: {r['note'] or r['match']}"
        if PERSONAL.search(question or ""):
            return None
        best = None
        for r in _read(self.answers_path):
            s = similarity(question, r["question"]) + (0.15 if company and _co(r["company"]) == _co(company) else 0)
            if s >= 0.75 and (best is None or s > best[0]):
                best = (s, r["answer"], f"answered before for {r['company']} ({r['date']})")
        for r in _read(self.questions_path):
            if r.get("status") == "answered" and similarity(question, r["question"]) >= 0.7:
                s = similarity(question, r["question"])
                if best is None or s > best[0]:
                    best = (s, r["answer"], f"your reply to {r['id']}")
        return (best[1], best[2]) if best else None

    def record(self, company: str, question: str, answer: str, today: dt.date) -> bool:
        rows = _read(self.answers_path)
        if any(_co(r["company"]) == _co(company) and similarity(r["question"], question) >= 0.9 for r in rows):
            return False
        rows.append({"date": today.isoformat(), "company": company, "question": question, "answer": answer})
        _write(self.answers_path, AFIELDS, rows)
        return True

    def ask(self, question: str, company: str, job_id: str, today: dt.date) -> tuple[str, str]:
        """("answer", text) when memory has it, else ("hold", "Q<n>") after filing or merging a question."""
        hit = self.lookup(question, company)
        if hit:
            self.record(company, question, hit[0], today)
            return "answer", f"{hit[0]}   [{hit[1]}]"
        qs = _read(self.questions_path)
        for q in qs:
            if q.get("status", "open") == "open" and company and _co(q.get("company", "")) == _co(company):
                if similarity(question, q["question"]) < 0.75 and question not in q["question"]:
                    q["question"] = q["question"].rstrip("; ") + "; also: " + question
                q["jobs"] = ",".join(sorted(set(filter(None, q.get("jobs", "").split(",") + [job_id]))))
                _write(self.questions_path, QFIELDS, qs)
                return "hold", q["id"]
        n = 1 + max([int(re.sub(r"\D", "", q["id"]) or 0) for q in qs] or [0])
        qs.append({"id": f"Q{n}", "date": today.isoformat(), "question": question, "company": company,
                   "jobs": job_id, "status": "open", "answer": ""})
        _write(self.questions_path, QFIELDS, qs)
        return "hold", f"Q{n}"

    def open_questions(self) -> list[dict]:
        return [q for q in _read(self.questions_path) if q.get("status", "open") == "open"]

    def reply(self, qid: str, answer: str, today: dt.date) -> dict:
        qs = _read(self.questions_path)
        for q in qs:
            if q["id"].lower() == qid.lower():
                q["status"], q["answer"] = "answered", answer
                _write(self.questions_path, QFIELDS, qs)
                for part in re.split(r";\s*also:\s*", q["question"]):
                    self.record(q.get("company", ""), part, answer, today)
                return q
        raise KeyError(f"no question {qid}")
