from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import sys
import os

# utils 폴더를 파이썬 경로에 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 크롤러 함수 임포트
from utils.daily_report_crawler import crawl_yesterday_reports

# 기본 설정
default_args = {
    'owner': 'hongkyun',
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# DAG 정의
with DAG(
    dag_id='daily_report_collection',
    default_args=default_args,
    description='매일 어제자 증권사 리포트 수집',
    schedule_interval='0 7 * * *',  # 매일 아침 07:00 실행 (한국 시간)
    start_date=datetime(2023, 1, 1), # 시작 날짜
    catchup=False, # 밀린 과거 데이터는 수집 안 함
    tags=['finance', 'crawler'],
) as dag:

    # 태스크 정의
    task_crawl = PythonOperator(
        task_id='crawl_naver_finance',
        python_callable=crawl_yesterday_reports 
    )

    task_crawl