# download_model.py
from huggingface_hub import snapshot_download
import os

# 저장할 경로 (현재 위치 기준 models 폴더)
# 사용자의 경로: /mnt/c/Users/hongkyun/Desktop/DataspellProjects/agent-project/models/ko-sbert-nli
save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "ko-sbert-nli")

print(f"📥 모델 다운로드 시작: {save_dir}")

# snapshot_download는 LFS 없이도 원본 파일을 완벽하게 받아줍니다.
snapshot_download(
    repo_id="jhgan/ko-sbert-nli",
    local_dir=save_dir,
    local_dir_use_symlinks=False  # 윈도우/WSL 환경에서는 False가 안전함
)

print("✅ 다운로드 완료! 이제 실행해 보세요.")