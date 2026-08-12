import os

import streamlit as st
from dotenv import load_dotenv

from petebot.ai_defense import check_input, redact_output
from petebot.llm import DEFAULT_MODEL, chat_completion, get_client
from petebot.system_prompt import SYSTEM_PROMPT

load_dotenv()

st.set_page_config(page_title="PeteBot", page_icon="🤖")
st.title("🤖 PeteBot — Cisco IT 헬프데스크")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "detection_log" not in st.session_state:
    st.session_state.detection_log = []

with st.sidebar:
    st.subheader("🛡️ AI Defense")
    defense_on = st.toggle("AI Defense", value=False)
    st.caption("데모용 목업 필터입니다. 실제 Cisco AI Defense 엔진이 아닙니다.")

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

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

user_input = st.chat_input("메시지를 입력하세요...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    if defense_on:
        matched_pattern = check_input(user_input)
        if matched_pattern:
            reply = "⚠️ AI Defense가 프롬프트 인젝션 시도를 차단했습니다."
            st.session_state.detection_log.append(
                f"입력 차단: 패턴 `{matched_pattern}` 감지"
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

    if defense_on:
        reply, redacted_labels = redact_output(reply)
        for label in redacted_labels:
            st.session_state.detection_log.append(f"출력 마스킹: {label}")

    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.rerun()
