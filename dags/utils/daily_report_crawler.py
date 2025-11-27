import requests
from bs4 import BeautifulSoup
import psycopg2
import os
import logging
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
import boto3
from botocore.client import Config
import io

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# 환경변수 & 설정
DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST"),
    "port": os.getenv("POSTGRES_PORT"),
    "database": os.getenv("POSTGRES_DB"),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD")
}

# 크롤링 대상 설정
# 네이버 금융 리포트 페이지 
TARGETS = {
    "market": {
        "url": "https://finance.naver.com/research/market_info_list.naver",
    },
    "invest": {
        "url": "https://finance.naver.com/research/invest_list.naver",
    },
    "stock": {
        "url": "https://finance.naver.com/research/company_list.naver", 
    },
}

# 버킷 연결
def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=os.getenv("MINIO_ENDPOINT"),
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"),
        config=Config(signature_version='s3v4'),
        verify=False
    )

# DB 연결
def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

# 파일 업로드
def upload_to_minio(s3, url, filename):
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, stream=True)
        if response.status_code == 200:
            file_obj = io.BytesIO(response.content)
            
            print(file_obj, os.getenv("BUCKET_NAME"), filename)
            
            s3.upload_fileobj(file_obj, os.getenv("BUCKET_NAME"), filename)
            return True
        return False
    except Exception as e:
        logger.error(f"업로드 실패: {e}")
        return False

# 카테고리별 크롤링
def crawl_category(category, config, target_date_str, db_date_str, s3, conn):
    """특정 카테고리 크롤링 로직"""
    cur = conn.cursor()
    page = 1
    is_collecting = True
    
    logger.info(f"[{category}] 수집 시작...")

    while is_collecting:
        url = f"{config['url']}?&page={page}"
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(res.text, "html.parser")
            rows = soup.select("table.type_1 tr")
            
            if not rows: break

            for row in rows:
                cols = row.find_all("td")
  
                if len(cols) < 5: continue
  
                try:
                    # 리서치별 컬럼 구조                   
                    # 시황: [0]제목 [1]증권사 [2]파일 [3]날짜 [4]조회수
                    # 투자: [0]제목 [1]증권사 [2]파일 [3]날짜 [4]조회수
                    # 종목: [0]종목 [1]제목 [2]증권사 [3]파일 [4]날짜 [5]조회수
                    
                    
                    # 모든 리서치가 날짜는 마지막에서 두번째 컬럼
                    row_date = cols[-2].text.strip()

                    # 목표날짜 데이터만 수집
                    if row_date > target_date_str: continue
                    if row_date < target_date_str:
                        is_collecting = False
                        break

                    # 데이터 추출
                    stock_name = None
                    stock_code = None
                    
                    if category == "stock":
                        # 종목 리포트
                        stock_td = cols[0]
                        stock_name = stock_td.text.strip()
                        stock_link = stock_td.find('a')['href']
                        code_match = re.search(r'code=(\d+)', stock_link)
                        stock_code = code_match.group(1) if code_match else ""
                        
                        title = cols[1].find("a").text.strip()
                        broker = cols[2].text.strip()
                        file_td = cols[3]
                    else:
                        # 종목 없는 리포트
                        stock_name = None # 시황, 투자 등은 종목명이 없음
                        stock_code = None # 종목 코드 없음 
                        
                        title = cols[0].find("a").text.strip()
                        broker = cols[1].text.strip()
                        file_td = cols[2]

                    # PDF 링크 추출
                    pdf_link_tag = file_td.find('a', href=True)
                    if pdf_link_tag and 'pdf' in pdf_link_tag['href']:
                        pdf_url = pdf_link_tag['href']
                        
                        # 리포트 제목 불필요 특수문자 제거 
                        safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
                        
                        # 종목명이 없으면 제목만 있으면 종목명_종목코드_제목 
                        if category == "stock":
                            filename = f"{stock_name}_{stock_code}_{safe_title}.pdf"
                        else:
                            filename = f"{safe_title}.pdf"
                        
                        # 경로: category/date/filename
                        object_name = f"{category}/{db_date_str}/{filename}"

                        # DB 중복 체크
                        cur.execute(
                            "SELECT 1 FROM reports WHERE title = %s AND date = %s AND category = %s",
                            (title, db_date_str, category)
                        )
                        if cur.fetchone(): continue

                        # 업로드 & 저장
                        if upload_to_minio(s3, pdf_url, object_name):
                            cur.execute("""
                                INSERT INTO reports (title, stock_name, stock_code, broker, date, category, pdf_url, minio_path)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            """, (title, stock_name, stock_code, broker, db_date_str, category, pdf_url, object_name))
                            conn.commit()
                            logger.info(f"[{category}] 저장: {title}")
                            
                        
                except Exception as e:
                    logger.error(f"파싱 에러: {e}")
                    continue

            page += 1
            # 리포트가 아무림 많아도 20페이지는 넘지 않을 것
            if page > 20: break 

        except Exception as e:
            logger.error(f"페이지 에러: {e}")
            break


# 일단위 리포트 크롤러 메인 함수
def crawl_reports():
    s3 = get_s3_client()
    conn = get_db_connection()
    
    # 어제 날짜
    kst_now = datetime.utcnow() + timedelta(hours=9)
    yesterday = kst_now - timedelta(days=1)
    target_date_str = yesterday.strftime("%y.%m.%d") # 네이버 날짜 포맷
    db_date_str = yesterday.strftime("%Y-%m-%d")     # DB 저장용 포맷
    
    try:
        # 시황, 투자, 종목 리포트 크롤링
        for category, config in TARGETS.items():
            crawl_category(category, config, target_date_str, db_date_str, s3, conn)
            
    finally:
        conn.close()

if __name__ == "__main__":
    crawl_reports()