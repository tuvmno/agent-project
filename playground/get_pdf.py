import os
import boto3
from botocore.client import Config
from dotenv import load_dotenv

# .env 로드 (상위 폴더에 있으므로 경로 지정 필요할 수 있음, 여기선 직접 입력 추천)
# 로컬 테스트니까 localhost로 설정
MINIO_ENDPOINT = "http://localhost:9000"
MINIO_ACCESS_KEY = "hongkyun" # .env에 설정한 값
MINIO_SECRET_KEY = "hongkyunadmin" # .env에 설정한 값
BUCKET_NAME = "reports"

def download_sample_pdf():
    print("🔌 MinIO 연결 시도...")
    s3 = boto3.client(
        's3',
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version='s3v4'),
        verify=False
    )
    
    # 1. 파일 목록 조회
    objects = s3.list_objects_v2(Bucket=BUCKET_NAME)
    
    if 'Contents' not in objects:
        print("❌ 버킷이 비어있습니다! 크롤러를 먼저 돌려주세요.")
        return
    print(objects)
    # 2. 첫 번째 PDF 다운로드
    # stock 폴더 안에 있는 것 중 하나를 고릅니다.
    target_file = None
    for obj in objects['Contents']:
        if obj['Key'].endswith(".pdf"):
            target_file = obj['Key']
            break
    
    if not target_file:
        print("❌ PDF 파일을 찾을 수 없습니다.")
        return

    print(f"📥 다운로드 대상: {target_file}")
    
    # 로컬에 저장
    local_filename = "test.pdf"
    s3.download_file(BUCKET_NAME, target_file, local_filename)
    
    print(f"✅ 다운로드 완료! 현재 폴더에 '{local_filename}'이 저장되었습니다.")

if __name__ == "__main__":
    download_sample_pdf()
