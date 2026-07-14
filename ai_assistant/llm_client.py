from __future__ import annotations

import numpy as np
from openai import OpenAI

from .config import Settings


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._client = OpenAI(api_key=settings.openai_api_key)

    def embed(self, texts: list[str]) -> np.ndarray:
        resp = self._client.embeddings.create(model=self._s.embed_model, input=texts)
        vecs = [np.asarray(d.embedding, dtype="float32") for d in resp.data]
        return np.vstack(vecs)

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def chat(self, system: str, user: str) -> str:
        resp = self._client.responses.create(
            model=self._s.llm_model,
            instructions=system,
            input=user,
        )
        return resp.output_text
