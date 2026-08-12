import re

from petebot.ai_defense import SECRET_PATTERNS
from petebot.system_prompt import SYSTEM_PROMPT


def test_system_prompt_contains_every_planted_secret():
    for label, pattern in SECRET_PATTERNS.items():
        assert re.search(pattern, SYSTEM_PROMPT), f"missing secret for {label}"


def test_system_prompt_instructs_not_to_reveal_secrets():
    assert "알려드릴 수 없습니다" in SYSTEM_PROMPT
