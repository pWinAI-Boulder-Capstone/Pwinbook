"""
OpenRouter image generation via their chat/completions API with modalities=["image"].
Uses the app's default image model (must be an OpenRouter model).
"""
import os
from typing import Optional

import httpx
from loguru import logger

from open_notebook.domain.models import DefaultModels, Model


OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"


async def generate_image(prompt: str) -> str:
    """
    Generate an image from a text prompt using the default image model (OpenRouter).

    Returns:
        The generated image as a data URL string (e.g. data:image/png;base64,...).
        On failure, returns an error message string.
    """
    api_key = os.environ.get(OPENROUTER_API_KEY_ENV)
    if not api_key:
        return "Image generation is not configured: OPENROUTER_API_KEY is not set."

    defaults = await DefaultModels.get_instance()
    model_id = getattr(defaults, "default_image_model", None) if defaults else None
    if not model_id:
        return "No default image model is set. Please set one in Models → Default Model Assignments → Image Generation Model."

    try:
        model_record = await Model.get(model_id)
    except Exception as e:
        logger.warning(f"Failed to load image model {model_id}: {e}")
        return f"Could not load the selected image model: {model_id}."

    if model_record.provider.lower() != "openrouter":
        return "Image generation is only supported with an OpenRouter model. Please set an OpenRouter model as the default image model."

    model_name = model_record.name
    logger.info(
        f"[Image flow] OpenRouter: using model {model_name!r}, prompt length {len(prompt)}, "
        f"prompt preview: {prompt[:150]!r}{'...' if len(prompt) > 150 else ''}"
    )
    # Image-only models (Flux, Sourceful) require modalities=["image"].
    # Models that output both (e.g. Gemini) use ["image", "text"].
    model_lower = (model_name or "").lower()
    if "flux" in model_lower or "sourceful" in model_lower or "riverflow" in model_lower:
        modalities = ["image"]
    else:
        modalities = ["image", "text"]

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": modalities,
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

    choices = data.get("choices")
    if not choices:
        return "No response from image model. The model may not support image generation."

    message = choices[0].get("message", {})
    images = message.get("images") or []

    if not images:
        text = message.get("content", "")
        return text or "The model did not return an image. Try a clearer prompt (e.g. 'Generate an image of a lion')."

    first = images[0]
    if isinstance(first, dict):
        image_url_obj = first.get("image_url")
        url = image_url_obj.get("url") if isinstance(image_url_obj, dict) else None
    else:
        url = getattr(getattr(first, "image_url", None), "url", None)
    if not url or not str(url).startswith("data:image/"):
        logger.warning("[Image flow] OpenRouter returned response but no valid data URL")
        return "The model returned an invalid image format."
    logger.info(f"[Image flow] OpenRouter: image received, data URL length {len(str(url))}")
    return str(url)


async def edit_image(image_data_url: str, instruction: str) -> str:
    """
    Edit an existing image using the model: send image pixels + text instruction,
    get back an edited image. Uses the same default image model; works with
    models that support image input + image output (e.g. Gemini 2.5 Flash Image).

    Args:
        image_data_url: The image to edit, as a data URL (e.g. data:image/png;base64,...).
        instruction: What to change (e.g. "Add a sun in the sky", "Remove the lion").

    Returns:
        The edited image as a data URL, or an error message string.
    """
    api_key = os.environ.get(OPENROUTER_API_KEY_ENV)
    if not api_key:
        return "Image editing is not configured: OPENROUTER_API_KEY is not set."

    defaults = await DefaultModels.get_instance()
    model_id = getattr(defaults, "default_image_model", None) if defaults else None
    if not model_id:
        return "No default image model is set. Image editing uses the same model as generation (Models → Default Model Assignments → Image Generation Model)."

    try:
        model_record = await Model.get(model_id)
    except Exception as e:
        logger.warning(f"Failed to load image model {model_id}: {e}")
        return f"Could not load the selected image model: {model_id}."

    if model_record.provider.lower() != "openrouter":
        return "Image editing is only supported with an OpenRouter model as the default image model."

    model_name = model_record.name
    # Models that support image-in + image-out (e.g. Gemini) need modalities ["image", "text"]
    model_lower = (model_name or "").lower()
    if "flux" in model_lower and "fill" not in model_lower:
        # Flux text-to-image often doesn't accept image input; prefer dual modality
        modalities = ["image", "text"]
    else:
        modalities = ["image", "text"]

    # Multimodal message: instruction first, then image (per OpenRouter recommendation)
    user_content = [
        {"type": "text", "text": f"Edit this image according to the following instruction. Output only the edited image.\n\nInstruction: {instruction}"},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": user_content}],
        "modalities": modalities,
    }

    logger.info(
        f"[Image edit] OpenRouter: model {model_name!r}, instruction length {len(instruction)}"
    )
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
        return "No response from image model. The model may not support image editing (image input + image output). Try a model like Gemini 2.5 Flash Image."

    message = choices[0].get("message", {})
    images = message.get("images") or []

    if not images:
        text = message.get("content", "")
        return text or "The model did not return an edited image. Some models only generate from text; use 'edit by re-prompt' or set an image-editing capable model (e.g. Gemini 2.5 Flash Image)."

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
