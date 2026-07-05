from .config import AppConfig
import re
import fitz 
import base64
import io
import os
import logging
import pandas as pd
from PIL import Image
from ultralytics import YOLO
from ollama import Client
from difflib import SequenceMatcher
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions

logger = logging.getLogger("CustomParser")

class CustomParser:
    def __init__(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.join(current_dir, "../../../models/","yolov8n-doclaynet.pt")
        
        # layout 확인해서 텍스트만 추출하기 위해 사용
        try:
            self.yolo_model = YOLO(model_path)
        except Exception as e:
            logger.error(f"YOLO 로드 실패: {e}")
            raise e
        
        # docling으로 PDF에서 표만 추출 하기 위해 사용
        self.pipeline_options = PdfPipelineOptions()
        # self.pipeline_options.do_ocr = True  # ocr엔진 활성화 여부
        self.pipeline_options.do_table_structure = True # 문서 내 테이블 구조를 탐지하여 추출
        self.pipeline_options.table_structure_options.do_cell_matching = True # 테이블 셀 매칭 강화
        self.pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE # 정확도 높게
        # self.pipeline_options.generate_picture_images = True # 문서 내 이미지를 PIL객체로 추출
        # self.pipeline_options.images_scale = 2.5 # 추출된 이미지의 해상도 배율 설정
        self.pipeline_options.accelerator_options = AcceleratorOptions(device='cuda') # 하드웨어 가속기 사용과 관련된 설정을 지정

        # self.pipeline_options.do_picture_classification = True # 추출된 이미지를 분류하는 기능 활성화 여부
        # self.pipeline_options.do_picture_description = True # 이미지에 대한 자연어 캡션 생성기능 활성화 여부
        # self.pipeline_options.enable_remote_services = True # ocr엔진이나 llm 등 원격 서비스 설정 
        # self.pipeline_options.ocr_options # 사용할 특정 ocr엔진(tesseract,easyocr) 세부 옵션 설정

        self.docling_converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=self.pipeline_options)
            }
        )
        
        # 필요없는 텍스트 패턴
        self.garbage_patterns = [
            r"(자료|Source|참고|주)\s*[:;]", 
            r"^\(.*\)$", 
            r"Compliance Notice",
            r"무단\s*전재",
            r"본\s*자료는",
            r"투자자",
            r"투자의견",
            r"목표주가",
            r".*@.*\.com",
            r"www\..*",
            r'^.*이 자료에 게재된.*$\n?',
            r"^\d+\s*$",        # 페이지 번호
            r"^그림\s*\d+",     # 그림 1. ...
            r"^도표\s*\d+",     # 도표 2. ...
            r"^Figure\s*\d+",   # Figure 3. ...
            r"^Chart\s*\d+",    # Chart 4. ...
            r"^Appendix"        # 부록 헤더
        ]


    def is_garbage(self, text):
        """텍스트가 쓰레기인지 판별"""
        text = text.strip()
        if len(text) < 2: return True
        for pat in self.garbage_patterns:
            if re.search(pat, text, re.IGNORECASE):
                return True
        return False

    def get_similarity(self, a, b):
        # 두 문장의 유사도 비율을 계산 (0.0 ~ 1.0)
        return SequenceMatcher(None, a, b).ratio()

    def parse(self, pdf_path, output_file="parsed_result.md"):
        try:
            print(f"파싱 시작: {pdf_path}")
            
            # Docling으로 표 추출
            docling_res = self.docling_converter.convert(pdf_path)
            
            # YOLO + PyMuPDF로 본문 추출
            pdf_doc = fitz.open(pdf_path)
            # docling기준 각 페이지 높이 값
            page_heights = {i+1: page.rect.height for i, page in enumerate(pdf_doc)}
            
            # 전체 표 데이터 추출 
            tables_by_page = {}
            for table in docling_res.document.tables:
                p_no = table.prov[0].page_no
                
                # docling은 왼쪽 아래가 (0,0), YOLO는 위가 (0,0)
                # 통일작업
                # 해당 페이지 높이값
                page_h = page_heights.get(p_no, 842)
                
                d_left = table.prov[0].bbox.l
                d_right = table.prov[0].bbox.r
                d_top = table.prov[0].bbox.t    # PDF상 위쪽 (큰 숫자)
                d_bottom = table.prov[0].bbox.b # PDF상 아래쪽 (작은 숫자)
                
                # 뒤집기 (Top-Left 기준)
                new_top = page_h - d_top      # 큰 숫자를 빼야 위쪽(작은 Y)이 됨
                new_bottom = page_h - d_bottom # 작은 숫자를 빼야 아래쪽(큰 Y)이 됨
                
                # [좌, 상, 우, 하]
                bbox = [d_left, new_top, d_right, new_bottom]
                                
                # 현재 표 추출
                df = table.export_to_dataframe(docling_res)
                print(df)
                # 헤더 정리 (숫자형 헤더 제거)
                if all(isinstance(c, int) for c in df.columns):
                    new_header = df.iloc[0]
                    df = df[1:]
                    df.columns = new_header

                # 현재 표 마크다운 변환
                df_clean = df.fillna('').astype(str).replace(r'\n', ' ', regex=True)
                md_table = df_clean.to_markdown(index=False)

                # 각 페이지 리스트
                if p_no not in tables_by_page: tables_by_page[p_no] = []

                # 각 페이지의 표 저장
                tables_by_page[p_no].append({
                    'bbox': bbox,
                    'content': md_table,  # DataFrame 상태로 저장 (나중에 병합 위해)
                    'used': False # 제목과 매칭되었는지 여부
                })


            # 전체 페이지 데이터
            all_pages_content = []
            
            # 각 페이지 별 처리
            for i, page in enumerate(pdf_doc):
                page_num = i + 1                
                # YOLO 실행
                # 2배 확대해서 선명하게 확인 
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                results = self.yolo_model.predict(img, conf=0.25, verbose=False)

                # YOLO 박스 수집
                yolo_items = []
                for box in results[0].boxes:
                    xyxy = box.xyxy[0].tolist()
                    label = self.yolo_model.names[int(box.cls[0])]

                    # 텍스트 데이터 제외 건너뛰기
                    if label not in ['Text', 'Title', 'Section-header', 'List-item']:
                        continue
                    
                    # PDF 좌표 변환(2배 확대한거 원래비율로 처리)
                    rect = [c / 2 for c in xyxy]
                    # 텍스트 추출
                    text = page.get_text("text", clip=rect).strip()
                    if len(text) > 1:
                        # 텍스트 박스 좌표, 텍스트 내용, 라벨, 표와 매치여부
                        yolo_items.append({'bbox': rect, 'content': text, 'label': label, 'matched': False})
                        
                # 해당 페이지의 표 데이터 가져오기
                page_tables = tables_by_page.get(page_num, [])

                # 표 리스트 순회
                for table_item in page_tables:
                    table_bbox_top = table_item['bbox'][1]

                    # 표의 바로 위에 있는 YOLO 텍스트 찾기 (거리 50pt 이내)
                    best_title = None
                    min_dist = 50 
                    best_idx = -1

                    # 해당 페이지 텍스트 박스 순회
                    for idx, txt in enumerate(yolo_items):
                        # 이미 다른 표랑 짝지어진 건 패스
                        if txt['matched']: 
                            continue
    
                        # 텍스트 하단 가져오기
                        txt_bottom = txt['bbox'][3]
                        
                        # 표 상단 - 텍스트 하단
                        dist = table_bbox_top - txt_bottom 
                        
                        # 텍스트가 표 위에 있고(양수), 거리가 가까우며, 내용이 제목스러우면(표, 그림 등)
                        if 0 < dist < min_dist:
                            # 정규식으로 '표 1', 'Figure' 같은게 있는지 확인
                            if re.match(r"^(표|그림|도표|Figure|Table)\s*\d+", txt['content']):
                                min_dist = dist
                                best_title = txt
                                best_idx = idx

                    # 표 데이터 
                    final_table_block = ""
                    # 표 제목을 찾은 경우
                    if best_title:
                        yolo_items[best_idx]['matched'] = True
                        # 테이블 전체를 청킹할 수 있도록 특수 태크로 범위 표시
                        final_table_block = f"\n@@@TABLE_START@@@\n{best_title['content']}\n\n{table_item['content']}\n@@@TABLE_END@@@\n"
                    else:
                        # 제목 못 찾았으면 그냥 표만
                        final_table_block = f"\n@@@TABLE_START@@@\n\n{table_item['content']}\n@@@TABLE_END@@@\n"

                    # 표는 별도 리스트에 넣지 않고, 나중에 위치 정렬할 때 좌표 기준으로 넣음
                    table_item['final_content'] = final_table_block

                # 최종 정렬 (사용 안 된 텍스트 + 합체된 표)
                merged_items = []
                
                # 매칭 안 된 일반 텍스트 추가
                for item in yolo_items:
                    if not item['matched']:
                        # 텍스트 추출
                        text = item['content']

                        # 필터링 및 중복 방지
                        if not text or self.is_garbage(text): 
                            continue
                        
                        merged_items.append({'y': item['bbox'][1], 'content': text})

                # 표(제목 포함됨) 추가
                for merged_table in page_tables:
                    merged_items.append({'y': merged_table['bbox'][1], 'content': merged_table['final_content']})


                # y 좌표로 정렬
                merged_items.sort(key=lambda x: x['y'])

                # 연속된 중복 텍스트 제거
                final_items = []
                prev_content = ""
                for it in merged_items:
                    current_content = it['content']
            
                    # 이전 문장과 현재 문장의 유사도가 0.8(80%) 이상이면 제외
                    if prev_content and self.get_similarity(prev_content, current_content) >= 0.8:
                        continue
                
                    final_items.append(current_content)
                    prev_content = current_content
                        
                    
                if final_items:
                    page_str = f"\n## --- Page {page_num} ---\n"
                    page_str += "\n\n".join(final_items)
                    all_pages_content.append(page_str)
                    
            result_text = "\n".join(all_pages_content)
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(result_text)

            return result_text
        except Exception as e:
            logger.error(e)
            return ""   
