from collections.abc import Sequence
from typing import Protocol

from openai import AsyncOpenAI


class Embedder(Protocol):
    model: str

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str, dimensions: int) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.dimensions = dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(
            model=self.model,
            input=list(texts),
            dimensions=self.dimensions,
            encoding_format="float",
        )
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
