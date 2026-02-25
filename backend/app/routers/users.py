"""User management endpoints."""

from fastapi import APIRouter, HTTPException
from app.database import get_db
from app.models.schemas import UserResponse

router = APIRouter()


def _row_to_user(row, drawing_count: int = 0) -> UserResponse:
    return UserResponse(
        id=row['id'],
        username=row['username'],
        display_name=row['display_name'],
        dataset_path=row['dataset_path'],
        created_at=row['created_at'],
        drawing_count=drawing_count
    )


@router.get("", response_model=list[UserResponse])
async def list_users():
    """List all users with their drawing counts."""
    with get_db() as db:
        rows = db.execute("""
            SELECT u.*, COUNT(d.id) as drawing_count
            FROM users u
            LEFT JOIN drawings d ON d.user_id = u.id
            GROUP BY u.id
            ORDER BY u.username
        """).fetchall()
        return [_row_to_user(r, r['drawing_count']) for r in rows]


@router.get("/{username}", response_model=UserResponse)
async def get_user(username: str):
    """Get a specific user by username."""
    with get_db() as db:
        row = db.execute("""
            SELECT u.*, COUNT(d.id) as drawing_count
            FROM users u
            LEFT JOIN drawings d ON d.user_id = u.id
            WHERE u.username = ?
            GROUP BY u.id
        """, (username,)).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"User '{username}' not found")

        return _row_to_user(row, row['drawing_count'])
