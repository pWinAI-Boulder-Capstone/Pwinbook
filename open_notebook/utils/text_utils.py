"""
Text utilities for Open Notebook.
Extracted from main utils to avoid circular imports.
"""

import re
import unicodedata
from typing import Tuple

from langchain_text_splitters import RecursiveCharacterTextSplitter

from .token_utils import token_count

# Pattern for matching thinking content in AI responses (<think> and <thinking>)
THINK_PATTERN = re.compile(r"<think(?:ing)?>(.*?)</think(?:ing)?>", re.DOTALL)

# Pattern for stripping markdown code fences (```json ... ``` or ``` ... ```)
CODE_FENCE_PATTERN = re.compile(r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def split_text(txt: str, chunk_size=500):
    """
    Split the input text into chunks.

    Args:
        txt (str): The input text to be split.
        chunk_size (int): The size of each chunk. Default is 500.

    Returns:
        list: A list of text chunks.
    """
    overlap = int(chunk_size * 0.15)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        length_function=token_count,
        separators=[
            "\n\n",
            "\n",
            ".",
            ",",
            " ",
            "\u200b",  # Zero-width space
            "\uff0c",  # Fullwidth comma
            "\u3001",  # Ideographic comma
            "\uff0e",  # Fullwidth full stop
            "\u3002",  # Ideographic full stop
            "",
        ],
    )
    return text_splitter.split_text(txt)


def remove_non_ascii(text: str) -> str:
    """Remove non-ASCII characters from text."""
    return re.sub(r"[^\x00-\x7F]+", "", text)


def remove_non_printable(text: str) -> str:
    """Remove non-printable characters from text."""
    # Replace any special Unicode whitespace characters with a regular space
    text = re.sub(r"[\u2000-\u200B\u202F\u205F\u3000]", " ", text)

    # Replace unusual line terminators with a single newline
    text = re.sub(r"[\u2028\u2029\r]", "\n", text)

    # Remove control characters, except newlines and tabs
    text = "".join(
        char for char in text if unicodedata.category(char)[0] != "C" or char in "\n\t"
    )

    # Replace non-breaking spaces with regular spaces
    text = text.replace("\xa0", " ").strip()

    # Keep letters (including accented ones), numbers, spaces, newlines, tabs, and basic punctuation
    return re.sub(r"[^\w\s.,!?\-\n\t]", "", text, flags=re.UNICODE)


def parse_thinking_content(content: str) -> Tuple[str, str]:
    """
    Parse message content to extract thinking content from <think> tags.

    Args:
        content (str): The original message content

    Returns:
        Tuple[str, str]: (thinking_content, cleaned_content)
            - thinking_content: Content from within <think> tags
            - cleaned_content: Original content with <think> blocks removed

    Example:
        >>> content = "<think>Let me analyze this</think>Here's my answer"
        >>> thinking, cleaned = parse_thinking_content(content)
        >>> print(thinking)
        "Let me analyze this"
        >>> print(cleaned)
        "Here's my answer"
    """
    # Input validation
    if not isinstance(content, str):
        return "", str(content) if content is not None else ""

    # Limit processing for very large content (100KB limit)
    if len(content) > 100000:
        return "", content

    # Find all thinking blocks
    thinking_matches = THINK_PATTERN.findall(content)

    if not thinking_matches:
        return "", content

    # Join all thinking content with double newlines
    thinking_content = "\n\n".join(match.strip() for match in thinking_matches)

    # Remove all <think>...</think> blocks from the original content
    cleaned_content = THINK_PATTERN.sub("", content)

    # Clean up extra whitespace
    cleaned_content = re.sub(r"\n\s*\n\s*\n", "\n\n", cleaned_content).strip()

    return thinking_content, cleaned_content


def strip_code_fences(content: str) -> str:
    """
    Remove markdown code fences (```json ... ``` or ``` ... ```) from AI output.

    Many models wrap JSON responses in code blocks despite being told not to.
    This strips the fences so the raw JSON can be parsed.

    Args:
        content (str): Text that may be wrapped in code fences

    Returns:
        str: Content with code fences removed, or original if none found
    """
    if not content:
        return content
    match = CODE_FENCE_PATTERN.match(content)
    if match:
        return match.group(1).strip()
    return content


def clean_thinking_content(content: str) -> str:
    """
    Remove thinking content and code fences from AI responses.

    This is a convenience function for cases where you only need the cleaned
    content and don't need access to the thinking process.

    Args:
        content (str): The original message content with potential <think> tags

    Returns:
        str: Content with <think> blocks and code fences removed

    Example:
        >>> content = "<think>Let me think...</think>Here's the answer"
        >>> clean_thinking_content(content)
        "Here's the answer"
    """
    _, cleaned_content = parse_thinking_content(content)
    cleaned_content = strip_code_fences(cleaned_content)
    # If the cleaned content has a text preamble before JSON, try to extract
    # the JSON object/array (common with models that narrate before responding)
    stripped = cleaned_content.strip()
    if stripped and not stripped.startswith(("{", "[")):
        first_brace = stripped.find("{")
        first_bracket = stripped.find("[")
        candidates = [i for i in (first_brace, first_bracket) if i > 0]
        if candidates:
            return stripped[min(candidates):]
    return cleaned_content
