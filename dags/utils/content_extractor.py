import logging
import os
import tempfile

import boto3
import pdfplumber
import psycopg2
from botocore.client import Config
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST"),
    "port": os.getenv("POSTGRES_PORT"),
    "database": os.getenv("POSTGRES_DB"),
    "user": os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}


def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT"),
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"),
        config=Config(signature_version="s3v4"),
        verify=False,
    )


def extract_text_from_pdf_path(file_path: str, max_chars: int = 60000) -> str:
    full_text = []

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            width, height = page.width, page.height
            crop_box = (0, height * 0.05, width, height * 0.95)
            text = page.crop(bbox=crop_box).extract_text()

            if text:
                full_text.append(text)

            if sum(len(part) for part in full_text) >= max_chars:
                break

    lines = []
    for line in "\n".join(full_text).splitlines():
        clean = " ".join(line.split())
        if len(clean) > 5:
            lines.append(clean)

    return "\n".join(lines)[:max_chars]


def process_pending_content(limit: int | None = None):
    bucket_name = os.getenv("BUCKET_NAME", "reports")
    limit = limit or int(os.getenv("CONTENT_EXTRACT_LIMIT", "20"))

    conn = get_db_connection()
    s3 = get_s3_client()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, minio_path, title
                FROM reports
                WHERE content IS NULL
                  AND minio_path IS NOT NULL
                ORDER BY date DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )
            targets = cur.fetchall()

            if not targets:
                logger.info("본문 추출 대상 리포트가 없습니다.")
                return

            logger.info("본문 추출 대상: %s건", len(targets))

            for report_id, minio_path, title in targets:
                temp_path = None
                try:
                    suffix = os.path.splitext(minio_path)[1] or ".pdf"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        temp_path = tmp.name

                    logger.info("PDF 다운로드: %s", minio_path)
                    s3.download_file(bucket_name, minio_path, temp_path)

                    content = extract_text_from_pdf_path(temp_path)
                    if not content:
                        logger.warning("본문 추출 결과가 비어 있습니다: %s", title)
                        continue

                    cur.execute(
                        "UPDATE reports SET content = %s WHERE id = %s",
                        (content, report_id),
                    )
                    conn.commit()
                    logger.info("본문 추출 완료: %s", title)

                except Exception as exc:
                    conn.rollback()
                    logger.error("본문 추출 실패 (%s): %s", title, exc)
                finally:
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)
    finally:
        conn.close()


if __name__ == "__main__":
    process_pending_content()
