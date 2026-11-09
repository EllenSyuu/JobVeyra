import io
import json
from urllib import error

import pytest

from jobveyra import config
from jobveyra.evaluate import llm


def cfg_with(tmp_path, **llm_cfg):
    raw = {"candidate": {"name": "Alex Rivera", "email": "alex.rivera@example.com"}, "llm": llm_cfg}
    return config.from_dict(raw, tmp_path)


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def capture(monkeypatch):
    calls = []
    replies = []

    def fake_urlopen(req, timeout=None):
        calls.append({"url": req.full_url, "headers": {k.lower(): v for k, v in req.header_items()},
                      "body": json.loads(req.data.decode())})
        return FakeResp(json.dumps(replies.pop(0)).encode())

    monkeypatch.setattr(llm.request, "urlopen", fake_urlopen)
    return calls, replies


def test_get_none(tmp_path):
    assert llm.get(cfg_with(tmp_path)) is None
    assert llm.get(cfg_with(tmp_path, provider="none")) is None


def test_anthropic_request_shape(tmp_path, monkeypatch, capture):
    calls, replies = capture
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    replies.append({"content": [{"type": "text", "text": "hello"}]})
    p = llm.get(cfg_with(tmp_path, provider="anthropic", model="test-model", anonymize=False))
    assert isinstance(p, llm.AnthropicProvider) and isinstance(p, llm.Provider)
    assert p.complete("sys", "usr", max_tokens=50) == "hello"
    c = calls[0]
    assert c["url"] == "https://api.anthropic.com/v1/messages"
    assert c["headers"]["x-api-key"] == "test-key" and c["headers"]["anthropic-version"] == "2023-06-01"
    assert c["body"] == {"model": "test-model", "max_tokens": 50, "system": "sys",
                         "messages": [{"role": "user", "content": "usr"}]}


def test_openai_and_compatible(tmp_path, monkeypatch, capture):
    calls, replies = capture
    monkeypatch.setenv("MY_KEY", "k2")
    replies += [{"choices": [{"message": {"content": "a"}}]}, {"choices": [{"message": {"content": "b"}}]}]
    p = llm.get(cfg_with(tmp_path, provider="openai", api_key_env="MY_KEY", anonymize=False))
    assert p.complete("s", "u") == "a"
    assert calls[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert calls[0]["headers"]["authorization"] == "Bearer k2"
    assert calls[0]["body"]["messages"][0] == {"role": "system", "content": "s"}
    q = llm.get(cfg_with(tmp_path, provider="openai_compatible", base_url="http://models.example/v1",
                         model="m", anonymize=False))
    assert q.complete("s", "u") == "b"
    assert calls[1]["url"] == "http://models.example/v1/chat/completions"
    assert "authorization" not in calls[1]["headers"]


def test_ollama(tmp_path, capture):
    calls, replies = capture
    replies.append({"message": {"role": "assistant", "content": "ok"}})
    p = llm.get(cfg_with(tmp_path, provider="ollama", model="llama3.1", anonymize=False))
    assert p.complete("s", "u") == "ok"
    assert calls[0]["url"] == "http://localhost:11434/api/chat"
    assert calls[0]["body"]["stream"] is False


def test_missing_key_and_base_url(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(llm.LLMError, match="ANTHROPIC_API_KEY"):
        llm.get(cfg_with(tmp_path, provider="anthropic"))
    with pytest.raises(llm.LLMError, match="base_url"):
        llm.get(cfg_with(tmp_path, provider="openai_compatible", model="m"))


def test_http_error_becomes_llm_error(tmp_path, monkeypatch):
    def boom(req, timeout=None):
        raise error.HTTPError(req.full_url, 429, "busy", {}, io.BytesIO(b"rate limited"))
    monkeypatch.setattr(llm.request, "urlopen", boom)
    p = llm.OllamaProvider("m")
    with pytest.raises(llm.LLMError, match="429"):
        p.complete("s", "u")


def test_masking_wrapper(tmp_path, monkeypatch, capture):
    calls, replies = capture
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    replies.append({"choices": [{"message": {"content": "Dear team, [NAME] can be reached at [EMAIL_1]."}}]})
    p = llm.get(cfg_with(tmp_path, provider="openai"))
    assert isinstance(p, llm.MaskedProvider)
    out = p.complete("You help Alex Rivera.", "Write to alex.rivera@example.com for Alex.")
    sent = json.dumps(calls[0]["body"])
    assert "Alex" not in sent and "alex.rivera@example.com" not in sent and "[NAME]" in sent
    assert out == "Dear team, Alex Rivera can be reached at alex.rivera@example.com."


class FakeProvider:
    name = "fake"

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def complete(self, system, user, max_tokens=800):
        self.prompts.append((system, user))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_semantic_skill_match_validates_reply():
    reply = json.dumps([
        {"requirement": "Experience with gradient boosting", "skill": "xgboost", "confidence": 0.9},
        {"requirement": "Cloud data warehouses", "skill": "snowflake", "confidence": 0.95},   # not a candidate skill
        {"requirement": "Invented requirement", "skill": "python", "confidence": 0.99},       # not asked
        {"requirement": "Dashboards for executives", "skill": "Tableau", "confidence": 0.5},  # too unsure
    ])
    fp = FakeProvider("Sure! ```json\n" + reply + "\n```")
    reqs = ["Experience with gradient boosting", "Cloud data warehouses", "Dashboards for executives"]
    res = llm.semantic_skill_match(fp, reqs, ["XGBoost", "Tableau", "Python"])
    assert [(r, s) for r, s, _ in res["matches"]] == [("Experience with gradient boosting", "XGBoost")]
    assert res["boost"] == pytest.approx(llm.MAX_BOOST / 3)
    assert res["boost"] <= llm.MAX_BOOST
    assert all(e.basis == "estimate" for e in res["evidence"])


def test_semantic_skill_match_boost_is_bounded_and_safe():
    reply = json.dumps({"matches": [{"requirement": "A", "skill": "x", "confidence": 1}]})
    assert llm.semantic_skill_match(FakeProvider(reply), ["A"], ["x"])["boost"] == llm.MAX_BOOST
    res = llm.semantic_skill_match(FakeProvider(llm.LLMError("down")), ["A"], ["x"])
    assert res["boost"] == 0 and "down" in res["error"]
    assert llm.semantic_skill_match(FakeProvider("not json"), ["A"], ["x"])["boost"] == 0
    assert llm.semantic_skill_match(None, ["A"], ["x"])["boost"] == 0
