"""Lens endpoints: list lenses, get drawings for a lens with annotations."""

from fastapi import APIRouter, Query, HTTPException, BackgroundTasks
from app.database import get_db
from app.models.schemas import (
    LensResponse, LensDrawingsResponse, DrawingWithAnnotation,
    AnnotationStatusResponse
)
from app.config import get_settings
from app.routers.drawings import _thumbnail_url

router = APIRouter()


def _row_to_lens(row) -> LensResponse:
    keys = row.keys()
    return LensResponse(
        id=row['id'],
        user_id=row['user_id'],
        name=row['name'],
        description=row['description'],
        sort_order=row['sort_order'],
        created_at=row['created_at'],
        drawing_count=row['drawing_count'] if 'drawing_count' in keys else 0,
        relevant_count=row['relevant_count'] if 'relevant_count' in keys else 0,
    )


@router.get("", response_model=list[LensResponse])
async def list_lenses(user_id: int = Query(...)):
    """List all discovered lenses for a user."""
    settings = get_settings()
    with get_db() as db:
        rows = db.execute("""
            SELECT l.*,
                   COUNT(ldl.id) as drawing_count,
                   SUM(CASE WHEN ldl.relevance_score >= ? THEN 1 ELSE 0 END) as relevant_count
            FROM lenses l
            LEFT JOIN lens_drawing_links ldl ON ldl.lens_id = l.id
            WHERE l.user_id = ?
            GROUP BY l.id
            ORDER BY l.sort_order ASC
        """, (settings.relevance_threshold, user_id)).fetchall()
        return [_row_to_lens(r) for r in rows]


@router.get("/{lens_id}/drawings", response_model=LensDrawingsResponse)
async def get_lens_drawings(
    lens_id: int,
    user_id: int = Query(...),
    background_tasks: BackgroundTasks = None
):
    """
    Get drawings for a lens, filtered by relevance threshold, ordered chronologically.
    Triggers annotation generation if not yet done.
    """
    settings = get_settings()

    with get_db() as db:
        # Get lens
        lens_row = db.execute(
            "SELECT * FROM lenses WHERE id = ? AND user_id = ?", (lens_id, user_id)
        ).fetchone()

        if not lens_row:
            raise HTTPException(status_code=404, detail="Lens not found")

        # Get drawing count for lens metadata
        drawing_count = db.execute(
            "SELECT COUNT(*) as cnt FROM lens_drawing_links WHERE lens_id = ?", (lens_id,)
        ).fetchone()['cnt']

        relevant_count = db.execute(
            "SELECT COUNT(*) as cnt FROM lens_drawing_links WHERE lens_id = ? AND relevance_score >= ?",
            (lens_id, settings.relevance_threshold)
        ).fetchone()['cnt']

        lens = LensResponse(
            id=lens_row['id'],
            user_id=lens_row['user_id'],
            name=lens_row['name'],
            description=lens_row['description'],
            sort_order=lens_row['sort_order'],
            created_at=lens_row['created_at'],
            drawing_count=drawing_count,
            relevant_count=relevant_count,
        )

        # Get drawings above threshold, ordered by drawn_date
        rows = db.execute("""
            SELECT d.*, ldl.relevance_score, ldl.annotation
            FROM lens_drawing_links ldl
            JOIN drawings d ON d.id = ldl.drawing_id
            WHERE ldl.lens_id = ?
              AND ldl.relevance_score >= ?
            ORDER BY d.drawn_date ASC, d.filename ASC
        """, (lens_id, settings.relevance_threshold)).fetchall()

        drawings = [
            DrawingWithAnnotation(
                id=r['id'],
                user_id=r['user_id'],
                filename=r['filename'],
                filepath=r['filepath'],
                drawn_date=r['drawn_date'],
                title=r['title'],
                file_ext=r['file_ext'],
                thumbnail_url=_thumbnail_url(r['id']) if r['thumbnail_path'] else None,
                width=r['width'],
                height=r['height'],
                analyzed_at=r['analyzed_at'],
                relevance_score=r['relevance_score'],
                annotation=r['annotation'],
            )
            for r in rows
        ]

        # Count how many have annotations
        annotation_done = sum(1 for d in drawings if d.annotation is not None)
        annotations_ready = annotation_done == len(drawings) and len(drawings) > 0

    # Trigger annotation generation if needed
    if not annotations_ready and background_tasks is not None:
        from app.services.archive_analyzer import get_archive_analyzer
        analyzer = get_archive_analyzer()
        background_tasks.add_task(
            analyzer.generate_lens_annotations,
            lens_id,
            user_id
        )

    return LensDrawingsResponse(
        lens=lens,
        drawings=drawings,
        annotations_ready=annotations_ready,
        annotation_total=len(drawings),
        annotation_done=annotation_done,
    )


@router.get("/{lens_id}/annotation_status", response_model=AnnotationStatusResponse)
async def get_annotation_status(lens_id: int, user_id: int = Query(...)):
    """Poll annotation generation progress for a lens."""
    settings = get_settings()

    with get_db() as db:
        total = db.execute("""
            SELECT COUNT(*) as cnt FROM lens_drawing_links ldl
            JOIN drawings d ON d.id = ldl.drawing_id
            WHERE ldl.lens_id = ? AND ldl.relevance_score >= ?
        """, (lens_id, settings.relevance_threshold)).fetchone()['cnt']

        ready = db.execute("""
            SELECT COUNT(*) as cnt FROM lens_drawing_links ldl
            JOIN drawings d ON d.id = ldl.drawing_id
            WHERE ldl.lens_id = ?
              AND ldl.relevance_score >= ?
              AND ldl.annotation IS NOT NULL
        """, (lens_id, settings.relevance_threshold)).fetchone()['cnt']

    if total == 0:
        status = "empty"
    elif ready == 0:
        status = "pending"
    elif ready < total:
        status = "generating"
    else:
        status = "complete"

    return AnnotationStatusResponse(
        lens_id=lens_id,
        total=total,
        ready=ready,
        status=status
    )
