"""Port para la iteración 4 (OCR/sprite matching). Definido ahora para que
la arquitectura lo soporte sin refactor grande; sin adapter todavía, tal
como pide el prompt original."""
from __future__ import annotations

from typing import Protocol


class ScreenReader(Protocol):
    def read_region(self, region: tuple[int, int, int, int]) -> str:
        """`region`: (x, y, width, height) en píxeles de pantalla. Devuelve
        el texto/nombre detectado, o cadena vacía si no se reconoció nada."""
        ...
