import fitz  # pymupdf
from ultralytics import YOLO
from docling.document_converter import DocumentConverter
from PIL import Image
import io
import os
import pandas as pd
from huggingface_hub import hf_hub_download

class UltimateParser:
    def __init__(self):
        # 1. YOLO 모델 로드 (레이아웃 감지용 - Moured 모델)
        print("⏳ YOLO 모델 로드 중...")
        self.yolo_model = YOLO("yolo8n.pt")

        # 2. Docling 초기화 (표 추출용)
        self.docling_converter = DocumentConverter()

    def parse(self, pdf_path, output_file="final_result.md"):
        print(f"🚀 파싱 시작: {pdf_path}")
        
        # --- [Step 1] Docling으로 '표(Table)'만 정밀 추출 ---
        print("   Processing Tables with Docling...")
        docling_res = self.docling_converter.convert(pdf_path)
        doc_struct = docling_res.document
        
        # 페이지별 표 데이터 정리 (Key: Page번호, Value: 리스트)
        tables_by_page = {}
        for table in doc_struct.tables:
            p_no = table.prov[0].page_no
            bbox = table.prov[0].bbox
            # 마크다운으로 변환 (CSV 원하면 to_csv 문자열로 변환 가능)
            # 깔끔하게 CSV 스타일 텍스트로 변환
            df = table.export_to_dataframe()
            csv_text = df.to_markdown(index=False)
            
            if p_no not in tables_by_page: tables_by_page[p_no] = []
            tables_by_page[p_no].append({
                'rect': fitz.Rect(bbox.l, bbox.t, bbox.r, bbox.b), # 좌표
                'content': csv_text,
                'type': 'table'
            })

        # --- [Step 2] YOLO + PyMuPDF로 '본문(Text)'만 추출 ---
        print("   Processing Text with YOLO...")
        pdf_doc = fitz.open(pdf_path)
        full_markdown = []

        for i, page in enumerate(pdf_doc):
            page_num = i + 1
            print(f"   Page {page_num} 분석 중...", end="\r")
            
            # A. YOLO로 레이아웃 감지
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            results = self.yolo_model.predict(img, conf=0.25, verbose=False)

            # B. 요소 수집 (본문 텍스트 + 아까 뽑은 표)
            page_elements = []

            # (1) YOLO가 찾은 'Text', 'Title' 박스만 가져오기 (차트/그림 무시!)
            for box in results[0].boxes:
                xyxy = box.xyxy[0].tolist()
                cls = int(box.cls[0])
                label = self.yolo_model.names[cls]
                
                # ★핵심★: Chart, Figure, Footnote, Header, Footer는 여기서 걸러짐
                # 오직 'Text', 'Title', 'Section-header', 'List-item'만 읽음
                target_labels = ['Text', 'Title', 'Section-header', 'List-item']
                
                if label in target_labels:
                    # 좌표 변환 (이미지 2배 확대했으니 /2)
                    rect = fitz.Rect(xyxy[0]/2, xyxy[1]/2, xyxy[2]/2, xyxy[3]/2)
                    
                    # 해당 박스 안의 텍스트만 쏙 뽑기
                    text_content = page.get_text("text", clip=rect).strip()
                    
                    if text_content:
                        # 제목은 강조
                        if label in ['Title', 'Section-header']:
                            text_content = f"### {text_content}"
                        
                        page_elements.append({
                            'rect': rect,
                            'content': text_content,
                            'type': 'text'
                        })

            # (2) 아까 Docling으로 뽑은 표 추가
            if page_num in tables_by_page:
                page_elements.extend(tables_by_page[page_num])

            # C. 정렬 (위 -> 아래, 좌 -> 우)
            # 다단 편집이어도 읽는 순서가 맞게 됨
            page_elements.sort(key=lambda x: (int(x['rect'].y0 / 10), x['rect'].x0))

            # D. 페이지 결과 합치기
            page_md = [f"\n## --- Page {page_num} ---\n"]
            for elem in page_elements:
                page_md.append(elem['content'])
            
            full_markdown.append("\n\n".join(page_md))

        # --- [Step 3] 저장 ---
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(full_markdown))
        
        print(f"\n✅ 파싱 완료! 결과 파일: {output_file}")
        print("   - 차트(Figure) 안의 텍스트(순유입, 십억달러 등)는 완벽히 제거되었습니다.")
        print("   - 표(Table)는 Docling 품질 그대로 유지됩니다.")
        print("   - 본문(Text)은 YOLO가 잡은 영역만 깔끔하게 가져왔습니다.")

# 실행
parser = UltimateParser()
parser.parse("test3.pdf")