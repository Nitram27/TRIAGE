"""
Database SQLite del Feedback Service.
Gestisce due tabelle:
  - cases   : coda casi clinici (tecnico → coda → medico)
  - feedback: storico delle revisioni mediche
"""

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/data/feedback.db")


def init_db() -> None:
    with connect() as conn:
        # Tabella coda casi
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id          TEXT NOT NULL UNIQUE,
                patient_id       TEXT,
                age              INTEGER,
                sex              TEXT,
                image_b64        TEXT NOT NULL,
                inference_json   TEXT NOT NULL,
                explanation_json TEXT NOT NULL,
                triage_json      TEXT NOT NULL,
                confidence       REAL DEFAULT 0.5,
                status           TEXT DEFAULT 'pending_review',
                submitted_by     TEXT,
                submitted_at     TEXT DEFAULT (datetime('now')),
                reviewed_by      TEXT,
                reviewed_at      TEXT,
                review_json      TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_case_id ON cases(case_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_status  ON cases(status)")

        # Migrazione: aggiunge colonna confidence se non esiste
        try:
            conn.execute("ALTER TABLE cases ADD COLUMN confidence REAL DEFAULT 0.5")
        except Exception:
            pass  # colonna già presente

        # Migrazione: aggiorna confidence dei casi esistenti da inference_json
        import json as _json
        rows = conn.execute(
            "SELECT case_id, inference_json FROM cases WHERE confidence = 0.5"
        ).fetchall()
        for row in rows:
            try:
                conf = _json.loads(row["inference_json"]).get("confidence", 0.5)
                if conf != 0.5:
                    conn.execute(
                        "UPDATE cases SET confidence=? WHERE case_id=?",
                        (conf, row["case_id"])
                    )
            except Exception:
                pass

        # Tabella feedback (compatibilità con flusso precedente)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id        TEXT NOT NULL,
                clinician_id   TEXT NOT NULL,
                agreed         INTEGER NOT NULL,
                label_override INTEGER,
                notes          TEXT,
                created_at     TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_case ON feedback(case_id)")


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
