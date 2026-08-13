import httpx
import groq
import pytest
from groq import Groq

from petebot.ai_defense_gateway import (
    AIDefenseGatewayBlocked,
    chat_completion_via_gateway,
    get_gateway_client,
)


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeClient:
    def __init__(self, result):
        self._result = result
        self.last_call = None

    def post(self, path, *, body, cast_to):
        self.last_call = {"path": path, "body": body, "cast_to": cast_to}
        if isinstance(self._result, Exception):
            raise self._result
        return _FakeResponse(self._result)


def _blocked_error(body):
    request = httpx.Request("POST", "https://gateway.example.com/tenant/connections/conn/v1/chat/completions")
    response = httpx.Response(400, request=request, json=body)
    return groq.BadRequestError("blocked", response=response, body=body)


def test_get_gateway_client_uses_given_base_url_and_api_key():
    client = get_gateway_client("test-key", "https://gateway.example.com/tenant/connections/conn/v1")

    assert isinstance(client, groq.Groq)
    assert str(client.base_url).startswith("https://gateway.example.com/tenant/connections/conn/v1")
    assert client.api_key == "test-key"


def test_chat_completion_via_gateway_posts_to_chat_completions_path():
    client = _FakeClient("hello there")
    history = [{"role": "user", "content": "안녕"}, {"role": "assistant", "content": "안녕하세요"}]

    result = chat_completion_via_gateway(client, "SYSTEM_PROMPT", history, "질문입니다")

    assert result == "hello there"
    assert client.last_call["path"] == "/chat/completions"
    sent_messages = client.last_call["body"]["messages"]
    assert sent_messages[0] == {"role": "system", "content": "SYSTEM_PROMPT"}
    assert sent_messages[1:3] == history
    assert sent_messages[3] == {"role": "user", "content": "질문입니다"}


def test_chat_completion_via_gateway_raises_with_reason_from_body():
    client = _FakeClient(_blocked_error({"action": "block", "reason": "PII detected"}))

    with pytest.raises(AIDefenseGatewayBlocked) as exc_info:
        chat_completion_via_gateway(client, "SYSTEM_PROMPT", [], "hi")

    assert "PII detected" in str(exc_info.value)
    assert "(HTTP 400)" in str(exc_info.value)


def test_chat_completion_via_gateway_falls_back_to_generic_message_on_unrecognized_body():
    client = _FakeClient(_blocked_error({}))

    with pytest.raises(AIDefenseGatewayBlocked) as exc_info:
        chat_completion_via_gateway(client, "SYSTEM_PROMPT", [], "hi")

    assert "차단" in str(exc_info.value)
    assert "(HTTP 400)" in str(exc_info.value)


def test_chat_completion_via_gateway_builds_correct_request_url_against_real_client():
    """Regression test: the groq SDK's chat.completions.create() hardcodes
    '/openai/v1/chat/completions', which double-appends onto a Gateway
    base_url that already ends in '/v1'. This drives a real Groq client
    (HTTP transport swapped for a mock) through chat_completion_via_gateway
    and asserts the actual request URL, so a regression back to
    client.chat.completions.create() would be caught here.
    """
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hi there"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = Groq(
        api_key="test-key",
        base_url="https://gateway.example.com/tenant/connections/conn/v1",
        http_client=http_client,
    )

    result = chat_completion_via_gateway(client, "SYSTEM_PROMPT", [], "hi")

    assert result == "hi there"
    assert captured["url"] == "https://gateway.example.com/tenant/connections/conn/v1/chat/completions"
