import pytest

from app.utils.llm import _strip_fences, llm_generate_json


class FakeResponse:
    def __init__(self, content: str, status_code: int = 200):
        self._content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")

    def json(self):
        return {"message": {"content": self._content}}


def test_strip_fences_handles_json_block():
    text = "```json\n{\"foo\": \"bar\"}\n```"
    assert _strip_fences(text) == '{"foo": "bar"}'


def test_strip_fences_returns_plain_text():
    plain = '{"foo": "bar"}'
    assert _strip_fences(plain) == plain


def test_llm_generate_json_extracts_root_key(monkeypatch):
    payload = '{"ideas": [{"title": "A"}]}'

    def fake_post(url, json, timeout):
        assert url.endswith("/api/chat")
        return FakeResponse(payload)

    monkeypatch.setattr("app.utils.llm.requests.post", fake_post)
    ideas = llm_generate_json("sys", "user", "model", "http://localhost:11434", "ideas")
    assert ideas == [{"title": "A"}]


def test_llm_generate_json_accepts_list_payload(monkeypatch):
    payload = '[{"title": "A"}]'

    def fake_post(url, json, timeout):
        return FakeResponse(payload)

    monkeypatch.setattr("app.utils.llm.requests.post", fake_post)
    ideas = llm_generate_json("sys", "user", "model", "http://localhost:11434", "ideas")
    assert ideas == [{"title": "A"}]


def test_llm_generate_json_raises_for_unexpected_shape(monkeypatch):
    payload = '{"unexpected": true}'

    def fake_post(url, json, timeout):
        return FakeResponse(payload)

    monkeypatch.setattr("app.utils.llm.requests.post", fake_post)
    with pytest.raises(ValueError):
        llm_generate_json("sys", "user", "model", "http://localhost:11434", "ideas")
