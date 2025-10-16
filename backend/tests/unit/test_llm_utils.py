from app.utils.llm import _strip_fences


def test_strip_fences_handles_json_block():
    text = "```json\n{\"foo\": \"bar\"}\n```"
    assert _strip_fences(text) == '{"foo": "bar"}'


def test_strip_fences_returns_plain_text():
    plain = '{"foo": "bar"}'
    assert _strip_fences(plain) == plain
