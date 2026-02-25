"""CLIP embeddings API: generate, status, UMAP projection."""

from __future__ import annotations

import threading
from typing import Any

import numpy as np
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.database import get_db, get_db_connection

router = APIRouter()

# Track per-user embedding generation state in memory
# { user_id: "idle" | "running" | "complete" | "error" }
_status: dict[int, str] = {}
_lock = threading.Lock()


# ─── Background task ──────────────────────────────────────────────────────────

def _run_encode(user_id: int) -> None:
    """Run CLIP encoding in a background thread (not async — CPU-bound)."""
    with _lock:
        _status[user_id] = "running"

    try:
        from app.services.embeddings import get_embedding_service

        svc = get_embedding_service()
        db = get_db_connection()
        try:
            n = svc.encode_all_user_drawings(user_id, db)
            print(f"[Embeddings] User {user_id}: encoded {n} new drawings")
        finally:
            db.close()

        with _lock:
            _status[user_id] = "complete"

    except Exception as e:
        print(f"[Embeddings] Error for user {user_id}: {e}")
        with _lock:
            _status[user_id] = "error"


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_embeddings(
    user_id: int = Query(...),
    background_tasks: BackgroundTasks = None,
):
    """
    Trigger CLIP embedding generation for all un-embedded drawings of a user.
    Idempotent: if already complete, returns immediately.
    """
    with _lock:
        current = _status.get(user_id, "idle")

    if current == "running":
        return {"status": "running", "message": "Already in progress"}

    # Check if there's anything to do
    with get_db() as db:
        total = db.execute(
            "SELECT COUNT(*) FROM drawings WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        computed = db.execute(
            """
            SELECT COUNT(*) FROM embeddings e
            JOIN drawings d ON d.id = e.drawing_id
            WHERE d.user_id = ?
            """,
            (user_id,),
        ).fetchone()[0]

    if total > 0 and computed >= total:
        with _lock:
            _status[user_id] = "complete"
        return {"status": "complete", "message": "All embeddings already computed"}

    # Launch background thread (CPU-bound, can't use asyncio)
    with _lock:
        _status[user_id] = "running"

    t = threading.Thread(target=_run_encode, args=(user_id,), daemon=True)
    t.start()

    return {"status": "started", "total": total, "computed": computed}


@router.get("/status")
async def get_embedding_status(user_id: int = Query(...)):
    """Return current embedding computation status for a user."""
    with get_db() as db:
        total = db.execute(
            "SELECT COUNT(*) FROM drawings WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        computed = db.execute(
            """
            SELECT COUNT(*) FROM embeddings e
            JOIN drawings d ON d.id = e.drawing_id
            WHERE d.user_id = ?
            """,
            (user_id,),
        ).fetchone()[0]

    with _lock:
        status = _status.get(user_id, "idle")

    # Auto-promote to complete if all rows present
    if computed >= total > 0 and status != "error":
        status = "complete"
        with _lock:
            _status[user_id] = "complete"

    return {"status": status, "total": total, "computed": computed}


@router.get("/umap")
async def get_umap(user_id: int = Query(...)):
    """
    Compute and return 2-D UMAP projection for all embedded drawings of a user.

    Response:
        { "points": [ { drawing_id, x, y, filename, title, drawn_date, thumbnail_url }, ... ] }
    """
    with get_db() as db:
        rows = db.execute(
            """
            SELECT d.id, d.filename, d.title, d.drawn_date, d.thumbnail_path,
                   e.vector_blob
            FROM drawings d
            JOIN embeddings e ON e.drawing_id = d.id
            WHERE d.user_id = ?
            ORDER BY d.id
            """,
            (user_id,),
        ).fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No embeddings found for this user. Run /generate first."
        )

    from app.services.embeddings import EmbeddingService

    # Stack vectors
    vecs = np.stack(
        [EmbeddingService.blob_to_vector(r["vector_blob"]) for r in rows]
    )

    # UMAP projection
    from app.services.embeddings import get_embedding_service
    svc = get_embedding_service()
    coords = svc.compute_umap(vecs)  # (N, 2) normalized [0, 1]

    # Build response
    points: list[dict[str, Any]] = []
    base = "http://localhost:8000"  # thumbnail URL prefix
    for i, row in enumerate(rows):
        thumb_url = None
        if row["thumbnail_path"]:
            thumb_url = f"{base}/api/drawings/{row['id']}/thumbnail"

        points.append({
            "drawing_id": row["id"],
            "x": float(coords[i, 0]),
            "y": float(coords[i, 1]),
            "filename": row["filename"],
            "title": row["title"],
            "drawn_date": row["drawn_date"],
            "thumbnail_url": thumb_url,
        })

    return {"points": points}
