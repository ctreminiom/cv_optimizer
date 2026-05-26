"""
memory.py — Recommendation #16.

Persistent SQLite-backed memory for CrewAI agents. Stores facts learned
across runs (especially the candidate's voice signature, decisions made
in interactive mode, and patterns from prior jobs).

This is intentionally simple: a single key-value table with namespaces.
For more sophisticated retrieval, swap to a vector store later.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

DB_PATH = Path("cache/memory.sqlite")


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            namespace TEXT,
            key TEXT,
            value TEXT,
            updated_at REAL,
            PRIMARY KEY (namespace, key)
        )
    """)
    return conn


def remember(namespace: str, key: str, value: Any) -> None:
    """Store a fact under (namespace, key). Overwrites existing."""
    payload = json.dumps(value, default=str)
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO memory (namespace, key, value, updated_at) VALUES (?, ?, ?, ?)",
            (namespace, key, payload, time.time()),
        )


def recall(namespace: str, key: str) -> Any | None:
    """Retrieve a fact by (namespace, key), or None."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT value FROM memory WHERE namespace=? AND key=?",
            (namespace, key),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return row[0]


def list_namespace(namespace: str) -> dict[str, Any]:
    """Return all key/value pairs in a namespace."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT key, value FROM memory WHERE namespace=?",
            (namespace,),
        ).fetchall()
    out: dict[str, Any] = {}
    for k, v in rows:
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def forget(namespace: str, key: str | None = None) -> int:
    """Remove a key, or the whole namespace if key is None. Returns deleted count."""
    with _conn() as conn:
        if key is None:
            cur = conn.execute("DELETE FROM memory WHERE namespace=?", (namespace,))
        else:
            cur = conn.execute(
                "DELETE FROM memory WHERE namespace=? AND key=?",
                (namespace, key),
            )
        return cur.rowcount
