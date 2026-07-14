from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import REPO_ROOT, Settings
from .llm_client import LLMClient
from .store import Chunk, Store

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
EMBED_BATCH = 64
MIN_SCORE = 0.20

SYSTEM = (
    "You are a developer assistant for the LocalStack project. Answer questions about "
    "the project using ONLY the provided documentation context. If the context does not "
    "contain the answer, say you don't know and suggest where to look. Cite sources as "
    "[path] inline. Be concise and technical."
)


@dataclass
class Hit:
    path: str
    text: str
    score: float


def discover(settings: Settings) -> list[Path]:
    seen: dict[Path, None] = {}
    for pattern in settings.rag_include:
        for p in REPO_ROOT.glob(pattern):
            if p.is_file():
                seen[p.resolve()] = None
    return list(seen.keys())


def chunk_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    out: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + CHUNK_SIZE, n)
        out.append(text[start:end])
        if end == n:
            break
        start = end - CHUNK_OVERLAP
    return out


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Rag:
    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self.s = settings
        self.llm = llm
        self.store = Store(settings.index_path)

    def reindex(self, force: bool = False) -> dict[str, int]:
        files = discover(self.s)
        keep = {str(p.relative_to(REPO_ROOT)).replace("\\", "/") for p in files}
        indexed = skipped = 0
        for path in files:
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            raw = path.read_bytes()
            sha = _sha(raw)
            if not force and self.store.file_sha(rel) == sha:
                skipped += 1
                continue
            texts = chunk_text(raw.decode("utf-8", errors="replace"))
            if not texts:
                self.store.replace_file(rel, sha, [])
                continue
            vecs = self._embed_batched(texts)
            chunks = [Chunk(rel, i, t, vecs[i]) for i, t in enumerate(texts)]
            self.store.replace_file(rel, sha, chunks)
            indexed += 1
        self.store.prune_missing(keep)
        return {"files": len(files), "indexed": indexed, "skipped": skipped, "chunks": self.store.count()}

    def _embed_batched(self, texts: list[str]) -> np.ndarray:
        parts = []
        for i in range(0, len(texts), EMBED_BATCH):
            parts.append(self.llm.embed(texts[i : i + EMBED_BATCH]))
        return np.vstack(parts)

    def retrieve(self, query: str, k: int = 6) -> list[Hit]:
        matrix, meta = self.store.load_matrix()
        if matrix.shape[0] == 0:
            return []
        q = self.llm.embed_one(query)
        sims = _cosine(matrix, q)
        top = np.argsort(-sims)[:k]
        return [Hit(meta[i][0], meta[i][1], float(sims[i])) for i in top]

    def answer(self, query: str, k: int = 6) -> tuple[str, list[Hit]]:
        hits = self.retrieve(query, k)
        useful = [h for h in hits if h.score >= MIN_SCORE]
        if not useful:
            return (
                "I couldn't find relevant docs for that. Try `--reindex`, or ask about "
                "something covered in README / docs/.",
                hits,
            )
        context = "\n\n".join(f"[{h.path}]\n{h.text}" for h in useful)
        reply = self.llm.chat(SYSTEM, f"Context:\n{context}\n\nQuestion: {query}")
        return reply, useful


def _cosine(matrix: np.ndarray, q: np.ndarray) -> np.ndarray:
    m_norm = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-8)
    q_norm = q / (np.linalg.norm(q) + 1e-8)
    return m_norm @ q_norm
