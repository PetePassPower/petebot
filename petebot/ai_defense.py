"""Mock 'AI Defense' filters for the PeteBot demo.

These are simple, deterministic rule-based checks meant to visually
demonstrate the concept of an AI guardrail during a live demo. They are not
the real Cisco AI Defense engine.
"""
import re
from typing import Dict, List, Optional, Tuple

INJECTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"disregard (all |any )?(previous|prior|above) instructions",
    r"시스템\s*프롬프트",
    r"이전\s*지시.{0,10}무시",
    r"숨겨진\s*지시",
    r"reveal.{0,20}(prompt|instructions|secret)",
    r"what (is|are) your (system prompt|instructions)",
]

SECRET_PATTERNS: Dict[str, str] = {
    "관리자 비밀번호": r"P@ssw0rd_IT2024!",
    "내부 API 키": r"sk-internal-CiscoHelpdesk-[A-Za-z0-9]+",
    "VPN 비밀번호": r"Vpn#2024Secure",
    "급여 정보": r"62,000,000\s*원",
}


def check_input(text: str) -> Optional[str]:
    """Return the matched injection pattern, or None if input looks clean."""
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


def redact_output(text: str) -> Tuple[str, List[str]]:
    """Redact known secret-shaped substrings.

    Returns (redacted_text, labels_redacted).
    """
    redacted = text
    labels: List[str] = []
    for label, pattern in SECRET_PATTERNS.items():
        if re.search(pattern, redacted):
            redacted = re.sub(pattern, "[REDACTED by AI Defense]", redacted)
            labels.append(label)
    return redacted, labels
