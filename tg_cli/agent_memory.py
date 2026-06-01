import datetime as _dt
import hashlib
import sqlite3
from pathlib import Path


def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).replace(
        microsecond=0).isoformat()


def _row_dict(row):
    return {key: row[key] for key in row.keys()}


class MemoryStore:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_schema(self):
        with self._connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS rooms (
              chat_id INTEGER PRIMARY KEY,
              title TEXT,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              chat_id INTEGER NOT NULL,
              scope TEXT NOT NULL,
              sender_id INTEGER,
              sender_name TEXT,
              kind TEXT NOT NULL,
              content TEXT NOT NULL,
              confidence REAL NOT NULL,
              source_task_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              chat_id INTEGER NOT NULL,
              message_id INTEGER,
              sender_id INTEGER,
              sender_name TEXT,
              direction TEXT NOT NULL,
              text_hash TEXT NOT NULL,
              text_len INTEGER NOT NULL,
              created_at TEXT NOT NULL
            );
            """)

    def upsert_room(self, chat_id, title=None):
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rooms(chat_id, title, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                  title=excluded.title,
                  updated_at=excluded.updated_at
                """,
                (int(chat_id), title, utc_now()),
            )

    def remember(self, chat_id, scope, content, kind='note', sender_id=None,
                 sender_name=None, confidence=1.0, source_task_id=None):
        scope = str(scope or '').strip()
        if scope not in ('room', 'user'):
            raise ValueError('scope must be room or user.')
        content = str(content or '').strip()
        if not content:
            raise ValueError('content must not be empty.')
        confidence = float(confidence)
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError('confidence must be between 0 and 1.')
        if scope == 'user' and sender_id is None:
            raise ValueError('sender_id is required for user memory.')
        self.ensure_schema()
        now = utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO memories(
                  chat_id, scope, sender_id, sender_name, kind, content,
                  confidence, source_task_id, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(chat_id), scope, sender_id, sender_name,
                    str(kind or 'note'), content, confidence, source_task_id,
                    now, now,
                ),
            )
            return int(cursor.lastrowid)

    def relevant_memories(self, chat_id, sender_id=None, limit=8):
        self.ensure_schema()
        limit = int(limit)
        if limit <= 0:
            return []
        params = [int(chat_id)]
        filters = ["scope = 'room'"]
        if sender_id is not None:
            filters.append("(scope = 'user' AND sender_id = ?)")
            params.append(int(sender_id))
        params.append(limit)
        sql = """
            SELECT id, chat_id, scope, sender_id, sender_name, kind, content,
                   confidence, source_task_id, created_at, updated_at
            FROM memories
            WHERE chat_id = ? AND ({})
            ORDER BY
              CASE WHEN scope = 'user' THEN 0 ELSE 1 END,
              updated_at DESC,
              id DESC
            LIMIT ?
        """.format(' OR '.join(filters))
        with self._connect() as conn:
            return [_row_dict(row) for row in conn.execute(sql, params)]

    def record_event(self, chat_id, message_id, sender_id, sender_name,
                     direction, text):
        self.ensure_schema()
        text = str(text or '')
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events(
                  chat_id, message_id, sender_id, sender_name, direction,
                  text_hash, text_len, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(chat_id), message_id, sender_id, sender_name,
                    str(direction or 'in'), digest, len(text), utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def events(self, chat_id, limit=20):
        self.ensure_schema()
        with self._connect() as conn:
            return [
                _row_dict(row)
                for row in conn.execute(
                    """
                    SELECT id, chat_id, message_id, sender_id, sender_name,
                           direction, text_hash, text_len, created_at
                    FROM events
                    WHERE chat_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (int(chat_id), max(1, int(limit))),
                )
            ]
