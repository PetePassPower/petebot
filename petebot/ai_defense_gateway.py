"""Client for Cisco AI Defense Gateway (inline proxy) mode.

The Gateway exposes an OpenAI-compatible endpoint per "connection". Pointing
an OpenAI-compatible client's base_url at it routes calls through Cisco's
inline inspection before they reach the real LLM provider. Auth is
pass-through: the caller sends the underlying provider's own API key, there
is no separate Gateway API key.
"""
from typing import Dict, List, Optional

import groq
from groq import Groq

from petebot.llm import DEFAULT_MODEL


class AIDefenseGatewayBlocked(Exception):
    """Raised when the AI Defense Gateway blocks a request or response."""


def get_gateway_client(api_key: str, gateway_url: str) -> Groq:
    """Build a Groq client routed through an AI Defense Gateway connection."""
    return Groq(api_key=api_key, base_url=gateway_url)


def _extract_block_reason(body: Optional[object]) -> str:
    """Best-effort extraction of a human-readable reason from a block response body.

    Cisco does not publish the raw HTTP block-response schema for Gateway
    mode, so this checks a few plausible field names and falls back to a
    generic message if none match.
    """
    if isinstance(body, dict):
        for key in ("reason", "message", "action", "error"):
            value = body.get(key)
            if value:
                return str(value)
    return "Gateway가 요청을 차단했습니다."


def chat_completion_via_gateway(
    client: Groq,
    system_prompt: str,
    history: List[Dict[str, str]],
    user_message: str,
    model: str = DEFAULT_MODEL,
) -> str:
    """Send a chat completion through the AI Defense Gateway.

    Raises AIDefenseGatewayBlocked if the Gateway blocks the request or response.
    """
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(model=model, messages=messages)
    except groq.APIStatusError as exc:
        raise AIDefenseGatewayBlocked(f"{_extract_block_reason(exc.body)} (HTTP {exc.status_code})") from exc

    return response.choices[0].message.content
