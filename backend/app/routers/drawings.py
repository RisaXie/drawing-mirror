"""Drawing management endpoints: list, detail, serve image/thumbnail."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from app.database import get_db
from app.models.schemas import DrawingResponse, DrawingDetailResponse
from pathlib import Path

router = APIRouter()

BASE_URL = "http://localhost:8000"


def _thumbnail_url(drawing_id: int) -> str:
    return f"{BASE_URL}/api/drawings/{drawing_id}/thumbnail"


def _image_url(drawing_id: int) -> str:
    return f"{BASE_URL}/api/drawings/{drawing_id}/image"


def _row_to_drawing(row) -> DrawingResponse:
    return DrawingResponse(
        id=row['id'],
        user_id=row['user_id'],
        filename=row['filename'],
        filepath=row['filepath'],
        drawn_date=row['drawn_date'],
        title=row['title'],
        file_ext=row['file_ext'],
        thumbnail_url=_thumbnail_url(row['id']) if row['thumbnail_path'] else None,
        width=row['width'],
        height=row['height'],
        analyzed_at=row['analyzed_at'],
    )


@router.get("", response_model=list[DrawingResponse])
async def list_drawings(user_id: int = Query(...)):
    """List all drawings for a user, ordered chronologically."""
    with get_db() as db:
        rows = db.execute("""
            SELECT * FROM drawings
            WHERE user_id = ?
            ORDER BY drawn_date ASC, filename ASC
        """, (user_id,)).fetchall()
        return [_row_to_drawing(r) for r in rows]


@router.get("/{drawing_id}", response_model=DrawingDetailResponse)
async def get_drawing(drawing_id: int):
    """Get a single drawing with its full analysis."""
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM drawings WHERE id = ?", (drawing_id,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Drawing not found")

        return DrawingDetailResponse(
            id=row['id'],
            user_id=row['user_id'],
            filename=row['filename'],
            filepath=row['filepath'],
            drawn_date=row['drawn_date'],
            title=row['title'],
            file_ext=row['file_ext'],
            thumbnail_url=_thumbnail_url(row['id']) if row['thumbnail_path'] else None,
            width=row['width'],
            height=row['height'],
            analyzed_at=row['analyzed_at'],
            analysis_text=row['analysis_text'],
            analysis_json=row['analysis_json'],
        )


@router.get("/{drawing_id}/thumbnail")
async def get_thumbnail(drawing_id: int):
    """Serve the thumbnail image."""
    with get_db() as db:
        row = db.execute(
            "SELECT thumbnail_path FROM drawings WHERE id = ?", (drawing_id,)
        ).fetchone()

        if not row or not row['thumbnail_path']:
            raise HTTPException(status_code=404, detail="Thumbnail not found")

        path = Path(row['thumbnail_path'])
        if not path.exists():
            raise HTTPException(status_code=404, detail="Thumbnail file missing")

        return FileResponse(str(path), media_type="image/jpeg")


@router.get("/{drawing_id}/image")
async def get_image(drawing_id: int):
    """Serve the original image."""
    with get_db() as db:
        row = db.execute(
            "SELECT filepath, file_ext FROM drawings WHERE id = ?", (drawing_id,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Drawing not found")

        path = Path(row['filepath'])
        if not path.exists():
            raise HTTPException(status_code=404, detail="Image file missing")

        ext = (row['file_ext'] or 'jpeg').lower()
        media_type = "image/jpeg" if ext in ('jpg', 'jpeg') else f"image/{ext}"
        return FileResponse(str(path), media_type=media_type)
