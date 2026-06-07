"""
DB SQLite del Data Ingestion Service.
Archivia le immagini MRI pre-processate con i relativi metadati.
"""

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/data/mri_store.db")


def init_db() -> None:
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mri_images (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id          TEXT NOT NULL UNIQUE,
                original_filename TEXT,
                original_mode     TEXT,
                original_size     TEXT,
                output_size       TEXT,
                image_b64         TEXT NOT NULL,
                submitted_at      TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mri_image_id ON mri_images(image_id)"
        )


@contextmanager
def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
