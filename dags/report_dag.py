from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import sys
import os

# utils 폴더 경로 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.daily_report_crawler import crawl_reports
from utils.enrichment import process_data
from utils.content_extractor import process_pending_content
import pendulum

# 한국 시간대 설정
kst = pendulum.timezone("Asia/Seoul")

default_args = {
    'owner': 'hongkyun',
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    dag_id='daily_report_pipeline',
    default_args=default_args,
    description='증권사 리포트 수집 및 AI 요약 파이프라인',
    schedule_interval='0 7 * * *',  # 매일 아침 7시
    start_date=datetime(2023, 1, 1, tzinfo=kst), # 한국 시간대 설정
    catchup=False,
    tags=['finance', 'etl', 'ai'],
) as dag:

    # 태스크 1: 수집 (Crawler)
    task_crawl = PythonOperator(
        task_id='crawl_reports',
        python_callable=crawl_reports
    )

    # 태스크 2: 가공 & 요약 (Enrichment)
    task_extract_content = PythonOperator(
        task_id='extract_report_content',
        python_callable=process_pending_content
    )

    # 순서 정의: 수집이 성공해야 -> 가공을 시작한다
    task_crawl >> task_extract_content
