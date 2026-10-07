"""OpenAI adapters for thematic segmentation and vector generation."""

from src.extractors.document_embeddings import Segmentation, token_count
from src.services.async_provider import AsyncProvider


class OpenAIDocumentEmbeddingProvider(AsyncProvider):
    def __init__(self, api_key, segmentation_model, client=None, *, max_retries=0):
        self._api_key, self.segmentation_model = api_key, segmentation_model
        self._max_retries = max_retries
        self._configure_client(client)

    def client(self):
        if self._client is None:
            if not self._api_key:
                raise ValueError("embedding_api_key_required")
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self._api_key, timeout=self._timeout, max_retries=self._max_retries
            )
        return self._client

    async def segment(self, blocks, profile, target):
        content = f"Target section size: {target} tokens.\n" + "\n".join(
            f"[BLOCK {index}]\n{text}" for index, text in enumerate(blocks, 1)
        )
        async with self._request_slot():
            response = await self.client().responses.parse(
                model=self.segmentation_model,
                store=False,
                text_format=Segmentation,
                input=[
                    {"role": "system", "content": profile.instructions},
                    {"role": "user", "content": content},
                ],
            )
        if response.output_parsed is None:
            raise ValueError("embedding_segmentation_missing")
        return Segmentation.model_validate(response.output_parsed)

    async def embed(self, texts, configuration):
        if any(not text.strip() or token_count(text) > 8192 for text in texts):
            raise ValueError("embedding_input_token_limit")
        async with self._request_slot():
            response = await self.client().embeddings.create(
                model=configuration.model,
                dimensions=configuration.dimensions,
                input=texts,
            )
        data = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in data] != list(range(len(texts))):
            raise ValueError("embedding_response_indexes_invalid")
        return [item.embedding for item in data]
