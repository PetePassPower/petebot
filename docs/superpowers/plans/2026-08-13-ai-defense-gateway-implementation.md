# Cisco AI Defense Gateway Connection Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third Cisco AI Defense filter mode to PeteBot — "Gateway (프록시)" — that routes the LLM call through the Cisco AI Defense Gateway's OpenAI-compatible proxy endpoint instead of calling the Inspection API out-of-band.

**Architecture:** New module `petebot/ai_defense_gateway.py` wraps a `Groq` client whose `base_url` points at the Gateway connection URL (auth is pass-through: `GROQ_API_KEY` is reused as the Bearer token). `app.py` gets a third radio option that, when selected, calls this module's single combined completion+inspection function instead of the existing two-step (inspect → LLM call → inspect) pipeline used by Mock/Real modes.

**Tech Stack:** Python, Streamlit, the `groq` SDK (OpenAI-compatible client), `pytest`.

## Global Constraints

- No new third-party dependencies — `groq` (already in `requirements.txt`) is reused.
- Bearer auth for Gateway calls reuses `GROQ_API_KEY`; do not add a separate Gateway API key env var.
- New env var: `AI_DEFENSE_GATEWAY_URL` — full base URL up to and including `/v1`, no default value.
- Default model for Gateway calls is `petebot.llm.DEFAULT_MODEL` (`llama-3.1-8b-instant`).
- All new user-facing strings (captions, warnings, log entries) are in Korean, matching the existing UI's language.
- Follow the existing fake-client test pattern from `tests/test_llm.py` (a hand-rolled fake `Groq`-shaped object with `.chat.completions.create`) rather than mocking HTTP transport — Gateway blocks are simulated by raising `groq.APIStatusError` subclasses from the fake's `create()`.
- Run tests with `python -m pytest` (not bare `pytest`) — this repo has no pytest config/rootdir setup, so bare `pytest` fails to resolve the `petebot` package import; `python -m pytest` puts the cwd on `sys.path` and works.

---

### Task 1: `petebot/ai_defense_gateway.py` module

**Files:**
- Create: `petebot/ai_defense_gateway.py`
- Test: `tests/test_ai_defense_gateway.py`

**Interfaces:**
- Consumes: `petebot.llm.DEFAULT_MODEL` (`str`, already exists).
- Produces (for Task 2 to consume):
  - `class AIDefenseGatewayBlocked(Exception)`
  - `get_gateway_client(api_key: str, gateway_url: str) -> groq.Groq`
  - `chat_completion_via_gateway(client: groq.Groq, system_prompt: str, history: list[dict], user_message: str, model: str = DEFAULT_MODEL) -> str` — raises `AIDefenseGatewayBlocked` on a blocked request/response.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ai_defense_gateway.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ai_defense_gateway.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'petebot.ai_defense_gateway'`

- [ ] **Step 3: Write the implementation**

Create `petebot/ai_defense_gateway.py`:

```python
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
        raise AIDefenseGatewayBlocked(_extract_block_reason(exc.body)) from exc

    return response.choices[0].message.content
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ai_defense_gateway.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add petebot/ai_defense_gateway.py tests/test_ai_defense_gateway.py
git commit -m "Add Cisco AI Defense Gateway client module"
```

---

### Task 2: Wire Gateway mode into `app.py`

**Files:**
- Modify: `app.py`

**Interfaces:**
- Consumes: `petebot.ai_defense_gateway.AIDefenseGatewayBlocked`, `.get_gateway_client`, `.chat_completion_via_gateway` (from Task 1); `petebot.llm.DEFAULT_MODEL` (existing).
- Produces: nothing consumed by later tasks (UI leaf).

No dedicated automated test — this app has no Streamlit test harness (only `tests/test_ai_defense.py`, `test_ai_defense_real.py`, `test_llm.py`, `test_system_prompt.py` exist, all pure-function tests). Verify manually in Step 3 below, matching how Mock/Real modes were verified per the original spec's Testing section.

- [ ] **Step 1: Add the import and the new mode constant**

In `app.py`, replace the import block (current lines 6-9):

```python
from petebot.ai_defense import check_input, redact_output
from petebot.ai_defense_real import AIDefenseError, DEFAULT_BASE_URL, describe_verdict, inspect_messages
from petebot.llm import DEFAULT_MODEL, chat_completion, get_client
from petebot.system_prompt import SYSTEM_PROMPT
```

with:

```python
from petebot.ai_defense import check_input, redact_output
from petebot.ai_defense_gateway import AIDefenseGatewayBlocked, chat_completion_via_gateway, get_gateway_client
from petebot.ai_defense_real import AIDefenseError, DEFAULT_BASE_URL, describe_verdict, inspect_messages
from petebot.llm import DEFAULT_MODEL, chat_completion, get_client
from petebot.system_prompt import SYSTEM_PROMPT
```

Replace the mode constants (current lines 13-15):

```python
DEFENSE_MODE_OFF = "끄기"
DEFENSE_MODE_MOCK = "Mock 필터 (데모용)"
DEFENSE_MODE_REAL = "Cisco AI Defense API (실제)"
```

with:

```python
DEFENSE_MODE_OFF = "끄기"
DEFENSE_MODE_MOCK = "Mock 필터 (데모용)"
DEFENSE_MODE_REAL = "Cisco AI Defense API (실제)"
DEFENSE_MODE_GATEWAY = "Cisco AI Defense Gateway (프록시)"
```

- [ ] **Step 2: Add the radio option, caption, and sidebar warning**

Replace the sidebar radio + caption block (current lines 27-35):

```python
    defense_mode = st.radio(
        "필터 모드",
        options=[DEFENSE_MODE_OFF, DEFENSE_MODE_MOCK, DEFENSE_MODE_REAL],
        index=0,
    )
    if defense_mode == DEFENSE_MODE_MOCK:
        st.caption("데모용 목업 필터입니다. 실제 Cisco AI Defense 엔진이 아닙니다.")
    elif defense_mode == DEFENSE_MODE_REAL:
        st.caption("Cisco AI Defense Chat Inspection API를 실시간으로 호출합니다.")
```

with:

```python
    defense_mode = st.radio(
        "필터 모드",
        options=[DEFENSE_MODE_OFF, DEFENSE_MODE_MOCK, DEFENSE_MODE_REAL, DEFENSE_MODE_GATEWAY],
        index=0,
    )
    if defense_mode == DEFENSE_MODE_MOCK:
        st.caption("데모용 목업 필터입니다. 실제 Cisco AI Defense 엔진이 아닙니다.")
    elif defense_mode == DEFENSE_MODE_REAL:
        st.caption("Cisco AI Defense Chat Inspection API를 실시간으로 호출합니다.")
    elif defense_mode == DEFENSE_MODE_GATEWAY:
        st.caption("Cisco AI Defense Gateway를 통해 LLM 호출 자체를 프록시합니다 (인라인 검사, 단일 호출).")
```

Replace the env var block (current lines 56-59):

```python
ai_defense_api_key = os.getenv("AI_DEFENSE_API_KEY")
ai_defense_base_url = os.getenv("AI_DEFENSE_BASE_URL", DEFAULT_BASE_URL)
if defense_mode == DEFENSE_MODE_REAL and not ai_defense_api_key:
    st.sidebar.warning("AI_DEFENSE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
```

with:

```python
ai_defense_api_key = os.getenv("AI_DEFENSE_API_KEY")
ai_defense_base_url = os.getenv("AI_DEFENSE_BASE_URL", DEFAULT_BASE_URL)
if defense_mode == DEFENSE_MODE_REAL and not ai_defense_api_key:
    st.sidebar.warning("AI_DEFENSE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

gateway_url = os.getenv("AI_DEFENSE_GATEWAY_URL")
if defense_mode == DEFENSE_MODE_GATEWAY and not gateway_url:
    st.sidebar.warning("AI_DEFENSE_GATEWAY_URL이 설정되지 않았습니다. .env 파일을 확인하세요.")
```

- [ ] **Step 3: Branch the message-handling flow for Gateway mode**

Replace the start of the `if user_input:` block (current lines 67-72):

```python
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    if defense_mode == DEFENSE_MODE_MOCK:
```

with:

```python
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    if defense_mode == DEFENSE_MODE_GATEWAY:
        if not gateway_url:
            reply = "⚠️ AI_DEFENSE_GATEWAY_URL이 설정되지 않아 Gateway 모드를 사용할 수 없습니다."
        else:
            gateway_client = get_gateway_client(api_key, gateway_url)
            try:
                reply = chat_completion_via_gateway(
                    gateway_client,
                    SYSTEM_PROMPT,
                    st.session_state.messages[:-1],
                    user_input,
                    model=DEFAULT_MODEL,
                )
            except AIDefenseGatewayBlocked as exc:
                st.session_state.detection_log.append(f"[Cisco AI Defense Gateway] 차단: {exc}")
                reply = "⚠️ Cisco AI Defense Gateway가 요청을 차단했습니다."

        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()

    if defense_mode == DEFENSE_MODE_MOCK:
```

This keeps the rest of the existing OFF/Mock/Real pipeline (the code below, from the `if defense_mode == DEFENSE_MODE_MOCK:` line onward) completely unchanged — Gateway mode always exits early via `st.rerun()` before reaching it.

- [ ] **Step 4: Manual smoke test**

Run: `streamlit run app.py`

1. With no `AI_DEFENSE_GATEWAY_URL` set, select "Cisco AI Defense Gateway (프록시)" in the sidebar — confirm the sidebar warning appears, and sending a message shows the "설정되지 않아" reply without crashing.
2. Set `AI_DEFENSE_GATEWAY_URL` in `.env` to a real Cisco AI Defense Gateway connection URL for a Groq connection (per the design doc), restart, select Gateway mode, and send a normal message — confirm a reply comes back and no warning shows.
3. Send an injection/leak prompt (see `README.md` demo script step 1) in Gateway mode — confirm either a blocked reply with a `[Cisco AI Defense Gateway]` detection-log entry, or a normal leaked reply if the connection's policy doesn't catch it (record which, for the demo script).

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "Add Cisco AI Defense Gateway filter mode to PeteBot UI"
```

---

### Task 3: Document Gateway mode in `.env.example` and `README.md`

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing (docs only).
- Produces: nothing (leaf task).

- [ ] **Step 1: Update `.env.example`**

Current content:

```
GROQ_API_KEY=your-groq-api-key-here

# Optional: only needed for the "Cisco AI Defense API (실제)" filter mode.
AI_DEFENSE_API_KEY=your-ai-defense-api-key-here
# Region base URL: us (default), ap, or eu.
# AI_DEFENSE_BASE_URL=https://us.api.inspect.aidefense.security.cisco.com
```

Replace with:

```
GROQ_API_KEY=your-groq-api-key-here

# Optional: only needed for the "Cisco AI Defense API (실제)" filter mode.
AI_DEFENSE_API_KEY=your-ai-defense-api-key-here
# Region base URL: us (default), ap, or eu.
# AI_DEFENSE_BASE_URL=https://us.api.inspect.aidefense.security.cisco.com

# Optional: only needed for the "Cisco AI Defense Gateway (프록시)" filter mode.
# Full connection URL from the Cisco AI Defense console, ending in /v1.
# No default — this is tenant/connection-specific; create a Groq connection
# in the console to get your own URL. Auth reuses GROQ_API_KEY above (the
# Gateway forwards it to Groq as-is after inspecting the request/response).
# AI_DEFENSE_GATEWAY_URL=https://us.gateway.aidefense.security.cisco.com/<tenant-id>/connections/<connection-id>/v1
```

- [ ] **Step 2: Update `README.md`**

Replace the mode list (current lines 5-11):

```markdown
assistant) used to demonstrate Cisco AI Defense against prompt injection and
sensitive data leakage. The sidebar has three filter modes:

- **끄기** — no filtering, PeteBot leaks everything.
- **Mock 필터 (데모용)** — local rule-based mock, not the real Cisco AI Defense engine.
- **Cisco AI Defense API (실제)** — calls the real Cisco AI Defense Chat Inspection
  API (`/api/v1/inspect/chat`) before sending the user's message to the LLM, and
  again on the model's reply before it's shown.
```

with:

```markdown
assistant) used to demonstrate Cisco AI Defense against prompt injection and
sensitive data leakage. The sidebar has four filter modes:

- **끄기** — no filtering, PeteBot leaks everything.
- **Mock 필터 (데모용)** — local rule-based mock, not the real Cisco AI Defense engine.
- **Cisco AI Defense API (실제)** — calls the real Cisco AI Defense Chat Inspection
  API (`/api/v1/inspect/chat`) before sending the user's message to the LLM, and
  again on the model's reply before it's shown.
- **Cisco AI Defense Gateway (프록시)** — routes the LLM call itself through the
  real Cisco AI Defense Gateway's OpenAI-compatible proxy endpoint. Inspection of
  both the input and the output happens inline inside the Gateway, in a single
  round trip, instead of PeteBot calling a separate inspect API before/after.
```

Replace the setup block (current lines 13-20):

````markdown
## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env and set GROQ_API_KEY
# optionally set AI_DEFENSE_API_KEY to use the real Cisco AI Defense API mode
```
````

with:

````markdown
## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env and set GROQ_API_KEY
# optionally set AI_DEFENSE_API_KEY to use the real Cisco AI Defense API mode
# optionally set AI_DEFENSE_GATEWAY_URL to use the Cisco AI Defense Gateway mode
# (create a Groq connection in the Cisco AI Defense console to get this URL)
```
````

Add a step to the demo script (append after the current step 4, which ends at line 41):

```markdown
5. Switch to **Cisco AI Defense Gateway (프록시)** (requires `AI_DEFENSE_GATEWAY_URL`
   in `.env`, pointing at a Groq connection in the Cisco AI Defense console) and
   repeat the same prompts to compare the Gateway's inline blocking behavior
   (single round trip, no separate inspect calls) against the API mode.
```

- [ ] **Step 3: Commit**

```bash
git add .env.example README.md
git commit -m "Document the Cisco AI Defense Gateway filter mode"
```
