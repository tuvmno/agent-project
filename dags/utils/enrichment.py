import os
import psycopg2
import logging
import pdfplumber
import re
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

# 환경 변수 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)
logger = logging.getLogger(__name__)

# DB 연결 설정
DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST"),
    "port": os.getenv("POSTGRES_PORT"),
    "database": os.getenv("POSTGRES_DB"),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD")
}

# LLM 설정 (Gemini)
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", 
    temperature=0,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

# PDF에서 텍스트 추출
def extract_text_from_pdf(file_path):
    if not os.path.exists(file_path):
        return None
        
    full_text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                # 상단 5%, 하단 5% 제외하고 본문만 추출 (증권사 로고 등 제거)
                width, height = page.width, page.height
                crop_box = (0, height * 0.05, width, height * 0.95)
                
                cropped_page = page.crop(bbox=crop_box)
                text = cropped_page.extract_text()
                if text:
                    full_text += text + "\n"
        
        # 전처리: 너무 짧은 줄이나 불필요한 공백 제거
        lines = [line.strip() for line in full_text.split('\n') if len(line.strip()) > 5]
        return '\n'.join(lines)
    except Exception as e:
        logger.error(f"PDF 읽기 실패 ({file_path}): {e}")
        return None

# LLM을 사용하여 리포트 내용 요약
def generate_summary(content):
    try:
        # 토큰 제한 고려하여 앞부분 10,000자만 사용
        input_text = content[:10000]
        
        prompt = f"""
        너는 전문 주식 애널리스트야. 아래 증권사 리포트 본문을 읽고 투자자에게 도움이 되도록 핵심을 3줄로 요약해줘.
        
        [요약 가이드]
        1. 투자의견(매수/중립 등)과 목표주가가 있다면 반드시 포함할 것.
        2. 실적 전망이나 주요 이슈를 명확하게 적을 것.
        3. 말투는 "~함", "~임" 등의 개조식으로 간결하게 작성할 것.
        4. 요약 내용을 1.내용 2.내용 3.내용 형식으로 작성할 것.
        5. 요약 내용 3줄 이외의 다른 내용은 절대 포함하지 말 것.
        
        [리포트 본문]
        {input_text}

        [요약문]
        """
        
        response = llm.invoke(prompt)
        return response.content
    except Exception as e:
        logger.error(f"LLM 요약 실패: {e}")
        return None

def process_data():
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # 텍스트 추출이 안 된 리포트 조회
        cur.execute("SELECT id, file_path FROM reports WHERE content IS NULL")
        rows = cur.fetchall()
        
        if rows:
            logger.info(f"텍스트 변환 대기: {len(rows)}건")
            for r_id, file_path in rows:
                # 텍스트 추출 작업
                text = extract_text_from_pdf(file_path)
                if text:
                    # DB에 텍스트 저장
                    cur.execute("UPDATE reports SET content = %s WHERE id = %s", (text, r_id))
                    conn.commit()
                    logger.info(f"  Let -> 텍스트 변환 완료 (ID: {r_id})")
        
        # 요약이 안 된 리포트 조회
        cur.execute("SELECT id, title, content FROM reports WHERE content IS NOT NULL AND summary IS NULL")
        rows = cur.fetchall()
        
        if rows:
            logger.info(f"AI 요약 대기: {len(rows)}건")
            for r_id, title, content in rows:
                logger.info(f"  Processing Summary... {title}")
                # 요약 작업
                summary = generate_summary(content)
                if summary:
                    cur.execute("UPDATE reports SET summary = %s WHERE id = %s", (summary, r_id))
                    conn.commit()
                    logger.info(f"  Done -> 요약 완료!")
        
        if not rows and not cur.rowcount:
            logger.info("처리할 데이터가 없습니다. 모든 리포트가 최신 상태입니다.")

    except Exception as e:
        logger.error(f"작업 중 에러 발생: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    process_data()