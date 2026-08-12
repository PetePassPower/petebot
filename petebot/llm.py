"""Thin wrapper around the Groq chat completions API."""
from typing import Dict, List

from groq import Groq

DEFAULT_MODEL = "llama-3.1-8b-instant"


def get_client(api_key: str) -> Groq:
    return Groq(api_key=api_key)


def chat_completion(
    client: Groq,
    system_prompt: str,
    history: List[Dict[str, str]],
    user_message: str,
    model: str = DEFAULT_MODEL,
) -> str:
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content
