"""Port para la iteración 2 (voz). Definido ahora para que la arquitectura
lo soporte sin refactor grande; sin adapter todavía -- `WhisperTranscriber`
se escribe cuando arranque esa iteración."""
from __future__ import annotations

from typing import Protocol


class Transcriber(Protocol):
    def transcribe(self, audio: bytes) -> str:
        """`audio`: PCM mono 16kHz. Devuelve el texto transcripto (puede
        estar vacío si no se detectó habla)."""
        ...
