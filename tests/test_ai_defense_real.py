import pytest

from petebot.ai_defense_real import AIDefenseError, describe_verdict, inspect_messages


class _FakeResponse:
    def __init__(self, json_body, status_code=200):
        self._json_body = json_body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._json_body


def test_inspect_messages_sends_expected_request(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse({"is_safe": True, "classifications": []})

    monkeypatch.setattr("petebot.ai_defense_real.requests.post", fake_post)

    result = inspect_messages("test-key", [{"role": "user", "content": "hi"}])

    assert result == {"is_safe": True, "classifications": []}
    assert captured["url"] == "https://us.api.inspect.aidefense.security.cisco.com/api/v1/inspect/chat"
    assert captured["headers"]["X-Cisco-AI-Defense-API-Key"] == "test-key"
    assert captured["json"] == {"messages": [{"role": "user", "content": "hi"}]}


def test_inspect_messages_uses_custom_base_url(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        return _FakeResponse({"is_safe": True})

    monkeypatch.setattr("petebot.ai_defense_real.requests.post", fake_post)

    inspect_messages(
        "test-key",
        [{"role": "user", "content": "hi"}],
        base_url="https://eu.api.inspect.aidefense.security.cisco.com",
    )

    assert captured["url"].startswith("https://eu.api.inspect.aidefense.security.cisco.com")


def test_inspect_messages_raises_ai_defense_error_on_http_failure(monkeypatch):
    def fake_post(url, headers, json, timeout):
        return _FakeResponse({"error": "bad key"}, status_code=401)

    monkeypatch.setattr("petebot.ai_defense_real.requests.post", fake_post)

    with pytest.raises(AIDefenseError):
        inspect_messages("bad-key", [{"role": "user", "content": "hi"}])


def test_inspect_messages_raises_ai_defense_error_on_network_failure(monkeypatch):
    import requests

    def fake_post(url, headers, json, timeout):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr("petebot.ai_defense_real.requests.post", fake_post)

    with pytest.raises(AIDefenseError):
        inspect_messages("test-key", [{"role": "user", "content": "hi"}])


def test_describe_verdict_formats_classifications_severity_and_rules():
    result = {
        "classifications": ["PRIVACY_VIOLATION"],
        "severity": "HIGH",
        "rules": [{"rule_name": "PII"}, {"rule_name": "PCI"}],
    }

    summary = describe_verdict(result)

    assert "PRIVACY_VIOLATION" in summary
    assert "HIGH" in summary
    assert "PII" in summary
    assert "PCI" in summary


def test_describe_verdict_handles_missing_fields():
    summary = describe_verdict({})
    assert "UNKNOWN" in summary
