"""CLIP embedding service for local image vectorization (Phase 4)."""

from __future__ import annotations

import io
import numpy as np
from pathlib import Path
from typing import Optional


class EmbeddingService:
    """
    Wraps OpenAI CLIP ViT-B/32 via open_clip for local image embedding.

    Usage:
        svc = EmbeddingService()
        vec = svc.encode_image("/path/to/drawing.jpg")  # shape (512,) float32, L2-normalized
    """

    def __init__(self) -> None:
        import open_clip
        import torch

        self._device = "cpu"  # CPU-only for demo
        self._model, _, self._preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="openai", device=self._device
        )
        self._model.eval()
        self._torch = torch
        print("[Embeddings] CLIP ViT-B/32 loaded (CPU)")

    def encode_image(self, filepath: str) -> np.ndarray:
        """
        Encode a single image file to a 512-dim float32 L2-normalized vector.
        Returns zero vector if file can't be opened.
        """
        from PIL import Image

        try:
            with Image.open(filepath) as img:
                img_rgb = img.convert("RGB")
                tensor = self._preprocess(img_rgb).unsqueeze(0).to(self._device)
        except Exception as e:
            print(f"[Embeddings] Failed to open {filepath}: {e}")
            return np.zeros(512, dtype=np.float32)

        with self._torch.no_grad():
            features = self._model.encode_image(tensor)
            features = features / features.norm(dim=-1, keepdim=True)
        return features.cpu().numpy()[0].astype(np.float32)

    @staticmethod
    def vector_to_blob(vec: np.ndarray) -> bytes:
        """Serialize numpy float32 array to raw bytes for SQLite storage."""
        return vec.astype(np.float32).tobytes()

    @staticmethod
    def blob_to_vector(blob: bytes) -> np.ndarray:
        """Deserialize raw bytes from SQLite to numpy float32 array."""
        return np.frombuffer(blob, dtype=np.float32).copy()

    def encode_all_user_drawings(self, user_id: int, db) -> int:
        """
        Encode all drawings for a user that don't yet have embeddings.
        Stores each embedding as a BLOB in the embeddings table.
        Returns the number of newly computed embeddings.
        """
        rows = db.execute(
            """
            SELECT d.id, d.filepath
            FROM drawings d
            LEFT JOIN embeddings e ON e.drawing_id = d.id
            WHERE d.user_id = ? AND e.drawing_id IS NULL
            """,
            (user_id,),
        ).fetchall()

        if not rows:
            return 0

        count = 0
        for row in rows:
            vec = self.encode_image(row["filepath"])
            blob = self.vector_to_blob(vec)
            db.execute(
                """
                INSERT OR REPLACE INTO embeddings (drawing_id, vector_blob, model_name)
                VALUES (?, ?, 'ViT-B-32/openai')
                """,
                (row["id"], blob),
            )
            count += 1

        db.commit()
        return count

    def compute_umap(self, vectors: np.ndarray) -> np.ndarray:
        """
        Run UMAP on an (N, 512) float32 matrix.
        Returns (N, 2) float32 array with coordinates normalized to [0, 1].
        Falls back to PCA if umap-learn is unavailable.
        """
        n = len(vectors)
        if n < 2:
            return np.zeros((n, 2), dtype=np.float32)

        try:
            import umap

            reducer = umap.UMAP(
                n_components=2,
                metric="cosine",
                n_neighbors=min(15, n - 1),
                min_dist=0.1,
                random_state=42,
            )
            coords = reducer.fit_transform(vectors).astype(np.float32)
        except ImportError:
            # Fallback: PCA via numpy SVD
            print("[Embeddings] umap-learn not available, falling back to PCA")
            centered = vectors - vectors.mean(axis=0)
            _, _, vh = np.linalg.svd(centered, full_matrices=False)
            coords = (centered @ vh[:2].T).astype(np.float32)

        # Normalize to [0, 1]
        for dim in range(2):
            col = coords[:, dim]
            lo, hi = col.min(), col.max()
            if hi > lo:
                coords[:, dim] = (col - lo) / (hi - lo)
            else:
                coords[:, dim] = 0.5

        return coords


# Module-level singleton (lazy init — avoids loading CLIP on every import)
_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service
