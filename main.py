import os
import re
from typing import List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import psycopg2
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool
from langchain.agents import create_agent
from dotenv import load_dotenv
from langsmith import Client

# 환경변수 불러오기
load_dotenv()

DEFAULT_SYSTEM_PROMPT = """
너는 증권사 리포트를 바탕으로 투자자가 이해하기 쉽게 답변하는 금융 리포트 분석 에이전트다.
사용자의 질문 의도에 맞는 도구를 사용하고, DB에서 찾은 리포트 내용을 근거로 한국어로 간결하게 답변한다.
근거 데이터가 부족하면 추측하지 말고 수집된 데이터가 부족하다고 말한다.

도구 사용 규칙:
- 사용자가 오늘/최근/시장/브리핑/시황을 물으면 get_daily_market_briefing 도구를 사용한다.
- 사용자가 특정 종목의 분석, 요약, 목표가, 리포트를 물으면 analyze_specific_stock 도구를 사용한다.
- 사용자가 키워드와 관련된 리포트 목록이나 검색을 요청하면 search_report_list 도구를 사용한다.
- 도구 결과가 비어 있거나 부족하면 그 사실을 그대로 알려준다.
"""


def load_agent_prompt():
    prompt_name = os.getenv("LANGSMITH_PROMPT", "financial-agent-prompt:88aa9995")
    api_key = os.getenv("LANGSMITH_API_KEY")

    if not api_key:
        return DEFAULT_SYSTEM_PROMPT

    try:
        client = Client(api_key=api_key)
        pulled_prompt = client.pull_prompt(prompt_name)
        if isinstance(pulled_prompt, str):
            return pulled_prompt

        print(
            "LangSmith prompt is not a plain string, "
            "using local fallback prompt for create_agent(system_prompt=...)."
        )
        return DEFAULT_SYSTEM_PROMPT
    except Exception as exc:
        print(f"LangSmith prompt load failed, using local fallback prompt: {exc}")
        return DEFAULT_SYSTEM_PROMPT


prompt = load_agent_prompt()

# 1. 유설정
DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": os.getenv("POSTGRES_PORT"),
    "database": os.getenv("POSTGRES_DB"),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD")
}

# LLM 설정
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

app = FastAPI(title="💰 AI 금융 에이전트")

class QueryRequest(BaseModel):
    question: str

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)


def format_report_line(row) -> str:
    stock_name, title, broker, category, minio_path = row
    stock_label = stock_name or category or "시장"
    storage_note = f" / PDF: {minio_path}" if minio_path else ""
    return f"- [{stock_label}] {title} ({broker}){storage_note}"


def extract_key_points(content: str, limit: int = 5) -> list[str]:
    text = " ".join(content.split())
    if not text:
        return []

    chunks = re.split(r"(?<=[.!?])\s+|(?<=다)\s+", text)
    keywords = [
        "투자의견", "목표주가", "매수", "Not Rated", "현재가",
        "매출", "영업이익", "실적", "전망", "기대", "성장",
        "수익성", "모멘텀", "리스크", "상승여력",
    ]

    points = []
    seen = set()
    for chunk in chunks:
        clean = chunk.strip()
        if len(clean) < 25:
            continue
        if not any(keyword in clean for keyword in keywords):
            continue

        clean = clean[:260]
        if clean in seen:
            continue

        seen.add(clean)
        points.append(clean)
        if len(points) >= limit:
            break

    if points:
        return points

    fallback = []
    for chunk in chunks:
        clean = chunk.strip()
        if len(clean) >= 25:
            fallback.append(clean[:260])
        if len(fallback) >= limit:
            break
    return fallback


def format_key_points(content: str, limit: int = 5) -> str:
    points = extract_key_points(content, limit=limit)
    if not points:
        return "본문에서 핵심 문장을 추출하지 못했습니다."

    return "\n".join(f"{idx}. {point}" for idx, point in enumerate(points, start=1))

# ---------------------------------------------------------
# 2. 도구(Tools) 정의
# ---------------------------------------------------------

@tool
def get_daily_market_briefing(dummy: str = "") -> str:
    """
    오늘 발행된 주요 리포트들을 종합하여 시장 브리핑을 제공합니다.
    사용자가 '오늘 시장 어때?', '시장 브리핑 해줘' 등을 물을 때 사용합니다.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT MAX(date) FROM reports")
        result = cur.fetchone()
        latest_date = result[0] if result else None
        
        if not latest_date:
            return "아직 수집된 데이터가 없습니다."

        cur.execute("""
            SELECT stock_name, title, summary 
            FROM reports 
            WHERE date = %s AND summary IS NOT NULL
            LIMIT 15 
        """, (latest_date,))
        rows = cur.fetchall()
        
        if not rows:
            cur.execute("""
                SELECT stock_name, title, broker, category, content
                FROM reports
                WHERE date = %s
                  AND content IS NOT NULL
                ORDER BY category, id DESC
                LIMIT 10
            """, (latest_date,))
            content_rows = cur.fetchall()

            if content_rows:
                context = ""
                for stock, title, broker, category, content in content_rows:
                    stock_label = stock or category or "시장"
                    context += f"- [{stock_label}] {title} ({broker})\n{content[:1200]}\n\n"

                return f"""
날짜: {latest_date}

AI 요약 컬럼은 아직 비어 있지만, PDF 본문 추출 데이터가 있어 아래 내용을 바탕으로 시장 브리핑을 작성할 수 있습니다.

{context}
"""

            cur.execute("""
                SELECT stock_name, title, broker, category, minio_path
                FROM reports
                WHERE date = %s
                ORDER BY category, id DESC
                LIMIT 20
            """, (latest_date,))
            report_rows = cur.fetchall()

            if not report_rows:
                return f"{latest_date} 일자의 수집된 리포트가 없습니다."

            report_list = "\n".join(format_report_line(row) for row in report_rows)
            return f"""
날짜: {latest_date}

수집된 리포트는 있지만 아직 본문 추출/AI 요약이 생성되지 않았습니다.
현재 DB에 있는 최신 리포트 목록은 아래와 같습니다.

{report_list}
"""

        context = ""
        for stock, title, summary in rows:
            context += f"- {stock} ({title}): {summary}\n"
            
        return f"날짜: {latest_date}\n\n{context}"
    finally:
        conn.close()

@tool
def analyze_specific_stock(stock_name: str) -> str:
    """
    특정 종목의 리포트를 찾아서 상세하게 분석하고 요약합니다.
    사용자가 '삼성전자 분석해줘', '하이닉스 목표가 얼마야?' 등을 물을 때 사용합니다.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        stock_name = stock_name.replace("분석해줘", "").replace("요약해줘", "").strip()
        
        cur.execute("""
            SELECT title, content, date FROM reports 
            WHERE (stock_name LIKE %s OR title LIKE %s) 
            AND content IS NOT NULL 
            ORDER BY date DESC LIMIT 1
        """, (f"%{stock_name}%", f"%{stock_name}%"))
        row = cur.fetchone()
        
        if row:
            title, content, date = row
            return f"""
                제목: {title}\n
                날짜: {date}\n
                본문: {content[:5000]}
                """

        cur.execute("""
            SELECT stock_name, title, broker, category, minio_path, date
            FROM reports
            WHERE stock_name LIKE %s OR title LIKE %s
            ORDER BY date DESC LIMIT 1
        """, (f"%{stock_name}%", f"%{stock_name}%"))
        meta_row = cur.fetchone()

        if not meta_row:
            return f"'{stock_name}'에 대한 최신 리포트를 찾지 못했습니다."

        stock, title, broker, category, minio_path, date = meta_row
        return f"""
제목: {title}
종목/분류: {stock or category}
증권사: {broker}
날짜: {date}
PDF 저장 위치: {minio_path}

이 리포트는 수집되어 있지만 아직 본문 추출/AI 요약이 생성되지 않았습니다.
현재 답변 가능한 정보는 리포트 메타데이터와 PDF 저장 위치까지입니다.
"""
    finally:
        conn.close()

@tool
def search_report_list(keyword: str) -> str:
    """
    특정 키워드가 포함된 리포트 목록을 검색합니다.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT title, stock_name, broker, date 
            FROM reports 
            WHERE title LIKE %s OR stock_name LIKE %s 
            ORDER BY date DESC LIMIT 5
        """, (f"%{keyword}%", f"%{keyword}%"))
        rows = cur.fetchall()
        
        if not rows:
            return f"'{keyword}' 관련 리포트가 없습니다."
            
        result = ""
        for r in rows:
            result += f"- [{r[1]}] {r[0]} ({r[2]}, {r[3]})\n"
        return result
    finally:
        conn.close()

# ---------------------------------------------------------
# 3. 에이전트 생성
# ---------------------------------------------------------

# 사용 가능 한 툴 리스트
tools = [get_daily_market_briefing, analyze_specific_stock, search_report_list]

# agent 
agent = create_agent(
        model=llm, 
        tools=tools,
        system_prompt=prompt)


def clean_keyword(text: str) -> str:
    keyword = text
    for token in [
        "리포트", "요약", "요약해줘", "분석", "분석해줘", "목표가",
        "알려줘", "해줘", "검색", "목록", "찾아줘", "브리핑",
    ]:
        keyword = keyword.replace(token, "")
    return keyword.strip()


def direct_market_briefing() -> str:
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT MAX(date) FROM reports")
        row = cur.fetchone()
        latest_date = row[0] if row else None
        if not latest_date:
            return "아직 DB에 수집된 리포트가 없습니다."

        cur.execute("""
            SELECT stock_name, title, broker, category, content, minio_path
            FROM reports
            WHERE date = %s
            ORDER BY
                CASE WHEN content IS NULL THEN 1 ELSE 0 END,
                category,
                id DESC
            LIMIT 12
        """, (latest_date,))
        rows = cur.fetchall()

        with_content = [r for r in rows if r[4]]
        if with_content:
            lines = [
                f"최신 수집일은 {latest_date}입니다. AI API를 거치지 않고 DB/PDF 본문 기준으로 보여드립니다.",
                "",
            ]
            for stock, title, broker, category, content, _ in with_content[:6]:
                label = stock or category or "시장"
                lines.append(f"### [{label}] {title} ({broker})")
                lines.append(format_key_points(content, limit=3))
                lines.append("")
            return "\n".join(lines)

        report_list = "\n".join(format_report_line((r[0], r[1], r[2], r[3], r[5])) for r in rows)
        return f"""
최신 수집일은 {latest_date}입니다.

리포트 PDF는 수집되어 있지만 아직 본문 추출/요약이 생성되지 않은 항목입니다.

{report_list}
"""
    finally:
        conn.close()


def direct_stock_report(question: str) -> str:
    keyword = clean_keyword(question)
    if not keyword:
        return direct_market_briefing()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT stock_name, title, broker, category, date, content, minio_path
            FROM reports
            WHERE stock_name LIKE %s OR title LIKE %s
            ORDER BY date DESC, id DESC
            LIMIT 1
        """, (f"%{keyword}%", f"%{keyword}%"))
        row = cur.fetchone()

        if not row:
            return f"'{keyword}' 관련 리포트를 DB에서 찾지 못했습니다."

        stock, title, broker, category, date, content, minio_path = row
        label = stock or category or keyword

        if content:
            return f"""
### [{label}] {title}

- 증권사: {broker}
- 날짜: {date}
- PDF: {minio_path}

본문 추출 데이터 기준 핵심 문장:

{format_key_points(content)}
"""

        return f"""
### [{label}] {title}

- 증권사: {broker}
- 날짜: {date}
- PDF: {minio_path}

이 리포트는 수집되어 있지만 아직 본문 추출이 끝나지 않았습니다.
"""
    finally:
        conn.close()


def direct_search_reports(question: str) -> str:
    keyword = clean_keyword(question)
    if not keyword:
        return direct_market_briefing()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT title, stock_name, broker, date, category, content IS NOT NULL
            FROM reports
            WHERE title LIKE %s OR stock_name LIKE %s
            ORDER BY date DESC, id DESC
            LIMIT 10
        """, (f"%{keyword}%", f"%{keyword}%"))
        rows = cur.fetchall()

        if not rows:
            return f"'{keyword}' 관련 리포트가 없습니다."

        lines = [f"'{keyword}' 관련 리포트 목록입니다.", ""]
        for title, stock, broker, date, category, has_content in rows:
            status = "본문 있음" if has_content else "본문 미추출"
            lines.append(f"- [{stock or category}] {title} ({broker}, {date}, {status})")
        return "\n".join(lines)
    finally:
        conn.close()


def direct_answer_if_possible(question: str) -> str | None:
    q = question.strip()
    market_keywords = ["오늘", "최근", "시장", "브리핑", "시황", "데일리", "모닝"]
    search_keywords = ["검색", "목록", "찾아", "관련 리포트"]
    stock_keywords = ["리포트", "요약", "분석", "목표가"]

    if any(keyword in q for keyword in market_keywords):
        return direct_market_briefing()
    if any(keyword in q for keyword in search_keywords):
        return direct_search_reports(q)
    if any(keyword in q for keyword in stock_keywords):
        return direct_stock_report(q)

    return None

# ---------------------------------------------------------
# 4. API 엔드포인트
# ---------------------------------------------------------

@app.post("/ask")
def ask_agent(req: QueryRequest):
    try:
        direct_answer = direct_answer_if_possible(req.question)
        if direct_answer:
            return {"answer": direct_answer}

        inputs = {"messages": [{"role":"user", "content":req.question}]}
        result = agent.invoke(inputs)
        
        # 최종 결과 추출
        last_message = result["messages"][-1]
        content = last_message.content
        
        # content가 리스트(복잡한 형태)로 오면 텍스트만 발라내기
        if isinstance(content, list):
            # 리스트 안에 있는 딕셔너리들 중 'text' 키를 가진 놈들의 값만 합침
            final_answer = "".join([item.get("text", "") for item in content if isinstance(item, dict) and "text" in item])
        else:
            # 그냥 문자열이면 그대로 사용
            final_answer = str(content)
            
        return {"answer": final_answer}
        
    except Exception as e:
        fallback_answer = direct_answer_if_possible(req.question)
        if fallback_answer:
            return {
                "answer": (
                    f"{fallback_answer}\n\n"
                    f"참고: LLM 호출은 실패해서 DB 조회 결과를 직접 반환했습니다. ({str(e)[:200]})"
                )
            }
        return {"answer": f"죄송합니다. 에러가 발생했습니다: {str(e)}"}

@app.get("/")
def root():
    return {"message": "💰 AI 리포트분석 에이전트가 실행 중입니다."}

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
