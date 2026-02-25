"""User reactions to AI observations."""

from fastapi import APIRouter, Query, HTTPException
from app.database import get_db
from app.models.schemas import ReactionCreate, ReactionResponse

router = APIRouter()


def _row_to_reaction(row) -> ReactionResponse:
    return ReactionResponse(
        id=row['id'],
        user_id=row['user_id'],
        drawing_id=row['drawing_id'],
        target_type=row['target_type'],
        target_id=row['target_id'],
        reaction_type=row['reaction_type'],
        annotation_text=row['annotation_text'],
        created_at=row['created_at'],
    )


@router.post("", response_model=ReactionResponse)
async def create_or_update_reaction(body: ReactionCreate):
    """
    Create or update a user reaction (INSERT OR REPLACE).
    One reaction per (user, drawing, target_type, target_id).
    """
    valid_reaction_types = {'agree', 'disagree', 'annotate'}
    if body.reaction_type not in valid_reaction_types:
        raise HTTPException(
            status_code=400,
            detail=f"reaction_type must be one of: {valid_reaction_types}"
        )

    valid_target_types = {'drawing_analysis', 'lens_annotation'}
    if body.target_type not in valid_target_types:
        raise HTTPException(
            status_code=400,
            detail=f"target_type must be one of: {valid_target_types}"
        )

    with get_db() as db:
        # Verify drawing exists
        drawing = db.execute(
            "SELECT id FROM drawings WHERE id = ?", (body.drawing_id,)
        ).fetchone()
        if not drawing:
            raise HTTPException(status_code=404, detail="Drawing not found")

        # Use COALESCE in UNIQUE constraint workaround: delete first, then insert
        db.execute("""
            DELETE FROM reactions
            WHERE user_id = ? AND drawing_id = ? AND target_type = ?
              AND COALESCE(target_id, '') = COALESCE(?, '')
        """, (body.user_id, body.drawing_id, body.target_type, body.target_id))

        cursor = db.execute("""
            INSERT INTO reactions (user_id, drawing_id, target_type, target_id, reaction_type, annotation_text)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            body.user_id, body.drawing_id, body.target_type,
            body.target_id, body.reaction_type, body.annotation_text
        ))

        row = db.execute(
            "SELECT * FROM reactions WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return _row_to_reaction(row)


@router.get("", response_model=list[ReactionResponse])
async def get_reactions(
    drawing_id: int = Query(...),
    user_id: int = Query(...)
):
    """Get all reactions for a drawing by a user."""
    with get_db() as db:
        rows = db.execute("""
            SELECT * FROM reactions
            WHERE drawing_id = ? AND user_id = ?
            ORDER BY created_at DESC
        """, (drawing_id, user_id)).fetchall()
        return [_row_to_reaction(r) for r in rows]
