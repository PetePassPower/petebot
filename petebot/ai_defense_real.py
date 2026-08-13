"""Client for the real Cisco AI Defense Chat Inspection API.

Docs: https://developer.cisco.com/docs/ai-defense-inspection/
"""
from typing import Dict, List

import requests

DEFAULT_BASE_URL = "https://us.api.inspect.aidefense.security.cisco.com"
INSPECT_CHAT_PATH = "/api/v1/inspect/chat"
REQUEST_TIMEOUT_SECONDS = 10


class AIDefenseError(Exception):
    """Raised when the AI Defense inspection request fails."""


def inspect_messages(
    api_key: str,
    messages: List[Dict[str, str]],
    base_url: str = DEFAULT_BASE_URL,
) -> Dict:
    """Send messages to the Cisco AI Defense Chat Inspection API.

    Returns the parsed JSON verdict (classifications, is_safe, severity, rules, ...).
    Raises AIDefenseError on network/HTTP failure.
    """
    try:
        response = requests.post(
            f"{base_url}{INSPECT_CHAT_PATH}",
            headers={
                "Content-Type": "application/json",
                "X-Cisco-AI-Defense-API-Key": api_key,
            },
            json={"messages": messages},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise AIDefenseError(str(exc)) from exc


def describe_verdict(result: Dict) -> str:
    """Build a short human-readable summary of an inspection verdict."""
    classifications = result.get("classifications") or []
    severity = result.get("severity", "UNKNOWN")
    rule_names = [rule.get("rule_name", "?") for rule in result.get("rules") or []]

    parts = [", ".join(classifications) or "VIOLATION", f"심각도: {severity}"]
    if rule_names:
        parts.append(f"규칙: {', '.join(rule_names)}")
    return " / ".join(parts)
