"""Application settings — single source of truth for model name and paths."""

from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path

# Resolve .env relative to this file's location (backend/app/ → project root)
_PROJECT_ROOT = Path(__file__).parent.parent.parent  # drawing-mirror/
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    # AI
    anthropic_api_key: str = ""
    model_name: str = "claude-opus-4-6"      # change in .env to switch model

    # Analysis tuning
    batch_size: int = 8                       # images per Claude batch call
    max_tokens_per_image: int = 600
    max_tokens_lens_discovery: int = 8000
    max_tokens_annotation_batch: int = 2000   # for 10-drawing annotation batches
    relevance_threshold: float = 0.4          # min score to show in lens view

    # Paths
    dataset_root: str = "/Users/xieyantong/Projects/art-journal/dataset"
    doug_catalog: str = ""          # Excel catalog for Doug's dataset
    doug_images_dir: str = ""       # Directory containing Doug's image files
    db_path: str = "/Users/xieyantong/Projects/drawing-mirror/data/drawing_mirror.db"
    thumbnail_dir: str = "/Users/xieyantong/Projects/drawing-mirror/thumbnails"

    model_config = {
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
        "env_ignore_empty": True,       # system env vars set to "" don't override .env
        "protected_namespaces": ("settings_",),
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
