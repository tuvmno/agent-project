import base64
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from .config import AppConfig
import logging

logger = logging.getLogger("ImageHandler")

class ImageHandler:
    def __init__(self):
        # 이미지 해석은 무료 티어가 있는 Gemini 1.5 Flash 사용
        self.vision_model = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            temperature=0,
            google_api_key=AppConfig.GOOGLE_API_KEY
        )

    def encode_image(self, image_path):
        """이미지 파일을 base64로 인코딩"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def describe_images(self, image_paths: list) -> list:
        descriptions = []
        
        for path in image_paths:
            try:
                base64_image = self.encode_image(path)
                
                msg = HumanMessage(content=[
                    {"type": "text", "text": "이 금융 차트나 표가 무엇을 의미하는지, 주요 수치와 추세를 포함해서 상세하게 설명해줘."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ])
                
                res = self.vision_model.invoke([msg])
                descriptions.append(f"[차트/이미지 설명]\n{res.content}")
                logger.info(f"   -> 이미지 해석 완료 ({path})")
                
            except Exception as e:
                logger.error(f"이미지 해석 실패 ({path}): {e}")
        
        return descriptions