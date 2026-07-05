import re
from docling.document_converter import DocumentConverter

class HybridReportParser:
    def __init__(self):
        # 1. 텍스트 청소용 패턴 (차트 찌꺼기, 날짜, 불필요한 문구 제거)
        self.garbage_patterns = [
            r"^자료\s*[:;]",           # 자료 : ...
            r"^Source\s*[:;]",         # Source : ...
            r"^주\s*[:;]",             # 주 : ...
            r"^참고\s*[:;]",           # 참고 : ...
            r"^\(.*\)$",               # (단위 : ...), (%), (bp)
            r"^'?\d{2,4}[./-]\d{1,2}", # '23/11 날짜 패턴
            r"^\d+(\.\d+)?$",          # 숫자만 있는 줄
            r"Compliance Notice",      # 유의사항
            r"무단 전재",
            r".*@.*\.com",             # 이메일
            r"그림\s*\d+",             # 그림 캡션
            r"도표\s*\d+"              # 도표 캡션
        ]

    def is_clean_text(self, text):
        """텍스트가 유의미한지 검사"""
        text = text.strip()
        if len(text) < 2: return False # 너무 짧음

        # 쓰레기 패턴 검사
        for pat in self.garbage_patterns:
            if re.search(pat, text, re.IGNORECASE):
                return False
        
        # 숫자/특수문자 비율 검사 (차트 데이터 제거)
        num_char = len(re.findall(r'[\d.,\-%]', text))
        if len(text) > 0 and (num_char / len(text)) > 0.6:
            return False

        return True

    def parse(self, pdf_path, output_file="final_hybrid_data2.md"):
        print(f"🚀 하이브리드 파싱 시작: {pdf_path}")
        
        converter = DocumentConverter()
        result = converter.convert(pdf_path)
        doc = result.document
        
        full_content = []

        # 페이지별 처리
        for page_no, page in doc.pages.items():
            page_items = []
            
            # 1. 텍스트 수집
            for text_item in doc.texts:
                if text_item.prov[0].page_no == page_no:
                    # 헤더/풋터 영역(상하 10%) 좌표 필터링
                    bbox = text_item.prov[0].bbox
                    page_h = page.size.height
                    rel_y = (bbox.t + bbox.b) / 2 / page_h
                    
                    if 0.1 < rel_y < 0.9: # 중간 영역만 인정
                        page_items.append({
                            'type': 'text',
                            'y': bbox.t, # 정렬용 좌표
                            'content': text_item.text
                        })

            # 2. 표(Table) 수집 (Docling의 강점!)
            for table_item in doc.tables:
                if table_item.prov[0].page_no == page_no:
                    # 표를 마크다운으로 변환
                    md_table = table_item.export_to_markdown()
                    page_items.append({
                        'type': 'table',
                        'y': table_item.prov[0].bbox.t,
                        'content': md_table
                    })

            # 3. 위치(Y좌표) 순서대로 정렬 (읽는 순서 맞추기)
            page_items.sort(key=lambda x: x['y'])

            # 4. 최종 조립
            clean_page_text = []
            clean_page_text.append(f"\n## --- Page {page_no} ---\n")
            
            for item in page_items:
                if item['type'] == 'table':
                    # 표는 무조건 포함 (필터링 X)
                    clean_page_text.append(f"\n{item['content']}\n")
                else:
                    # 텍스트는 청소기 통과
                    if self.is_clean_text(item['content']):
                        clean_page_text.append(item['content'])
            
            full_content.append("\n".join(clean_page_text))

        # 저장
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(full_content))
            
        print(f"✅ 파싱 완료! {output_file}")
        return output_file

# 실행
parser = HybridReportParser()
parser.parse("test2.pdf")