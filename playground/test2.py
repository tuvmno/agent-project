import fitz  # pymupdf
from ultralytics import YOLO
from docling.document_converter import DocumentConverter
from PIL import Image
import io
import os
import pandas as pd
from huggingface_hub import hf_hub_download

class PerfectHybridParser:
    def __init__(self):
        # 1. YOLO 모델 로드 (Moured: 문서 레이아웃 감지용)
        print("⏳ YOLO 모델 로드 중 (DocLayNet)...")
        try:
            model_path = hf_hub_download(repo_id="moured/yolov8n-doclaynet", filename="best.pt")
            self.yolo_model = YOLO(model_path)
        except:
            self.yolo_model = YOLO("yolo8n.pt") # 로컬 파일 사용

        # 2. Docling 초기화 (표 추출용)
        print("⏳ Docling 초기화 중...")
        self.docling_converter = DocumentConverter()

    def get_overlap_ratio(self, box1, box2):
        """두 박스의 겹치는 비율 계산 (box1이 box2 안에 얼마나 들어가는지)"""
        # box: [x1, y1, x2, y2]
        x_left = max(box1[0], box2[0])
        y_top = max(box1[1], box2[1])
        x_right = min(box1[2], box2[2])
        y_bottom = min(box1[3], box2[3])

        if x_right < x_left or y_bottom < y_top:
            return 0.0

        intersection_area = (x_right - x_left) * (y_bottom - y_top)
        box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
        
        if box1_area == 0: return 0.0
        return intersection_area / box1_area

    def parse(self, pdf_path, output_file="final_perfect_data.md"):
        print(f"🚀 완전체 파싱 시작: {pdf_path}")
        
        # --- [Step 1] Docling으로 '표(Table)'만 먼저 싹 뽑기 ---
        print("   Step 1: Docling으로 표 추출 중...")
        docling_res = self.docling_converter.convert(pdf_path)
        
        # 페이지별 표 저장 (좌표 포함)
        tables_on_page = {}
        for table in docling_res.document.tables:
            p_no = table.prov[0].page_no # 1부터 시작
            bbox = table.prov[0].bbox # [l, t, r, b]
            
            # DataFrame 변환 -> Markdown(CSV 스타일) 변환
            df = table.export_to_dataframe()
            
            # [정제] '0, 1, 2' 인덱스 제거 및 깔끔하게 변환
            # 줄바꿈 문자 공백으로 치환
            df = df.replace(r'\n', ' ', regex=True)
            md_table = df.to_markdown(index=False) 
            
            if p_no not in tables_on_page: tables_on_page[p_no] = []
            tables_on_page[p_no].append({
                'bbox': [bbox.l, bbox.t, bbox.r, bbox.b],
                'content': md_table,
                'type': 'table'
            })

        # --- [Step 2] YOLO로 '본문(Text)'만 골라내기 ---
        print("   Step 2: YOLO로 본문 텍스트 추출 중...")
        pdf_doc = fitz.open(pdf_path)
        full_result = []

        for i, page in enumerate(pdf_doc):
            page_num = i + 1
            print(f"   Page {page_num} 처리 중...", end="\r")
            
            # A. YOLO 실행
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            results = self.yolo_model.predict(img, conf=0.25, verbose=False)

            # B. 요소 수집
            page_items = []
            
            # (1) Docling 표 먼저 담기
            docling_tables = tables_on_page.get(page_num, [])
            for tbl in docling_tables:
                page_items.append({
                    'bbox': tbl['bbox'], # PDF 좌표 (pt)
                    'content': f"\n[표 데이터]\n{tbl['content']}\n",
                    'y_sort': tbl['bbox'][1] # 정렬용 Y좌표
                })

            # (2) YOLO 텍스트 박스 처리
            for box in results[0].boxes:
                xyxy = box.xyxy[0].tolist() # [x1, y1, x2, y2] (이미지 픽셀)
                cls = int(box.cls[0])
                label = self.yolo_model.names[cls]

                # ★ 핵심 필터링: 우리가 원하는 것만 가져온다!
                # Chart, Picture, Footer, Header -> 여기서 자동 탈락
                if label not in ['Text', 'Title', 'Section-header', 'List-item']:
                    continue

                # 좌표 변환 (이미지 2배 확대 -> PDF 좌표)
                rect = [c / 2 for c in xyxy] # [x1, y1, x2, y2]

                # ★ 충돌 검사: 이 텍스트 박스가 Docling 표 안에 들어있는지 확인
                is_inside_table = False
                for tbl in docling_tables:
                    # 50% 이상 겹치면 표의 일부로 간주하고 무시 (Docling이 더 정확하므로)
                    if self.get_overlap_ratio(rect, tbl['bbox']) > 0.5:
                        is_inside_table = True
                        break
                
                if is_inside_table:
                    continue

                # 텍스트 추출 (PyMuPDF)
                # clip으로 해당 영역만 긁어옴
                text_content = page.get_text("text", clip=rect).strip()
                
                # 내용 정제 (너무 짧거나 이상한 문자 제거)
                if len(text_content) > 1:
                    # 제목 강조
                    if label in ['Title', 'Section-header']:
                        text_content = f"### {text_content}"
                    
                    page_items.append({
                        'bbox': rect,
                        'content': text_content,
                        'y_sort': rect[1]
                    })

            # C. 정렬 (위 -> 아래, 좌 -> 우)
            # 다단 편집 문서를 위해 Y좌표(행) 우선, 그 다음 X좌표(열) 정렬
            # Y좌표를 10pt 단위로 묶어서 같은 줄 처리
            page_items.sort(key=lambda x: (int(x['y_sort'] / 10), x['bbox'][0]))

            # D. 페이지 결과 합치기
            page_text = [f"\n## --- Page {page_num} ---\n"]
            for item in page_items:
                page_text.append(item['content'])
            
            full_result.append("\n".join(page_text))

        # --- [Step 3] 저장 ---
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(full_result))
        
        print(f"\n✅ 파싱 완료! 결과 파일: {output_file}")
        print("   - 차트/이미지 찌꺼기 제거됨")
        print("   - 표는 깔끔한 포맷으로 유지됨")
        print("   - 본문 텍스트는 헤더/풋터 없이 추출됨")

# 실행
parser = PerfectHybridParser()
parser.parse("test3.pdf")