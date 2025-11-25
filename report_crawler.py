import requests
from bs4 import BeautifulSoup
import psycopg2
import os
import logging
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 설정
SAVE_DIR = "./pdf_reports"
os.makedirs(SAVE_DIR, exist_ok=True)

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

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def download_pdf(url, filename):
    try:
        response = requests.get(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"},
            timeout=15
        )
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(response.content)
            return True
        return False
    except Exception as e:
        logger.error(f"다운로드 에러: {e}")
        return False

def crawl_yesterday_reports():
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. 어제 날짜 계산 (형식: YY.MM.DD)
        yesterday = datetime.now() - timedelta(days=1)
        target_date_str = yesterday.strftime("%y.%m.%d")
        # 저장용 날짜 형식 (YYYY-MM-DD)
        db_date_str = yesterday.strftime("%Y-%m-%d")
        
        logger.info(f"🚀 [{target_date_str}] 일자 리포트 수집 시작...")

        page = 1
        is_collecting = True
        
        while is_collecting:
            url = f"https://finance.naver.com/research/company_list.naver?&page={page}"
            logger.info(f"--- {page} 페이지 탐색 중 ---")
            
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(res.text, "html.parser")
            
            rows = soup.select("table.type_1 tr")
            
            # 페이지에 리포트가 없으면 종료
            if not rows:
                break
                
            for row in rows:
                cols = row.find_all("td")
                # [0]종목명, [1]제목, [2]증권사, [3]파일, [4]작성일, [5]조회수
                if len(cols) < 5: continue
                
                try:
                    # 날짜 확인
                    row_date = cols[4].text.strip()
                    
                    # 미래/오늘 날짜면 패스 (아직 마감 안됐을 수 있으니)
                    if row_date > target_date_str:
                        continue
                        
                    # 어제 보다 과거면 수집 종료
                    if row_date < target_date_str:
                        logger.info(f"{row_date} 리포트 발견. 수집을 종료합니다.")
                        is_collecting = False
                        break
                    
                    # 어제 날짜의 리포트만 처리 
                    stock_name = cols[0].text.strip()
                    
                    title_tag = cols[1].find("a")
                    if not title_tag: continue
                    title = title_tag.text.strip()
                    
                    broker = cols[2].text.strip()
                    
                    # PDF 링크 추출
                    file_td = cols[3]
                    pdf_link_tag = file_td.find('a', href=True)
                    pdf_url = ""
                    
                    if pdf_link_tag and 'pdf' in pdf_link_tag['href']:
                        pdf_url = pdf_link_tag['href']
                    
                    # 파일명 생성 (특수문자 제거)
                    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
                    filename = f"{SAVE_DIR}/{stock_name}_{db_date_str}_{safe_title}.pdf"
                    
                    if pdf_url:
                        # DB 중복 체크 (이미 수집했으면 건너뜀)
                        cur.execute(
                            "SELECT 1 FROM reports WHERE title = %s AND stock_name = %s AND date = %s",
                            (title, stock_name, db_date_str)
                        )
                        if cur.fetchone():
                            continue

                        # 다운로드 및 저장
                        if download_pdf(pdf_url, filename):
                            cur.execute("""
                                INSERT INTO reports (title, stock_name, broker, date, pdf_url, file_path)
                                VALUES (%s, %s, %s, %s, %s, %s)
                            """, (title, stock_name, broker, db_date_str, pdf_url, filename))
                            conn.commit()
                            logger.info(f"수집: {stock_name} - {title}")
                    else:
                        logger.warning(f"PDF 링크 없음: {title}")

                except Exception as e:
                    logger.error(f"파싱 에러: {e}")
                    continue
            
            # 다음 페이지로
            page += 1
            
            # 혹시 모르는 예외 처리 20페이지 까지만 수집
            if page > 20:
                logger.info("최대 페이지 도달. 종료합니다.")
                break

    except Exception as e:
        logger.error(f"전체 실행 에러: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    crawl_yesterday_reports()