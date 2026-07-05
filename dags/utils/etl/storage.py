from .config import AppConfig
import boto3
from botocore.client import Config


class MinIOStorage:
    def __init__(self):
        # 스토리지 연결 설정
        self.client = boto3.client(
            's3',
            endpoint_url=AppConfig.MINIO_ENDPOINT,
            aws_access_key_id=AppConfig.MINIO_ACCESS_KEY,
            aws_secret_access_key=AppConfig.MINIO_SECRET_KEY,
            config=Config(signature_version='s3v4'), # aws 보안 권장 사항에 따라 서명생성방식을 s3v4로 고정 
            verify=False # SSL 인증서 검증 비활성화(개발 환경끝나면 추가)
        )
    
    def get_file_content(self, file_path: str) -> bytes:
        """MinIO에서 파일 바이너리 가져오기"""
        try:
            response = self.client.get_object(Bucket=AppConfig.BUCKET_NAME, Key=file_path)
            return response['Body'].read()
        except Exception as e:
            raise RuntimeError(f"[MinIOStorage] [get_file_content] Error: {e}") from e
        