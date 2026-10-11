"""Adapter: fuzzy matching con rapidfuzz (distancia de Levenshtein
normalizada). Absorbe errores de tipeo ('charizar', 'pikachú') y, en la
iteración 2, imprecisiones de Whisper."""
from __future__ import annotations

from rapidfuzz import fuzz, process


class RapidFuzzNameMatcher:
    def __init__(self, threshold: float = 70.0) -> None:
        self._threshold = threshold

    def match(self, query: str, candidates: tuple[str, ...]) -> str | None:
        if not query.strip() or not candidates:
            return None
        result = process.extractOne(
            query.strip().lower(), candidates, scorer=fuzz.WRatio
        )
        if result is None:
            return None
        name, score, _ = result
        return name if score >= self._threshold else None
