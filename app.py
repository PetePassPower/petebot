import os

import streamlit as st
from dotenv import load_dotenv

from petebot.ai_defense import check_input, redact_output
from petebot.ai_defense_gateway import AIDefenseGatewayBlocked, chat_completion_via_gateway, get_gateway_client
from petebot.ai_defense_real import AIDefenseError, DEFAULT_BASE_URL, describe_verdict, inspect_messages
from petebot.llm import DEFAULT_MODEL, chat_completion, get_client
from petebot.system_prompt import SYSTEM_PROMPT

load_dotenv()

DEFENSE_MODE_OFF = "끄기"
DEFENSE_MODE_MOCK = "Mock 필터 (데모용)"
DEFENSE_MODE_REAL = "Cisco AI Defense API (실제)"
DEFENSE_MODE_GATEWAY = "Cisco AI Defense Gateway (프록시)"

st.set_page_config(page_title="PeteBot", page_icon="🤖")
st.title("🤖 PeteBot")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "detection_log" not in st.session_state:
    st.session_state.detection_log = []

with st.sidebar:
    st.subheader("🛡️ AI Defense")
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

    if st.button("대화 초기화"):
        st.session_state.messages = []
        st.session_state.detection_log = []
        st.rerun()

    st.subheader("탐지 로그")
    if st.session_state.detection_log:
        for entry in st.session_state.detection_log:
            st.write(f"- {entry}")
    else:
        st.write("_아직 탐지된 항목이 없습니다._")

api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    st.warning("GROQ_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
    st.stop()

client = get_client(api_key)

ai_defense_api_key = os.getenv("AI_DEFENSE_API_KEY")
ai_defense_base_url = os.getenv("AI_DEFENSE_BASE_URL", DEFAULT_BASE_URL)
if defense_mode == DEFENSE_MODE_REAL and not ai_defense_api_key:
    st.sidebar.warning("AI_DEFENSE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

gateway_url = os.getenv("AI_DEFENSE_GATEWAY_URL")
if defense_mode == DEFENSE_MODE_GATEWAY and not gateway_url:
    st.sidebar.warning("AI_DEFENSE_GATEWAY_URL이 설정되지 않았습니다. .env 파일을 확인하세요.")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

user_input = st.chat_input("메시지를 입력하세요...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    if defense_mode == DEFENSE_MODE_GATEWAY:
        if not gateway_url:
            reply = "⚠️ AI_DEFENSE_GATEWAY_URL이 설정되지 않아 Gateway 모드를 사용할 수 없습니다."
        else:
            try:
                gateway_client = get_gateway_client(api_key, gateway_url)
                reply = chat_completion_via_gateway(
                    gateway_client,
                    SYSTEM_PROMPT,
                    st.session_state.messages[:-1],
                    user_input,
                    model=DEFAULT_MODEL,
                )
            except AIDefenseGatewayBlocked as exc:
                st.session_state.detection_log.append(f"[Cisco AI Defense Gateway] 차단: {exc}")
                reply = f"⚠️ Cisco AI Defense Gateway가 요청을 차단했습니다. ({exc})"
            except Exception as exc:
                reply = f"⚠️ 오류가 발생했습니다: {exc}"

        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()

    if defense_mode == DEFENSE_MODE_MOCK:
        matched_pattern = check_input(user_input)
        if matched_pattern:
            reply = "⚠️ AI Defense가 프롬프트 인젝션 시도를 차단했습니다."
            st.session_state.detection_log.append(
                f"[Mock] 입력 차단: 패턴 `{matched_pattern}` 감지"
            )
            st.session_state.messages.append({"role": "assistant", "content": reply})
            st.rerun()

    elif defense_mode == DEFENSE_MODE_REAL and ai_defense_api_key:
        try:
            verdict = inspect_messages(
                ai_defense_api_key,
                [{"role": "user", "content": user_input}],
                base_url=ai_defense_base_url,
            )
        except AIDefenseError as exc:
            st.session_state.detection_log.append(f"[Cisco AI Defense] 입력 검사 실패: {exc}")
        else:
            if not verdict.get("is_safe", True):
                reply = "⚠️ Cisco AI Defense API가 입력을 차단했습니다."
                st.session_state.detection_log.append(
                    f"[Cisco AI Defense] 입력 차단: {describe_verdict(verdict)}"
                )
                st.session_state.messages.append({"role": "assistant", "content": reply})
                st.rerun()

    try:
        reply = chat_completion(
            client,
            SYSTEM_PROMPT,
            st.session_state.messages[:-1],
            user_input,
            model=DEFAULT_MODEL,
        )
    except Exception as exc:
        reply = f"⚠️ 오류가 발생했습니다: {exc}"
        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()

    if defense_mode == DEFENSE_MODE_MOCK:
        reply, redacted_labels = redact_output(reply)
        for label in redacted_labels:
            st.session_state.detection_log.append(f"[Mock] 출력 마스킹: {label}")

    elif defense_mode == DEFENSE_MODE_REAL and ai_defense_api_key:
        try:
            verdict = inspect_messages(
                ai_defense_api_key,
                [{"role": "assistant", "content": reply}],
                base_url=ai_defense_base_url,
            )
        except AIDefenseError as exc:
            st.session_state.detection_log.append(f"[Cisco AI Defense] 출력 검사 실패: {exc}")
        else:
            if not verdict.get("is_safe", True):
                st.session_state.detection_log.append(
                    f"[Cisco AI Defense] 출력 차단: {describe_verdict(verdict)}"
                )
                reply = "⚠️ Cisco AI Defense API가 응답에서 위반 사항을 감지하여 표시를 차단했습니다."

    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.rerun()
