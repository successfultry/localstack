from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    dim INTEGER NOT NULL,
    embedding BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    sha TEXT NOT NULL
);
"""


@dataclass
class Chunk:
    path: str
    chunk_index: int
    text: str
    embedding: np.ndarray


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def file_sha(self, path: str) -> str | None:
        row = self.conn.execute("SELECT sha FROM files WHERE path = ?", (path,)).fetchone()
        return row[0] if row else None

    def replace_file(self, path: str, sha: str, chunks: list[Chunk]) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM chunks WHERE path = ?", (path,))
        cur.executemany(
            "INSERT INTO chunks (path, chunk_index, text, dim, embedding) VALUES (?, ?, ?, ?, ?)",
            [
                (c.path, c.chunk_index, c.text, c.embedding.shape[0], c.embedding.astype("float32").tobytes())
                for c in chunks
            ],
        )
        cur.execute(
            "INSERT INTO files (path, sha) VALUES (?, ?) "
            "ON CONFLICT(path) DO UPDATE SET sha = excluded.sha",
            (path, sha),
        )
        self.conn.commit()

    def prune_missing(self, keep_paths: set[str]) -> None:
        rows = self.conn.execute("SELECT DISTINCT path FROM chunks").fetchall()
        stale = [r[0] for r in rows if r[0] not in keep_paths]
        cur = self.conn.cursor()
        for p in stale:
            cur.execute("DELETE FROM chunks WHERE path = ?", (p,))
            cur.execute("DELETE FROM files WHERE path = ?", (p,))
        self.conn.commit()

    def load_matrix(self) -> tuple[np.ndarray, list[tuple[str, str]]]:
        rows = self.conn.execute(
            "SELECT path, text, dim, embedding FROM chunks ORDER BY path, chunk_index"
        ).fetchall()
        if not rows:
            return np.zeros((0, 0), dtype="float32"), []
        vecs = [np.frombuffer(r[3], dtype="float32", count=r[2]) for r in rows]
        meta = [(r[0], r[1]) for r in rows]
        return np.vstack(vecs), meta

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
