import os
import logging
import shutil
from .storage import MinIOStorage
from .parser import CustomParser
from .image_handler import ImageHandler
from .vector_store import PostgresVectorStore
from .chunker import AdvancedFinancialChunker

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ETL_Pipeline")

class ETLPipeline:
    def __init__(self):
        self.storage = MinIOStorage()
        self.db = PostgresVectorStore()
        self.parser = CustomParser()
        

    def run(self):
        logger.info("ETL 파이프라인 시작")

        # 처리할 리포트 조회 (DB)
        targets = self.db.get_pending_reports(limit=1)
        if not targets:
            logger.info("처리할 데이터가 없습니다.")
            return

        for r_id, minio_path, title in targets:
            try:
                # minio 스토리지에서 리포트 다운로드
                temp_path = f"/tmp/{minio_path.split('/')[-1]}"
                with open(temp_path, "wb") as f:
                    f.write(self.storage.get_file_content(minio_path))

                # PDF 클렌징 - 텍스트, 표 추출 
                result = self.parser.parse(temp_path)
                
                # 청킹
                chunker = AdvancedFinancialChunker()
                chunks = chunker.split_text(result)
                 
                # 결과 저장
                for chunk in chunks:
                    self.db.save_chunk(r_id, chunk, "text")

                # 처리완료된 리포트 상태값 업데이트
                self.db.mark_as_processed(r_id)
                logger.info(f"Success: {title}")

            except Exception as e:
                logger.error(f"Failed ({title}): {e}")
            
            finally:
                # 정리 (임시 PDF 파일 삭제)
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                

if __name__ == "__main__":
    pipeline = ETLPipeline()
    pipeline.run()