# 베이스 이미지
FROM apache/airflow:2.10.3-python3.11

# 파일 컨테이너로 복사
COPY requirements.txt .

# 라이브러리 설치
RUN pip install --no-cache-dir -r requirements.txt