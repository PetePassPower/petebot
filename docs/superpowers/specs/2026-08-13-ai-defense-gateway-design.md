# Cisco AI Defense Gateway 연결 방식 추가 — Design Spec

## Purpose
PeteBot currently supports two real integration modes for Cisco AI Defense:
Mock (local rule-based demo) and API (`petebot/ai_defense_real.py`, calls the
Chat Inspection API `/api/v1/inspect/chat` before and after the LLM call).
This adds a third mode: **Gateway**, where Cisco AI Defense sits inline as a
proxy in front of the LLM provider instead of being called out-of-band.

## Architecture
Cisco AI Defense Gateway exposes an OpenAI-compatible endpoint per
"connection":

```
https://us.gateway.aidefense.security.cisco.com/<tenant-id>/connections/<connection-id>/v1/chat/completions
```

Authentication is pass-through: the caller sends the *underlying LLM
provider's* API key as the Bearer token, and the Gateway forwards to the real
provider after inspecting the request, then inspects the response before
returning it. There is no separate "Gateway API key."

For PeteBot (which talks to Groq), Gateway mode works by pointing the Groq
Python client's `base_url` at the Gateway connection URL (up to `/v1`)
instead of Groq's default endpoint, and reusing `GROQ_API_KEY` as the Bearer
token. This replaces the existing two-step pipeline (call
`ai_defense_real.inspect_messages` → call `petebot.llm.chat_completion` →
call `inspect_messages` again) with a **single** LLM call; inspection of both
input and output happens inline inside the Gateway.

Note: Cisco's public docs describe the Gateway URL/auth pattern and a
`SecurityPolicyError` raised by the official SDK on block, but do not publish
the exact HTTP status code / JSON body schema for a blocked response at the
raw HTTP level (unlike the Inspection API, which is fully documented). Block
handling is therefore implemented defensively: catch the HTTP error, extract
whatever recognizable fields exist in the response body, and fall back to a
generic blocked message if none are found.

## New env vars (`.env.example`)
- `AI_DEFENSE_GATEWAY_URL` — full base URL up to and including `/v1`, e.g.
  `https://us.gateway.aidefense.security.cisco.com/<tenant-id>/connections/<connection-id>/v1`.
  Tenant/connection-specific, so no default value. Only required for Gateway mode.
- No new API key. `GROQ_API_KEY` (already required for the app to run) is
  reused as the Gateway Bearer token, matching the pass-through auth model.

## New module: `petebot/ai_defense_gateway.py`
- `AIDefenseGatewayBlocked(Exception)` — raised when the Gateway blocks a
  request or response; carries a human-readable reason string.
- `get_gateway_client(api_key: str, gateway_url: str) -> Groq` — returns
  `Groq(api_key=api_key, base_url=gateway_url)`.
- `chat_completion_via_gateway(client, system_prompt, history, user_message, model=DEFAULT_MODEL) -> str`
  — builds the same messages list shape as `petebot.llm.chat_completion`,
  calls `client.chat.completions.create(...)`, returns the reply text on
  success. On `groq.APIStatusError` (or similar HTTP-level error from the
  underlying SDK), extracts a reason from the response body if recognizable
  fields exist (e.g. `action`, `reason`, `message`, `error`) and raises
  `AIDefenseGatewayBlocked` with that reason, or a generic
  "Gateway가 요청을 차단했습니다" fallback if the body has no recognizable shape.
- Reuses `DEFAULT_MODEL` (`llama-3.1-8b-instant`) from `petebot/llm.py` — the
  Gateway connection routes to Groq, so the model field must be a Groq model
  name (the `gpt-4o-mini` in the example curl was specific to an OpenAI
  connection).

## `app.py` changes
- Add a third sidebar radio option: `DEFENSE_MODE_GATEWAY = "Cisco AI Defense Gateway (프록시)"`.
- Read `AI_DEFENSE_GATEWAY_URL` from env; show a sidebar warning if Gateway
  mode is selected but it's unset (mirrors the existing warning pattern for
  `AI_DEFENSE_API_KEY`).
- When `defense_mode == DEFENSE_MODE_GATEWAY`: skip the existing
  input-inspect → `llm.chat_completion` → output-inspect pipeline entirely.
  Call `chat_completion_via_gateway(...)` once with the gateway-routed
  client.
  - Success: show the reply exactly as the other modes do.
  - `AIDefenseGatewayBlocked`: append a `[Cisco AI Defense Gateway]`-prefixed
    entry to `st.session_state.detection_log` with the exception's reason,
    and show the same-style "⚠️ ... 차단했습니다" chat message used by the
    other two modes.
- A caption near the radio explains Gateway mode calls the real Cisco AI
  Defense Gateway inline (single round trip, no separate inspect calls).

## Testing
`tests/test_ai_defense_gateway.py`, following the pattern of
`tests/test_ai_defense_real.py` (monkeypatch the HTTP layer, not a live
Gateway):
1. `get_gateway_client` builds a `Groq` client with the given `base_url` and
   `api_key`.
2. A successful `chat.completions.create` call returns the message content.
3. A simulated HTTP error with a recognizable body (e.g.
   `{"action": "block", "reason": "..."}`) raises `AIDefenseGatewayBlocked`
   with that reason included.
4. A simulated HTTP error with an unrecognized/empty body still raises
   `AIDefenseGatewayBlocked` with the generic fallback message (no crash).

## README changes
- Add Gateway mode to the three-mode list at the top, describing it as the
  inline-proxy alternative to the API mode.
- Add a step to the demo script: repeat the injection/leak prompts against
  Gateway mode to compare its blocking behavior with API mode.
- Document `AI_DEFENSE_GATEWAY_URL` in the setup section and `.env.example`,
  noting it must be created per-tenant in the Cisco AI Defense console (no
  public default, unlike the Inspection API's region base URLs).

## Out of Scope
- Building/automating the Cisco console setup that produces the
  tenant-id/connection-id (manual, done by the user in Cisco's UI).
- Distinguishing *which side* (input vs. output) a Gateway block occurred on,
  since that isn't reliably derivable from the undocumented block response
  shape — the detection log entry reports the block as a single event.
- A separate Gateway-specific API key/secret — intentionally reuses
  `GROQ_API_KEY` per the pass-through auth model confirmed by the user.
