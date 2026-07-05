import os
import streamlit as st
import requests

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000/ask")

st.set_page_config(
    page_title="💰 AI 금융 리포트 애널리스트",
    page_icon="📈",
    layout="wide"
)

st.title("📈 AI 금융 리포트 애널리스트")
st.caption("매일 아침 쏟아지는 증권사 리포트, AI가 핵심만 요약해서 알려드립니다.")

# 1. 세션 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.messages.append({
        "role": "assistant", 
        "content": "안녕하세요! 투자자님. \n\n'오늘 시장 브리핑해줘' 또는 '삼성전자 리포트 요약해줘' 처럼 물어보세요."
    })

# 2. 사이드바
with st.sidebar:
    st.header("🔥 빠른 실행")
    if st.button("📅 오늘의 시장 브리핑 보기", use_container_width=True):
        st.session_state.messages.append({"role": "user", "content": "오늘 시장 브리핑해줘"})
        st.rerun()
    
    st.divider()
    st.info("💡 **Tip:** 특정 종목이 궁금하면 'OOO 요약해줘'라고 입력하세요.")

# 3. 채팅 기록 표시
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. 사용자 입력 처리
if prompt := st.chat_input("질문을 입력하세요..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun()

# 5. 주소 직접 입력하여 요청 보내기
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        with st.spinner("분석 중입니다... 잠시만 기다려주세요."):
            try:
                last_user_msg = st.session_state.messages[-1]["content"]
                
                response = requests.post(BACKEND_URL, json={"question": last_user_msg}, timeout=120)
                
                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("answer", "내용 없음")
                    
                    message_placeholder.markdown(answer)
                    
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                    
                else:
                    st.error(f"❌ 서버 에러 ({response.status_code})")

            except requests.exceptions.RequestException:
                st.error("❌ 연결 실패: 백엔드 서버와 통신할 수 없습니다.")
