# agent-project

AI 금융 리포트 수집/분석 프로젝트입니다.

## 구조

```text
Streamlit frontend (app.py)        http://localhost:8501
  -> FastAPI backend (main.py)     http://localhost:8000
      -> Postgres reports/chunks   localhost:5432

Airflow                            http://localhost:8080
  -> dags/report_dag.py
      -> Naver Finance crawler
      -> MinIO PDF storage         http://localhost:9001

Ollama                             http://localhost:11434
```

## 한 번에 띄우기

Docker Desktop을 먼저 켠 뒤 프로젝트 루트에서 실행합니다.

```powershell
docker compose up -d --build
```

상태 확인:

```powershell
docker compose ps
```

접속 주소:

- 프론트: http://localhost:8501
- 백엔드: http://localhost:8000
- 백엔드 헬스체크: http://localhost:8000/health
- Airflow: http://localhost:8080
- MinIO 콘솔: http://localhost:9001

## 종료

```powershell
docker compose down
```

데이터까지 전부 지우고 새로 시작해야 할 때만 아래를 사용합니다.

```powershell
docker compose down -v
```

## 주요 파일

- `app.py`: Streamlit 채팅 UI
- `main.py`: FastAPI + LangChain 금융 리포트 에이전트
- `dags/report_dag.py`: Airflow DAG
- `dags/utils/daily_report_crawler.py`: 네이버 금융 리포트 크롤러
- `dags/utils/etl/`: PDF 파싱, 청킹, 임베딩, 벡터 저장 코드
- `db_init/02_schema.sql`: 새 Postgres 볼륨 생성 시 `reports`, `chunks` 테이블 생성

## 포트 역할

- `8000`: FastAPI 백엔드
- `8501`: Streamlit 프론트
- `8080`: Airflow 웹 UI
- `9000`: MinIO API
- `9001`: MinIO 웹 콘솔
- `5432`: Postgres
- `11434`: Ollama

## 자주 나는 문제

### 8000 포트가 이미 사용 중

```powershell
Get-NetTCPConnection -LocalPort 8000
```

이 프로젝트에서는 8000번을 백엔드가 써야 합니다. Streamlit은 8501번입니다.

### 컨테이너 로그 보기

```powershell
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f airflow-webserver
docker compose logs -f airflow-scheduler
```

### Airflow에서 DAG가 안 보임

```powershell
docker compose logs airflow-scheduler
```

`dags/report_dag.py` import 에러가 있으면 여기에서 보입니다.

### MinIO 버킷 확인

`docker compose up -d --build`를 실행하면 `minio-init` 서비스가 `reports` 버킷을 자동으로 만듭니다.

## 로컬 conda/venv로 따로 띄우는 방법

이제는 Docker Compose 실행을 권장합니다. 그래도 로컬 Python으로 따로 띄울 때는:

```powershell
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
streamlit run app.py --server.port 8501
```

로컬 실행에서는 `.env`의 `POSTGRES_HOST`가 `localhost`여야 합니다. Docker Compose 실행에서는 Compose가 자동으로 `my_postgres`를 넣습니다.
