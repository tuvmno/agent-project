#!/bin/bash
set -e

# psql 명령어로 Airflow DB 생성 시도
# (이미 존재하면 에러가 나지만, OR || true 로 무시하고 넘어감)
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE ${POSTGRES_AIRFLOW_DB:-airflow_db}'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${POSTGRES_AIRFLOW_DB:-airflow_db}')\gexec
EOSQL
