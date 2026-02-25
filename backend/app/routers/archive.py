"""Archive analysis endpoints: trigger pipeline, check status."""

from fastapi import APIRouter, BackgroundTasks, Query, HTTPException
from app.database import get_db
from app.models.schemas import ArchiveStatusResponse, AnalyzeTriggerResponse

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeTriggerResponse)
async def trigger_analysis(
    user_id: int = Query(...),
    background_tasks: BackgroundTasks = None
):
    """
    Trigger the archive analysis pipeline for a user.
    Returns immediately; analysis runs in background.
    """
    from app.services.archive_analyzer import get_archive_analyzer

    with get_db() as db:
        # Check if already running
        running = db.execute("""
            SELECT id FROM archive_analyses
            WHERE user_id = ? AND status = 'running'
        """, (user_id,)).fetchone()

        if running:
            raise HTTPException(
                status_code=409,
                detail=f"Analysis already running (id={running['id']})"
            )

        # Create new analysis record
        from app.config import get_settings
        settings = get_settings()
        cursor = db.execute("""
            INSERT INTO archive_analyses (user_id, status, model_used)
            VALUES (?, 'pending', ?)
        """, (user_id, settings.model_name))
        analysis_id = cursor.lastrowid

    # Launch background task
    analyzer = get_archive_analyzer()
    background_tasks.add_task(analyzer.run_full_pipeline, user_id, analysis_id)

    return AnalyzeTriggerResponse(analysis_id=analysis_id, status="started")


@router.get("/status", response_model=ArchiveStatusResponse)
async def get_status(user_id: int = Query(...)):
    """Get the current archive analysis status for a user."""
    with get_db() as db:
        # Get most recent analysis
        analysis = db.execute("""
            SELECT * FROM archive_analyses
            WHERE user_id = ?
            ORDER BY started_at DESC
            LIMIT 1
        """, (user_id,)).fetchone()

        # Check if lenses exist
        lens_count = db.execute(
            "SELECT COUNT(*) as cnt FROM lenses WHERE user_id = ?", (user_id,)
        ).fetchone()['cnt']

        if not analysis:
            return ArchiveStatusResponse(
                analysis_id=None,
                status="not_started",
                phase=None,
                has_lenses=lens_count > 0
            )

        return ArchiveStatusResponse(
            analysis_id=analysis['id'],
            status=analysis['status'],
            phase=analysis['phase'],
            total_drawings=analysis['total_drawings'],
            analyzed_count=analysis['analyzed_count'],
            has_lenses=lens_count > 0,
            error_message=analysis['error_message']
        )
