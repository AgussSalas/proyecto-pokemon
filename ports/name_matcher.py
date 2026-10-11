"""Port: resolución difusa de un nombre dicho/tipeado contra los nombres
conocidos. Separado del service a propósito -- en la iteración 2 la calidad
del match contra lo que transcribe Whisper va a ser el problema difícil, y
conviene poder cambiar de estrategia (fonética en español vs. Levenshtein)
sin tocar `WeaknessService`. Ver sección 3 del plan.
"""
from __future__ import annotations

from typing import Protocol


class NameMatcher(Protocol):
    def match(self, query: str, candidates: tuple[str, ...]) -> str | None:
        """Devuelve el mejor candidato de `candidates` para `query`, o None
        si ninguno supera el umbral de confianza del adapter."""
        ...
