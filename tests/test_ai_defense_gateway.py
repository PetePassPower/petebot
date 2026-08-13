import httpx
import groq
import pytest

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


class _FakeCompletions:
    def __init__(self, result):
        self._result = result
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if isinstance(self._result, Exception):
            raise self._result
        return _FakeResponse(self._result)


class _FakeChat:
    def __init__(self, result):
        self.completions = _FakeCompletions(result)


class _FakeClient:
    def __init__(self, result):
        self.chat = _FakeChat(result)


def _blocked_error(body):
    request = httpx.Request("POST", "https://gateway.example.com/tenant/connections/conn/v1/chat/completions")
    response = httpx.Response(400, request=request, json=body)
    return groq.BadRequestError("blocked", response=response, body=body)


def test_get_gateway_client_uses_given_base_url_and_api_key():
    client = get_gateway_client("test-key", "https://gateway.example.com/tenant/connections/conn/v1")

    assert isinstance(client, groq.Groq)
    assert str(client.base_url).startswith("https://gateway.example.com/tenant/connections/conn/v1")
    assert client.api_key == "test-key"


def test_chat_completion_via_gateway_returns_reply_on_success():
    client = _FakeClient("hello there")
    history = [{"role": "user", "content": "안녕"}, {"role": "assistant", "content": "안녕하세요"}]

    result = chat_completion_via_gateway(client, "SYSTEM_PROMPT", history, "질문입니다")

    assert result == "hello there"
    sent = client.chat.completions.last_kwargs
    assert sent["messages"][0] == {"role": "system", "content": "SYSTEM_PROMPT"}
    assert sent["messages"][1:3] == history
    assert sent["messages"][3] == {"role": "user", "content": "질문입니다"}


def test_chat_completion_via_gateway_raises_with_reason_from_body():
    client = _FakeClient(_blocked_error({"action": "block", "reason": "PII detected"}))

    with pytest.raises(AIDefenseGatewayBlocked) as exc_info:
        chat_completion_via_gateway(client, "SYSTEM_PROMPT", [], "hi")

    assert "PII detected" in str(exc_info.value)


def test_chat_completion_via_gateway_falls_back_to_generic_message_on_unrecognized_body():
    client = _FakeClient(_blocked_error({}))

    with pytest.raises(AIDefenseGatewayBlocked) as exc_info:
        chat_completion_via_gateway(client, "SYSTEM_PROMPT", [], "hi")

    assert "차단" in str(exc_info.value)
