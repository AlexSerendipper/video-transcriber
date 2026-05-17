from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


SENTENCE_END_RE = re.compile(r"[\u3002\uff01\uff1f!?;\uff1b]+[\u201d\u2019\"')\uff09\u3011]*$")
PUNCTUATION_RE = re.compile(r"[\u3002\uff0c\uff01\uff1f\uff1b\uff1a\u3001,.!?;:]")
COMMA_HINTS = (
    "\u6240\u4ee5",
    "\u56e0\u4e3a",
    "\u4f46\u662f",
    "\u7136\u540e",
    "\u800c\u4e14",
    "\u5176\u5b9e",
    "\u9996\u5148",
    "\u5176\u6b21",
    "\u6700\u540e",
    "\u4e5f\u5c31\u662f",
    "\u6362\u53e5\u8bdd\u8bf4",
    "\u90a3\u4e48",
    "\u8fd9\u6837",
)
QUESTION_HINTS = (
    "\u5417",
    "\u5462",
    "\u4ec0\u4e48",
    "\u4e3a\u4ec0\u4e48",
    "\u600e\u4e48",
    "\u5982\u4f55",
    "\u662f\u4e0d\u662f",
)


@dataclass(frozen=True)
class RawSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TextBlock:
    start: float
    end: float
    text: str


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def restore_light_punctuation(text: str) -> str:
    text = normalize_text(text)
    if not text:
        return text

    punctuation_count = len(PUNCTUATION_RE.findall(text))
    if punctuation_count >= max(1, len(text) // 80):
        return text

    text = _insert_commas(text)
    if not SENTENCE_END_RE.search(text):
        text += "\uff1f" if _looks_like_question(text) else "\u3002"
    return text


def _insert_commas(text: str) -> str:
    for hint in COMMA_HINTS:
        text = text.replace(hint, f"\uff0c{hint}")
    text = re.sub(r"\uff0c+", "\uff0c", text).strip("\uff0c")
    return text


def _looks_like_question(text: str) -> bool:
    return any(hint in text[-20:] for hint in QUESTION_HINTS)


def merge_segments(
    segments: Iterable[RawSegment],
    max_chars: int = 90,
    min_chars: int = 28,
    pause_seconds: float = 1.35,
) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    current: list[str] = []
    start: float | None = None
    end = 0.0
    previous_end: float | None = None

    def flush() -> None:
        nonlocal current, start, end
        text = restore_light_punctuation("".join(current))
        if text and start is not None:
            blocks.append(TextBlock(start=round(start, 2), end=round(end, 2), text=text))
        current = []
        start = None

    for item in segments:
        text = normalize_text(item.text)
        if not text:
            continue

        pause = previous_end is not None and item.start - previous_end >= pause_seconds
        current_text = normalize_text("".join(current))
        should_flush_before = bool(current) and pause and len(current_text) >= min_chars
        if should_flush_before:
            flush()

        if start is None:
            start = item.start
        current.append(text)
        end = item.end
        previous_end = item.end

        merged_text = normalize_text("".join(current))
        ends_sentence = bool(SENTENCE_END_RE.search(merged_text))
        long_enough_sentence = ends_sentence and len(merged_text) >= min_chars
        too_long = len(merged_text) >= max_chars
        if long_enough_sentence or too_long:
            flush()

    flush()
    return blocks
