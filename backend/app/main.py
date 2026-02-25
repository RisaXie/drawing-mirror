"""Drawing Mirror — FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import init_db, get_db_connection
from app.services.drawing_loader import (
    scan_user_dataset, scan_catalog_dataset,
    generate_thumbnail, get_image_dimensions,
)
from app.routers import users, drawings, archive, lenses, reactions

BASE_DIR = Path(__file__).parent
WEB_DIR = BASE_DIR / "web"


# ─── Startup ──────────────────────────────────────────────────────────────────

async def seed_users_and_drawings(settings) -> None:
    """
    On startup: scan dataset_root for user subdirectories.
    For each user dir: ensure user exists in DB, scan drawings, generate missing thumbnails.
    """
    dataset_root = Path(settings.dataset_root)
    if not dataset_root.exists():
        print(f"[Startup] dataset_root not found: {dataset_root}")
        return

    db = get_db_connection()
    try:
        for user_dir in sorted(dataset_root.iterdir()):
            if not user_dir.is_dir() or user_dir.name.startswith('.'):
                continue

            username = user_dir.name
            dataset_path = str(user_dir.absolute())

            # Insert user if not exists
            db.execute("""
                INSERT OR IGNORE INTO users (username, display_name, dataset_path)
                VALUES (?, ?, ?)
            """, (username, username, dataset_path))
            db.commit()

            user_row = db.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            user_id = user_row['id']

            # Scan filesystem for drawings
            file_list = scan_user_dataset(dataset_path)

            # Insert new drawings
            for drawing in file_list:
                db.execute("""
                    INSERT OR IGNORE INTO drawings
                      (user_id, filename, filepath, drawn_date, title, file_ext)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    drawing['filename'],
                    drawing['filepath'],
                    drawing['drawn_date'],
                    drawing['title'],
                    drawing['file_ext'],
                ))
            db.commit()

            # Generate missing thumbnails + update dimensions
            thumb_dir = Path(settings.thumbnail_dir) / username
            thumb_dir.mkdir(parents=True, exist_ok=True)

            rows = db.execute("""
                SELECT id, filepath, thumbnail_path, width
                FROM drawings WHERE user_id = ?
            """, (user_id,)).fetchall()

            for row in rows:
                # Generate thumbnail if missing
                if not row['thumbnail_path'] or not Path(row['thumbnail_path']).exists():
                    thumb_path = str(thumb_dir / f"{row['id']}.jpg")
                    try:
                        generate_thumbnail(row['filepath'], thumb_path)
                        db.execute(
                            "UPDATE drawings SET thumbnail_path = ? WHERE id = ?",
                            (thumb_path, row['id'])
                        )
                    except Exception as e:
                        print(f"[Startup] Thumbnail failed for {row['filepath']}: {e}")

                # Fill in dimensions if missing
                if not row['width']:
                    try:
                        w, h = get_image_dimensions(row['filepath'])
                        db.execute(
                            "UPDATE drawings SET width = ?, height = ? WHERE id = ?",
                            (w, h, row['id'])
                        )
                    except Exception as e:
                        print(f"[Startup] Dimensions failed for {row['filepath']}: {e}")

            db.commit()
            drawing_count = len(file_list)
            print(f"[Startup] User '{username}': {drawing_count} drawings ready")

    finally:
        db.close()


async def seed_catalog_user(settings, username: str, display_name: str,
                             catalog_path: str, images_dir: str) -> None:
    """
    Seed a user whose drawings come from an Excel catalog + image directory.
    Uses scan_catalog_dataset() instead of scan_user_dataset().
    """
    if not catalog_path or not Path(catalog_path).exists():
        print(f"[Startup] Catalog not found, skipping user '{username}': {catalog_path}")
        return
    if not images_dir or not Path(images_dir).exists():
        print(f"[Startup] Images dir not found, skipping user '{username}': {images_dir}")
        return

    db = get_db_connection()
    try:
        db.execute("""
            INSERT OR IGNORE INTO users (username, display_name, dataset_path)
            VALUES (?, ?, ?)
        """, (username, display_name, images_dir))
        db.commit()

        user_row = db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        user_id = user_row['id']

        # Load drawings from catalog
        file_list = scan_catalog_dataset(catalog_path, images_dir)

        for drawing in file_list:
            db.execute("""
                INSERT OR IGNORE INTO drawings
                  (user_id, filename, filepath, drawn_date, title, file_ext)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                drawing['filename'],
                drawing['filepath'],
                drawing['drawn_date'],
                drawing['title'],
                drawing['file_ext'],
            ))
        db.commit()

        # Generate thumbnails + dimensions
        thumb_dir = Path(settings.thumbnail_dir) / username
        thumb_dir.mkdir(parents=True, exist_ok=True)

        rows = db.execute("""
            SELECT id, filepath, thumbnail_path, width
            FROM drawings WHERE user_id = ?
        """, (user_id,)).fetchall()

        for row in rows:
            if not row['thumbnail_path'] or not Path(row['thumbnail_path']).exists():
                thumb_path = str(thumb_dir / f"{row['id']}.jpg")
                try:
                    generate_thumbnail(row['filepath'], thumb_path)
                    db.execute(
                        "UPDATE drawings SET thumbnail_path = ? WHERE id = ?",
                        (thumb_path, row['id'])
                    )
                except Exception as e:
                    print(f"[Startup] Thumbnail failed for {row['filepath']}: {e}")

            if not row['width']:
                try:
                    w, h = get_image_dimensions(row['filepath'])
                    db.execute(
                        "UPDATE drawings SET width = ?, height = ? WHERE id = ?",
                        (w, h, row['id'])
                    )
                except Exception as e:
                    print(f"[Startup] Dimensions failed for {row['filepath']}: {e}")

        db.commit()
        print(f"[Startup] User '{display_name}': {len(file_list)} drawings ready (catalog)")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: init DB and seed data on startup."""
    settings = get_settings()
    init_db()
    await seed_users_and_drawings(settings)
    # Seed catalog-based users (e.g. Doug)
    if settings.doug_catalog:
        await seed_catalog_user(
            settings,
            username="doug",
            display_name="Doug Cooper",
            catalog_path=settings.doug_catalog,
            images_dir=settings.doug_images_dir,
        )
    print("[Startup] Drawing Mirror is ready.")
    yield


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Drawing Mirror API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

# API routers
app.include_router(users.router,    prefix="/api/users",    tags=["users"])
app.include_router(drawings.router, prefix="/api/drawings", tags=["drawings"])
app.include_router(archive.router,  prefix="/api/archive",  tags=["archive"])
app.include_router(lenses.router,   prefix="/api/lenses",   tags=["lenses"])
app.include_router(reactions.router, prefix="/api/reactions", tags=["reactions"])


# ─── HTML Pages ───────────────────────────────────────────────────────────────

def _read_template(name: str) -> str:
    path = WEB_DIR / "templates" / name
    return path.read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
async def index():
    return _read_template("index.html")


@app.get("/archive", response_class=HTMLResponse)
async def archive_page():
    return _read_template("archive.html")


@app.get("/lens-view", response_class=HTMLResponse)
async def lens_view_page():
    return _read_template("lens-view.html")


@app.get("/drawing-detail", response_class=HTMLResponse)
async def drawing_detail_page():
    return _read_template("drawing-detail.html")
