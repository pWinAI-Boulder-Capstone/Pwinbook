from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx


class WebSearchError(RuntimeError):
    pass


async def tavily_search(query: str, *, max_results: int = 5) -> List[Dict[str, Any]]:
    """Search the public web via Tavily.

    Requires env var TAVILY_API_KEY.
    Returns a list of results with title/url/content.
    """

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise WebSearchError("TAVILY_API_KEY is not set")

    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post("https://api.tavily.com/search", json=payload)
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results") or []
    cleaned: List[Dict[str, Any]] = []
    for r in results[:max_results]:
        if not isinstance(r, dict):
            continue
        cleaned.append(
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "content": r.get("content"),
                "score": r.get("score"),
            }
        )
    return cleaned
