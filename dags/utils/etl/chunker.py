import re
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from langchain_core.documents import Document
import hashlib

class AdvancedFinancialChunker:
    def __init__(self, chunk_size=1000, chunk_overlap=200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # separators 순서: 줄바꿈 2번(문단) -> 줄바꿈 1번(표 행) -> 공백
        # 표(Table)는 보통 줄바꿈(\n)으로 되어 있어서, \n\n을 최우선으로 자르면 표가 안 깨짐
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

    def _clean_markdown(self, text: str) -> str:
        """
        청킹 전에 불필요한 노이즈(페이지 번호, 중복 문구)를 제거하는 전처리
        """
        lines = text.split('\n')
        cleaned_lines = []
        
        # [제거 패턴]
        # 1. "## --- Page 10 ---" 같은 페이지 구분선 제거 (문맥 연결을 위해)
        page_pattern = re.compile(r"^##\s*---+\s*Page\s*\d+\s*---+$", re.IGNORECASE)
        
        # 2. 반복되는 꼬리말/머리말 패턴 (필요시 추가)
        
        for line in lines:
            if page_pattern.match(line.strip()):
                continue # 페이지 헤더 삭제 -> 앞뒤 문장이 자연스럽게 이어짐
            
            cleaned_lines.append(line)
            
        return "\n".join(cleaned_lines)

    def _clean_text_table(self, table_str: str) -> list[Document]:
        # 특수 태그(@@@)를 기준으로 문서 분리
        # 정규식 설명: (테이블 시작 ~ 테이블 끝) 패턴을 캡처
        # re.DOTALL: 줄바꿈도 포함해서 매칭
        pattern = r"(@@@TABLE_START@@@.*?@@@TABLE_END@@@)"
        parts = re.split(pattern, table_str, flags=re.DOTALL)
        
        final_chunks = []
        
        for part in parts:
            if not part.strip(): 
                continue
            
            # 표 블록인 경우
            if "@@@TABLE_START@@@" in part:
                # 태그 제거하고 순수 내용만 추출
                clean_content = part.replace("@@@TABLE_START@@@", "").replace("@@@TABLE_END@@@", "").strip()
                
                # 표 제목과 내용이 포함된 하나의 완벽한 청크 생성
                doc = Document(
                    page_content=clean_content,
                    metadata={"type": "table", "source": "processed_report"}
                )
                final_chunks.append(doc)
                
            # 3. 일반 텍스트인 경우 (기존대로 자름)
            else:
                text_docs = self.text_splitter.create_documents([part])
                for doc in text_docs:
                    doc.metadata = {"type": "text"}
                    final_chunks.append(doc)
                    
        return final_chunks


    def _remove_duplicates(self, docs: list[Document]) -> list[Document]:
        """
        내용이 완벽히 똑같은 청크(중복 헤더 등)를 제거
        """
        unique_docs = []
        seen_hashes = set()

        for doc in docs:
            # 내용을 해시화해서 중복 검사
            content_hash = hashlib.md5(doc.page_content.encode('utf-8')).hexdigest()
            
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                unique_docs.append(doc)
            else:
                # 디버깅: 중복 제거된 내용 확인
                # print(f"중복 청크 제거됨: {doc.page_content[:30]}...")
                pass
                
        return unique_docs

    def split_text(self, markdown_text: str) -> list[Document]:
        # 1. 노이즈 제거 (Page 헤더 등)
        cleaned_text = self._clean_markdown(markdown_text)
        print(cleaned_text)
        # 2. 헤더 기준 1차 분할 (의미 단위)
        final_splits = self._clean_text_table(cleaned_text)
        
        # 3. 중복 제거 (똑같은 내용의 청크 삭제)
        deduplicated_splits = self._remove_duplicates(final_splits)
        
        return deduplicated_splits
