"""
OpenRouter API adapters for embeddings + images.

Why this exists:
- `esperanto` supports OpenRouter for LLMs, but does not provide an OpenRouter *embedding* provider.
- OpenRouter image generation uses the chat/completions API with image modalities.

This module provides a uniform app-level interface:
- Embeddings: `OpenRouterEmbeddingModel.aembed([...])`
- Images: `generate_image()` and `edit_image()`
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import httpx
from loguru import logger

# Embeddings endpoint
OPENROUTER_EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"

# Image endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


def _get_openrouter_api_key() -> str:
    api_key = os.environ.get(OPENROUTER_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            "OpenRouter requires OPENROUTER_API_KEY to be set (env var missing)."
        )
    return api_key


from esperanto.common_types import Model as EsperantoModel
from esperanto.providers.embedding.base import EmbeddingModel


@dataclass
class OpenRouterEmbeddingModel(EmbeddingModel):
    """
    OpenRouter embeddings adapter.

    This subclasses `esperanto.providers.embedding.base.EmbeddingModel` because
    your app asserts `isinstance(model, EmbeddingModel)`.
    """

    def __post_init__(self) -> None:
        # Ensure base dataclass initialization happens (sets task-related fields).
        super().__post_init__()

    @property
    def provider(self) -> str:
        return "openrouter"

    def _get_models(self) -> List[EsperantoModel]:
        # Model discovery is not required for runtime embeddings in this app.
        return []

    def _get_default_model(self) -> str:
        return self.model_name or "openai/text-embedding-3-small"

    def embed(self, texts: List[str], **kwargs: Any) -> List[List[float]]:
        # The app currently only calls `aembed()`.
        raise NotImplementedError("Use aembed() for OpenRouter embeddings.")

    async def aembed(self, texts: List[str], **kwargs: Any) -> List[List[float]]:
        """
        Embed a list of texts. Returns list of embedding vectors.
        """
        if not texts:
            return []

        api_key = self.api_key or os.environ.get(OPENROUTER_API_KEY_ENV)
        if not api_key:
            raise RuntimeError(
                "OpenRouter embeddings require OPENROUTER_API_KEY to be set."
            )

        # OpenRouter accepts single string or array of strings
        input_payload = texts[0] if len(texts) == 1 else texts
        payload: Dict[str, Any] = {"model": self.model_name, "input": input_payload}

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                OPENROUTER_EMBEDDINGS_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code != 200:
            try:
                err = response.json()
                msg = err.get("error", {}).get("message", response.text)
            except Exception:
                msg = response.text
            raise RuntimeError(
                f"OpenRouter embeddings error ({response.status_code}): {msg}"
            )

        data = response.json()
        items = data.get("data") or []

        # Preserve order; each item has "embedding" key
        out: List[List[float]] = []
        for item in items:
            emb = item.get("embedding")
            if emb is None:
                raise RuntimeError("OpenRouter returned an entry without 'embedding'")
            out.append(emb)

        logger.debug(
            f"[OpenRouter embeddings] model={self.model_name!r}, requested={len(texts)}, got={len(out)}"
        )
        return out


def create_openrouter_embedding_model(model_name: str) -> OpenRouterEmbeddingModel:
    """Create an OpenRouter embedding model using OPENROUTER_API_KEY."""
    api_key = os.environ.get(OPENROUTER_API_KEY_ENV)
    if not api_key:
        raise ValueError(
            "OPENROUTER_API_KEY is not set. Set it to use OpenRouter for embeddings."
        )
    # `EmbeddingModel` expects `api_key` + `model_name` attributes.
    return OpenRouterEmbeddingModel(model_name=model_name, api_key=api_key)


async def generate_image(prompt: str) -> str:
    """
    Generate an image from a text prompt using the app's default OpenRouter image model.

    Returns:
    - A data URL string (e.g. `data:image/png;base64,...`)
    - Or an error message string (to avoid crashing the chat flow)
    """
    result = await generate_images(prompt=prompt, max_images=1)
    if isinstance(result, str):
        return result
    return result[0] if result else "The model did not return an image."


def _extract_image_data_urls(message: Any) -> List[str]:
    urls: List[str] = []
    images = message.get("images") if isinstance(message, dict) else None
    images = images or []
    for item in images:
        if isinstance(item, dict):
            image_url_obj = item.get("image_url")
            url = image_url_obj.get("url") if isinstance(image_url_obj, dict) else None
        else:
            url = getattr(getattr(item, "image_url", None), "url", None)
        if isinstance(url, str) and url.startswith("data:image/"):
            urls.append(url)
    return urls


async def generate_images(prompt: str, max_images: int = 1) -> Union[List[str], str]:
    """
    Generate one or more images from a text prompt using the app's default OpenRouter image model.

    Returns:
    - A list of data URL strings.
    - Or an error message string.
    """
    requested = max(1, min(int(max_images), 5))
    api_key = os.environ.get(OPENROUTER_API_KEY_ENV)
    if not api_key:
        return "Image generation is not configured: OPENROUTER_API_KEY is not set."

    # Lazy import to avoid circular import issues at startup.
    from open_notebook.domain.models import DefaultModels, Model

    defaults = await DefaultModels.get_instance()
    model_id = getattr(defaults, "default_image_model", None) if defaults else None
    if not model_id:
        return (
            "No default image model is set. Please set one in Models -> Default Model Assignments -> Image Generation Model."
        )

    try:
        model_record = await Model.get(model_id)
    except Exception as e:
        logger.warning(f"Failed to load image model {model_id}: {e}")
        return f"Could not load the selected image model: {model_id}."

    if model_record.provider.lower() != "openrouter":
        return (
            "Image generation is only supported with an OpenRouter model. Please set an OpenRouter model as the default image model."
        )

    model_name = model_record.name
    logger.info(
        f"[Image flow] OpenRouter: using model {model_name!r}, prompt length {len(prompt)}, requested images={requested}, "
        f"prompt preview: {prompt[:150]!r}{'...' if len(prompt) > 150 else ''}"
    )

    model_lower = (model_name or "").lower()
    if "flux" in model_lower or "sourceful" in model_lower or "riverflow" in model_lower:
        modalities = ["image"]
    else:
        modalities = ["image", "text"]

    async def _request_images(batch_size: int) -> Union[List[str], str]:
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "modalities": modalities,
            "n": batch_size,
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    OPENROUTER_API_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException:
            return "Image generation timed out. Please try again."
        except Exception as e:
            logger.exception(e)
            return f"Image generation request failed: {str(e)}"

        if response.status_code != 200:
            try:
                err_body = response.json()
                err_msg = err_body.get("error", {}).get("message", response.text)
            except Exception:
                err_msg = response.text
            return f"OpenRouter error ({response.status_code}): {err_msg}"

        try:
            data = response.json()
        except Exception as e:
            return f"Invalid response from image API: {e}"

        choices = data.get("choices") or []
        if not choices:
            return []

        urls: List[str] = []
        for choice in choices:
            urls.extend(_extract_image_data_urls(choice.get("message", {})))
        return urls

    # Attempt 1: ask for all requested images in one call.
    first_batch = await _request_images(requested)
    if isinstance(first_batch, str):
        return first_batch
    urls: List[str] = list(first_batch)

    # Some OpenRouter image models ignore `n` and still return one image.
    # Fallback by issuing additional single-image requests in parallel.
    if len(urls) < requested:
        remaining = requested - len(urls)
        logger.info(
            f"[Image flow] OpenRouter: model returned {len(urls)} image(s) for n={requested}; "
            f"issuing {remaining} additional request(s)"
        )
        extra_batches = await asyncio.gather(
            *[_request_images(1) for _ in range(remaining)], return_exceptions=False
        )
        for batch in extra_batches:
            if isinstance(batch, list):
                urls.extend(batch)
            elif isinstance(batch, str):
                logger.warning(f"[Image flow] Additional image request failed: {batch}")

    # Deduplicate while preserving order in case provider returns duplicates.
    deduped: List[str] = []
    seen = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
        if len(deduped) >= requested:
            break

    if not deduped:
        return "The model did not return an image. Try a clearer prompt (e.g. 'Generate an image of a lion')."

    logger.info(
        f"[Image flow] OpenRouter: received {len(deduped)} image(s), requested={requested}"
    )
    return deduped[:requested]


async def edit_image(image_data_url: str, instruction: str) -> str:
    """
    Edit an existing image using the app's default OpenRouter image model.

    Returns:
    - A data URL string with the edited image, or an error message string.
    """
    api_key = os.environ.get(OPENROUTER_API_KEY_ENV)
    if not api_key:
        return "Image editing is not configured: OPENROUTER_API_KEY is not set."

    # Lazy import to avoid circular import issues at startup.
    from open_notebook.domain.models import DefaultModels, Model

    defaults = await DefaultModels.get_instance()
    model_id = getattr(defaults, "default_image_model", None) if defaults else None
    if not model_id:
        return (
            "No default image model is set. Image editing uses the same model as generation (Models → Default Model Assignments → Image Generation Model)."
        )

    try:
        model_record = await Model.get(model_id)
    except Exception as e:
        logger.warning(f"Failed to load image model {model_id}: {e}")
        return f"Could not load the selected image model: {model_id}."

    if model_record.provider.lower() != "openrouter":
        return (
            "Image editing is only supported with an OpenRouter model as the default image model."
        )

    model_name = model_record.name
    model_lower = (model_name or "").lower()

    # Models that support image-in + image-out need ["image", "text"].
    # Flux text-to-image often doesn't accept image input; prefer dual modality.
    if "flux" in model_lower and "fill" not in model_lower:
        modalities = ["image", "text"]
    else:
        modalities = ["image", "text"]

    user_content = [
        {
            "type": "text",
            "text": (
                "Edit this image according to the following instruction. Output only the edited image.\n\n"
                f"Instruction: {instruction}"
            ),
        },
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": user_content}],
        "modalities": modalities,
    }

    logger.info(f"[Image edit] OpenRouter: model {model_name!r}, instruction length {len(instruction)}")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.TimeoutException:
        return "Image editing timed out. Please try again."
    except Exception as e:
        logger.exception(e)
        return f"Image editing request failed: {str(e)}"

    if response.status_code != 200:
        try:
            err_body = response.json()
            err_msg = err_body.get("error", {}).get("message", response.text)
        except Exception:
            err_msg = response.text
        return f"OpenRouter error ({response.status_code}): {err_msg}"

    try:
        data = response.json()
    except Exception as e:
        return f"Invalid response from image API: {e}"

    choices = data.get("choices")
    if not choices:
        return (
            "No response from image model. The model may not support image editing (image input + image output). Try a model like Gemini 2.5 Flash Image."
        )

    message = choices[0].get("message", {})
    images = message.get("images") or []

    if not images:
        text = message.get("content", "")
        return (
            text
            or "The model did not return an edited image. Some models only generate from text; use 'edit by re-prompt' or set an image-editing capable model (e.g. Gemini 2.5 Flash Image)."
        )

    first = images[0]
    if isinstance(first, dict):
        image_url_obj = first.get("image_url")
        url = image_url_obj.get("url") if isinstance(image_url_obj, dict) else None
    else:
        url = getattr(getattr(first, "image_url", None), "url", None)

    if not url or not str(url).startswith("data:image/"):
        logger.warning("[Image edit] OpenRouter returned response but no valid data URL")
        return "The model returned an invalid image format."

    logger.info(f"[Image edit] OpenRouter: edited image received, data URL length {len(str(url))}")
    return str(url)


__all__ = [
    "OpenRouterEmbeddingModel",
    "create_openrouter_embedding_model",
    "generate_image",
    "generate_images",
    "edit_image",
]

