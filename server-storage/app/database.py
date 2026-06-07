import os, sqlite3, uuid
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/data/server_storage.db")

def init_db():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clinical_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id    TEXT NOT NULL UNIQUE,
                service     TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                payload     TEXT DEFAULT '{}',
                actor       TEXT DEFAULT 'system',
                received_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clinical_events_type ON clinical_events(event_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clinical_events_svc  ON clinical_events(service)")

@contextmanager
def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn; conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
