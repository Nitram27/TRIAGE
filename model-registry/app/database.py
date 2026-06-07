"""
DB SQLite del Model Registry.
Gestisce modelli, promozioni e campioni di training.
"""

import json
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/data/model_registry.db")


def init_db() -> None:
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS models (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                version      TEXT NOT NULL UNIQUE,
                status       TEXT DEFAULT 'available',
                framework    TEXT,
                architecture TEXT,
                dataset      TEXT,
                weights_path TEXT,
                metrics_json TEXT DEFAULT '{}',
                is_stub      INTEGER DEFAULT 1,
                created_at   TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS promotions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                version     TEXT NOT NULL,
                promoted_by TEXT DEFAULT 'system',
                promoted_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS training_samples (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id             TEXT NOT NULL,
                final_label         INTEGER,
                confidence_override REAL,
                clinician_id        TEXT,
                agreed_with_ai      INTEGER DEFAULT 1,
                used_for_training   INTEGER DEFAULT 0,
                received_at         TEXT DEFAULT (datetime('now'))
            )
        """)

        # Versione stub di default se il DB è vuoto
        if conn.execute("SELECT COUNT(*) FROM models").fetchone()[0] == 0:
            conn.execute("""
                INSERT INTO models
                  (version, status, framework, architecture, dataset, metrics_json, is_stub)
                VALUES ('stub-0.1.0', 'production', 'stub', 'CNN (da definire)',
                        'N/A — nessun dato reale',
                        '{"accuracy": null, "auc_roc": null, "note": "stub"}', 1)
            """)
            conn.execute("""
                INSERT INTO promotions (version, promoted_by)
                VALUES ('stub-0.1.0', 'system')
            """)


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
