import os
import io
import logging
import psycopg2
import boto3
from dotenv import load_dotenv
from PIL import Image

# [New] Docling & Ollama
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableStructureOptions

from langchain_ollama import ChatOllama
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

load_dotenv(override=False)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Local_ETL")

# --- 설정 ---
DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": os.getenv("POSTGRES_PORT", 5432),
    "database": os.getenv("POSTGRES_DB", "postgres"),
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", "password")
}
MINIO_Config = {
    "endpoint_url": os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
    "aws_access_key_id": os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
    "aws_secret_access_key": os.getenv("MINIO_SECRET_KEY", "minioadmin"),
}
BUCKET_NAME = "reports"
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://my_ollama:11434") # 도커 내부 통신

# 1. 모델 초기화 (전부 로컬!)
# (1) 비전 모델: Ollama LLaVA
vision_model = ChatOllama(
    model="llava",
    base_url=OLLAMA_URL,
    temperature=0
)

# (2) 임베딩 모델: 로컬 HuggingFace (GPU 사용)
# device='cuda'로 설정하여 RTX 5070 활용
embedding_model = HuggingFaceEmbeddings(
    model_name="jhgan/ko-sbert-nli",
    model_kwargs={'device': 'cuda'}, 
    encode_kwargs={'normalize_embeddings': True}
)

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def get_s3_client():
    return boto3.client('s3', **MINIO_Config)

def describe_image_with_ollama(pil_image):
    """이미지(PIL)를 Ollama(LLaVA)에게 보내 설명을 받음"""
    try:
        # 이미지를 바이트로 변환
        img_byte_arr = io.BytesIO()
        pil_image.save(img_byte_arr, format='PNG')
        img_bytes = img_byte_arr.getvalue()
        
        # LangChain Ollama는 이미지 바이트를 직접 지원하지 않을 수 있어 base64 변환
        import base64
        b64_img = base64.b64encode(img_bytes).decode('utf-8')

        # 프롬프트: "이 차트나 이미지를 상세하게 설명해줘"
        # LLaVA는 영어 성능이 더 좋으므로 영어로 묻고 한국어 번역을 시키거나, 
        # 단순하게 차트 데이터 추출을 요청
        msg = [
            {"type": "text", "text": "Analyze this chart or image and describe the key data points and trends in detail."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}"}}
        ]
        # (참고: langchain_ollama 최신 버전에 따라 msg 구조가 다를 수 있음. 
        # 간단히 bind_tools 없이 invoke 호출)
        # LLaVA에게 직접 멀티모달 요청은 라이브러리 버전에 따라 까다로울 수 있어,
        # 여기서는 개념적으로 '이미지 설명 생성' 호출
        
        # Ollama API 직접 호출 방식 (안정적)
        import requests
        res = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": "llava",
            "prompt": "Describe this image in detail. If it's a chart, extracting numbers.",
            "images": [b64_img],
            "stream": False
        })
        return res.json()['response']

    except Exception as e:
        logger.error(f"Vision processing error: {e}")
        return ""


def process_reports():
    conn = get_db_connection()
    cur = conn.cursor()
    s3 = get_s3_client()

    # Docling 설정
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_table_structure = True
    pipeline_options.do_ocr = True
    pipeline_options.images_scale = 2.0 
    pipeline_options.generate_page_images = True 
    pipeline_options.generate_picture_images = True
    
    
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    try:
        cur.execute("SELECT id, minio_path, title FROM reports WHERE id = 1 LIMIT 1")
        targets = cur.fetchall()
        
        if not targets:
            logger.info("✨ 처리할 데이터 없음")
            return

        for r_id, minio_path, title in targets:
            logger.info(f"🔄 Processing: {title}")
            
            # 1. MinIO -> 로컬 다운로드
            filename = minio_path.split('/')[-1]
            temp_pdf = f"/tmp/{filename}"
            s3.download_file(BUCKET_NAME, minio_path, temp_pdf)

            # 2. Docling 파싱
            logger.info("   -> Docling으로 문서 구조 분석 중...")
            conv_result = converter.convert(temp_pdf)
            doc = conv_result.document
            
            # 3. 기본 마크다운 변환
            full_markdown = doc.export_to_markdown()
            
            # 4. [핵심 추가] 이미지 설명 생성 및 병합
            # Docling은 문서 내 그림들을 'pictures' 리스트에 담아줍니다.
            if doc.pictures:
                logger.info(f"   -> 📸 이미지 {len(doc.pictures)}개 발견! Vision AI 분석 시작...")
                
                for i, picture in enumerate(doc.pictures):
                    # 이미지가 없는 경우도 있으므로 체크
                    pil_image = picture.get_image(doc)
                    
                    if pil_image:
                        # 이미지 데이터를 Ollama에게 보내 설명 생성
                        description = describe_image_with_ollama(pil_image)
                        
                        if description:
                            # 본문 끝에 차트 설명을 덧붙입니다. (RAG가 읽을 수 있게)
                            # (더 정교하게 하려면 마크다운 내의 이미지 위치를 찾아서 교체해야 하지만, 
                            #  append 방식이 가장 안전하고 구현이 쉽습니다.)
                            full_markdown += f"\n\n### [차트/이미지 설명 {i+1}]\n{description}\n"
            
            logger.info("   -> 텍스트 청킹 및 벡터화...")
            
            # 5. 청킹 (Chunking)
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000, 
                chunk_overlap=200,
                separators=["\n## ", "\n### ", "\n", " ", ""] # 마크다운 헤더 기준 분할
            )
            chunks = splitter.split_text(full_markdown)
            
            # 6. 저장 (Embedding & Vector Store)
            for chunk in chunks:
                vector = embedding_model.embed_query(chunk)
                cur.execute("""
                    INSERT INTO chunks (report_id, content, embedding, page_num)
                    VALUES (%s, %s, %s, %s)
                """, (r_id, chunk, vector, 1))
            
            # 완료 처리
            cur.execute("UPDATE reports SET is_processed = TRUE WHERE id = %s", (r_id,))
            conn.commit()
            logger.info(f"✅ 완료: {title}")
            
            if os.path.exists(temp_pdf):
                os.remove(temp_pdf)

    except Exception as e:
        logger.error(f"Error: {e}")
        conn.rollback()
    finally:
        if cur: cur.close()
        if conn: conn.close()

if __name__ == "__main__":
    process_reports()