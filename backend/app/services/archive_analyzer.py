"""
Archive Analyzer — orchestrates the three-phase pipeline:
  Phase 1: Batch image analysis (Claude sees images in groups of 8)
  Phase 2: Lens discovery (Claude sees all text summaries, no images)
  Phase 3: Lens annotation (on-demand, text-only, 10 drawings per call)
"""

import asyncio
import io
import json
import re
import sqlite3
from pathlib import Path
from typing import Optional

from PIL import Image

from app.config import get_settings
from app.database import get_db_connection
from app.services.ai.vision import get_vision_service
from app.services.ai.prompts.registry import get_prompt_registry

# Claude's base64 image limit is 5MB; base64 overhead is ~33%, so keep originals under ~3.7MB
_MAX_IMAGE_BYTES = 3_700_000


def _prepare_image_bytes(raw_bytes: bytes, media_type: str) -> tuple[bytes, str]:
    """
    Resize/recompress image if it would exceed Claude's 5MB base64 limit.
    Returns (bytes, media_type) ready for the API.
    """
    if len(raw_bytes) <= _MAX_IMAGE_BYTES:
        return raw_bytes, media_type

    # Resize: fit within 2048×2048, re-save as JPEG at quality 85
    img = Image.open(io.BytesIO(raw_bytes))
    img = img.convert("RGB")  # ensure no alpha
    img.thumbnail((2048, 2048), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    result = buf.getvalue()
    print(f"[Phase1] Resized image from {len(raw_bytes)//1024}KB to {len(result)//1024}KB")
    return result, "image/jpeg"


class ArchiveAnalyzer:

    def __init__(self):
        self.settings = get_settings()
        self.vision = get_vision_service()
        self.prompts = get_prompt_registry()

    # ─── Public entry points ──────────────────────────────────────────────────

    async def run_full_pipeline(self, user_id: int, analysis_id: int) -> None:
        """
        Main pipeline: Phase 1 (image batches) → Phase 2 (lens discovery).
        Called as a FastAPI BackgroundTask.
        """
        db = get_db_connection()
        try:
            # Count total drawings
            total = db.execute(
                "SELECT COUNT(*) as cnt FROM drawings WHERE user_id = ?", (user_id,)
            ).fetchone()['cnt']

            db.execute("""
                UPDATE archive_analyses
                SET status = 'running', phase = 'batch_analysis', total_drawings = ?
                WHERE id = ?
            """, (total, analysis_id))
            db.commit()

            # Phase 1
            await self._phase1_batch_analysis(db, user_id, analysis_id)

            # Phase 2
            db.execute("""
                UPDATE archive_analyses SET phase = 'lens_discovery' WHERE id = ?
            """, (analysis_id,))
            db.commit()
            await self._phase2_lens_discovery(db, user_id, analysis_id)

            db.execute("""
                UPDATE archive_analyses
                SET status = 'complete', phase = 'done', completed_at = datetime('now')
                WHERE id = ?
            """, (analysis_id,))
            db.commit()

        except Exception as e:
            print(f"[ArchiveAnalyzer] Pipeline failed: {e}")
            db.execute("""
                UPDATE archive_analyses
                SET status = 'failed', error_message = ?
                WHERE id = ?
            """, (str(e)[:500], analysis_id))
            db.commit()
        finally:
            db.close()

    async def generate_lens_annotations(self, lens_id: int, user_id: int) -> None:
        """
        Phase 3 (on-demand): generate per-drawing annotations for a lens.
        Only processes drawings without annotations yet (idempotent).
        """
        db = get_db_connection()
        try:
            # Get lens info
            lens = db.execute(
                "SELECT * FROM lenses WHERE id = ? AND user_id = ?", (lens_id, user_id)
            ).fetchone()
            if not lens:
                return

            # Get drawings that need annotation (above threshold, no annotation yet)
            rows = db.execute("""
                SELECT d.id, d.filename, d.drawn_date, d.analysis_text
                FROM lens_drawing_links ldl
                JOIN drawings d ON d.id = ldl.drawing_id
                WHERE ldl.lens_id = ?
                  AND ldl.relevance_score >= ?
                  AND ldl.annotation IS NULL
                  AND d.analysis_text IS NOT NULL
                ORDER BY d.drawn_date ASC, d.filename ASC
            """, (lens_id, self.settings.relevance_threshold)).fetchall()

            if not rows:
                return

            # Batch annotate (10 drawings per call)
            annotation_batch_size = 10
            for i in range(0, len(rows), annotation_batch_size):
                batch = rows[i:i + annotation_batch_size]
                await self._annotate_batch(db, lens, batch)
                db.commit()
                if i + annotation_batch_size < len(rows):
                    await asyncio.sleep(0.5)

        except Exception as e:
            print(f"[ArchiveAnalyzer] Annotation failed for lens {lens_id}: {e}")
        finally:
            db.close()

    # ─── Phase 1: Batch image analysis ───────────────────────────────────────

    async def _phase1_batch_analysis(
        self, db: sqlite3.Connection, user_id: int, analysis_id: int
    ) -> None:
        """Send drawings to Claude in image batches, store per-drawing analysis."""

        # Only process drawings not yet analyzed
        drawings = db.execute("""
            SELECT id, filename, filepath, file_ext
            FROM drawings
            WHERE user_id = ? AND analyzed_at IS NULL
            ORDER BY drawn_date ASC, filename ASC
        """, (user_id,)).fetchall()

        if not drawings:
            return

        batch_size = self.settings.batch_size
        prompt = self.prompts.render("drawing_batch_analysis")

        for batch_start in range(0, len(drawings), batch_size):
            batch = drawings[batch_start:batch_start + batch_size]

            # Load image bytes
            image_tuples = []
            for d in batch:
                try:
                    with open(d['filepath'], 'rb') as f:
                        image_bytes = f.read()
                    ext = (d['file_ext'] or 'jpeg').lower()
                    media_type = "image/jpeg" if ext in ('jpg', 'jpeg') else f"image/{ext}"
                    # Resize if too large for Claude's 5MB base64 limit
                    image_bytes, media_type = _prepare_image_bytes(image_bytes, media_type)
                    image_tuples.append((image_bytes, media_type, d['filename']))
                except Exception as e:
                    print(f"[Phase1] Could not load {d['filepath']}: {e}")

            if not image_tuples:
                continue

            # Call Claude
            max_tokens = len(image_tuples) * self.settings.max_tokens_per_image + 500
            try:
                raw_response = await self.vision.analyze_batch(
                    images=image_tuples,
                    prompt=prompt,
                    max_tokens=max_tokens
                )
            except Exception as e:
                print(f"[Phase1] Claude call failed for batch {batch_start}: {e}")
                continue

            # Parse JSON response
            analyses = self._parse_json_list(raw_response)
            filename_to_analysis = {item.get('filename', ''): item for item in analyses}

            # Store per drawing
            for d in batch:
                item = filename_to_analysis.get(d['filename'])
                if item:
                    analysis_text = item.get('description', '')
                    db.execute("""
                        UPDATE drawings
                        SET analysis_text = ?, analysis_json = ?, analyzed_at = datetime('now')
                        WHERE id = ?
                    """, (analysis_text, json.dumps(item), d['id']))
                else:
                    # Mark as attempted even if no result
                    db.execute("""
                        UPDATE drawings SET analyzed_at = datetime('now') WHERE id = ?
                    """, (d['id'],))

            # Update progress
            analyzed_so_far = min(batch_start + batch_size, len(drawings))
            db.execute("""
                UPDATE archive_analyses SET analyzed_count = ? WHERE id = ?
            """, (analyzed_so_far, analysis_id))
            db.commit()

            print(f"[Phase1] Batch {batch_start//batch_size + 1}: {len(image_tuples)} images analyzed")

            # Courtesy pause between batches
            if batch_start + batch_size < len(drawings):
                await asyncio.sleep(2.0)

    # ─── Phase 2: Lens discovery ──────────────────────────────────────────────

    async def _phase2_lens_discovery(
        self, db: sqlite3.Connection, user_id: int, analysis_id: int
    ) -> None:
        """Collect all text summaries, send to Claude, discover and store lenses."""

        rows = db.execute("""
            SELECT id, filename, drawn_date, analysis_text
            FROM drawings
            WHERE user_id = ? AND analysis_text IS NOT NULL
            ORDER BY drawn_date ASC, filename ASC
        """, (user_id,)).fetchall()

        if not rows:
            print("[Phase2] No analyzed drawings found, skipping lens discovery")
            return

        # Build summaries block
        summaries_block = ""
        for r in rows:
            date_str = r['drawn_date'] or 'unknown date'
            summaries_block += f"\n[{date_str}] {r['filename']}: {r['analysis_text']}\n"

        # Determine year range
        dates = [r['drawn_date'] for r in rows if r['drawn_date']]
        if dates:
            year_range = f"{dates[0][:4]}–{dates[-1][:4]}"
        else:
            year_range = "unknown period"

        prompt = self.prompts.render(
            "lens_discovery",
            year_range=year_range,
            total_count=len(rows),
            all_summaries=summaries_block
        )

        try:
            raw_response = await self.vision.synthesize_text(
                text=prompt,
                max_tokens=self.settings.max_tokens_lens_discovery
            )
        except Exception as e:
            raise RuntimeError(f"Lens discovery API call failed: {e}")

        result = self._parse_json_dict(raw_response)
        lenses_data = result.get('lenses', [])

        if not lenses_data:
            print(f"[Phase2] No lenses returned. Raw response: {raw_response[:500]}")
            return

        # Build filename → drawing_id map
        filename_to_id = {r['filename']: r['id'] for r in rows}

        for sort_order, lens_data in enumerate(lenses_data):
            name = lens_data.get('name', f'Lens {sort_order + 1}')
            description = lens_data.get('description', '')
            drawing_relevance = lens_data.get('drawing_relevance', {})

            cursor = db.execute("""
                INSERT OR IGNORE INTO lenses
                  (user_id, archive_analysis_id, name, description, sort_order, raw_claude_output)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                user_id, analysis_id, name, description,
                sort_order, json.dumps(lens_data)
            ))

            # If already exists (IGNORE), fetch it
            lens_row = db.execute(
                "SELECT id FROM lenses WHERE user_id = ? AND name = ?", (user_id, name)
            ).fetchone()
            lens_id = lens_row['id']

            # Store relevance scores for ALL drawings
            for filename, score in drawing_relevance.items():
                drawing_id = filename_to_id.get(filename)
                if drawing_id is not None:
                    db.execute("""
                        INSERT OR IGNORE INTO lens_drawing_links
                          (lens_id, drawing_id, relevance_score)
                        VALUES (?, ?, ?)
                    """, (lens_id, drawing_id, float(score)))

            db.commit()
            print(f"[Phase2] Lens '{name}' stored with {len(drawing_relevance)} scores")

    # ─── Phase 3: Lens annotation batch ──────────────────────────────────────

    async def _annotate_batch(self, db: sqlite3.Connection, lens: sqlite3.Row, batch: list) -> None:
        """Annotate a batch of drawings through a lens."""

        # Build drawing entries block
        entries = []
        for d in batch:
            date_str = d['drawn_date'] or 'unknown'
            text = d['analysis_text'] or '(no description available)'
            entries.append(f"{d['filename']} ({date_str}): {text}")
        drawing_entries = "\n".join(entries)

        prompt = self.prompts.render(
            "lens_annotation_batch",
            lens_name=lens['name'],
            lens_description=lens['description'],
            drawing_entries=drawing_entries
        )

        try:
            raw_response = await self.vision.synthesize_text(
                text=prompt,
                max_tokens=self.settings.max_tokens_annotation_batch
            )
        except Exception as e:
            print(f"[Phase3] Annotation API call failed: {e}")
            return

        annotations = self._parse_json_list(raw_response)
        filename_to_annotation = {item.get('filename', ''): item.get('annotation', '') for item in annotations}

        for d in batch:
            annotation = filename_to_annotation.get(d['filename'])
            if annotation:
                db.execute("""
                    UPDATE lens_drawing_links
                    SET annotation = ?, annotation_generated_at = datetime('now')
                    WHERE lens_id = ? AND drawing_id = ?
                """, (annotation, lens['id'], d['id']))

    # ─── JSON parsing utilities ───────────────────────────────────────────────

    def _strip_markdown_fences(self, text: str) -> str:
        """Remove ```json ... ``` wrapping that Claude sometimes adds."""
        text = text.strip()
        if text.startswith("```"):
            text = text[text.find('\n') + 1:]
        if text.endswith("```"):
            text = text[:text.rfind("```")]
        return text.strip()

    def _parse_json_list(self, text: str) -> list:
        """Parse Claude's response as a JSON array."""
        text = self._strip_markdown_fences(text)
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # Fallback: try to extract array with regex
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        print(f"[JSON] Failed to parse list from: {text[:300]}")
        return []

    def _parse_json_dict(self, text: str) -> dict:
        """Parse Claude's response as a JSON object."""
        text = self._strip_markdown_fences(text)
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Fallback: try to extract object with regex
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        print(f"[JSON] Failed to parse dict from: {text[:300]}")
        return {}


# ─── Singleton ────────────────────────────────────────────────────────────────

_analyzer: Optional[ArchiveAnalyzer] = None


def get_archive_analyzer() -> ArchiveAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = ArchiveAnalyzer()
    return _analyzer
