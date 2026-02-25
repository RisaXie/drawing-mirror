"""Pydantic schemas for request/response models."""

from pydantic import BaseModel
from typing import Optional


# ─── Users ────────────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    id: int
    username: str
    display_name: str
    dataset_path: str
    created_at: str
    drawing_count: int = 0


# ─── Drawings ─────────────────────────────────────────────────────────────────

class DrawingResponse(BaseModel):
    id: int
    user_id: int
    filename: str
    filepath: str
    drawn_date: Optional[str]
    title: Optional[str]
    file_ext: Optional[str]
    thumbnail_url: Optional[str]
    width: Optional[int]
    height: Optional[int]
    analyzed_at: Optional[str]


class DrawingDetailResponse(DrawingResponse):
    analysis_text: Optional[str]
    analysis_json: Optional[str]


# ─── Archive Analysis ──────────────────────────────────────────────────────────

class ArchiveStatusResponse(BaseModel):
    analysis_id: Optional[int]
    status: str               # pending | running | complete | failed | not_started
    phase: Optional[str]      # batch_analysis | lens_discovery | annotating | done
    total_drawings: int = 0
    analyzed_count: int = 0
    has_lenses: bool = False
    error_message: Optional[str] = None


class AnalyzeTriggerResponse(BaseModel):
    analysis_id: int
    status: str


# ─── Lenses ───────────────────────────────────────────────────────────────────

class LensResponse(BaseModel):
    id: int
    user_id: int
    name: str
    description: str
    sort_order: int
    created_at: str
    drawing_count: int = 0       # total drawings with any relevance score
    relevant_count: int = 0      # drawings above relevance threshold


class DrawingWithAnnotation(DrawingResponse):
    relevance_score: float
    annotation: Optional[str]    # None if not yet generated


class LensDrawingsResponse(BaseModel):
    lens: LensResponse
    drawings: list[DrawingWithAnnotation]
    annotations_ready: bool      # True if all annotations generated
    annotation_total: int        # total drawings shown
    annotation_done: int         # annotations generated so far


class AnnotationStatusResponse(BaseModel):
    lens_id: int
    total: int
    ready: int
    status: str   # pending | generating | complete


# ─── Reactions ────────────────────────────────────────────────────────────────

class ReactionCreate(BaseModel):
    user_id: int
    drawing_id: int
    target_type: str            # 'drawing_analysis' | 'lens_annotation'
    target_id: Optional[str]   # lens_id (as string) if target_type='lens_annotation'
    reaction_type: str          # 'agree' | 'disagree' | 'annotate'
    annotation_text: Optional[str] = None


class ReactionResponse(BaseModel):
    id: int
    user_id: int
    drawing_id: int
    target_type: str
    target_id: Optional[str]
    reaction_type: str
    annotation_text: Optional[str]
    created_at: str
