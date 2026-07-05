import os
import psycopg2
from langchain_huggingface import HuggingFaceEmbeddings 
from .config import AppConfig

class PostgresVectorStore:
    def __init__(self):
        self.conn_params = {
            "host": AppConfig.POSTGRES_HOST,
            "port": AppConfig.POSTGRES_PORT,
            "database": AppConfig.POSTGRES_DB,
            "user": AppConfig.POSTGRES_USER,
            "password": AppConfig.POSTGRES_PASSWORD
        }
        
        # 임베딩 모델 초기화
        current_dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.join(current_dir, "../../../models", "ko-sbert-nli") 

        self.embeddings = HuggingFaceEmbeddings(
            model_name=model_path,
            model_kwargs={'device': 'cuda'}, 
            encode_kwargs={'normalize_embeddings': True}
        )

    def get_connection(self):
        return psycopg2.connect(**self.conn_params)

    def get_pending_reports(self, limit=1):
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                # cur.execute("SELECT id, minio_path, title FROM reports WHERE is_processed = FALSE LIMIT %s", (limit,))
                cur.execute("SELECT id, minio_path, title FROM reports WHERE id = 1 LIMIT %s", (limit,))

                return cur.fetchall()
        finally:
            conn.close()

    def save_chunk(self, report_id, content, data_type="text"):
        # content가 Document 객체라면 텍스트만 추출
        if hasattr(content, "page_content"):
            real_content = content.page_content
        
        # 임베딩 생성
        vector = self.embeddings.embed_query(real_content)
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO chunks (report_id, content, embedding, data_type)
                    VALUES (%s, %s, %s, %s)
                """, (report_id, real_content, vector, data_type))
            conn.commit()
        finally:
            conn.close()

    def mark_as_processed(self, report_id):
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE reports SET is_processed = TRUE WHERE id = %s", (report_id,))
            conn.commit()
        finally:
            conn.close()