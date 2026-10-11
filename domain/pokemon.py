"""Entidades de dominio. Sin dependencias externas (ni sqlite3, ni requests).

`WeaknessReport` no es una entidad "pura" en sentido estricto -- es el modelo
de respuesta que consumen los notifiers (consola, y a futuro overlay/TTS).
Se eligió como agregado único por simplicidad a esta escala; ver Apéndice C
del plan para la discusión completa del tradeoff.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Weakness:
    type_slug: str
    type_name_es: str
    multiplier: float


@dataclass(frozen=True)
class AbilityCaveat:
    """Advertencia informativa sobre una habilidad -- NUNCA ajusta el
    multiplicador de `Weakness`. Es un tipo separado a propósito: así es
    imposible que una habilidad modifique una debilidad por accidente (ver
    decisión de randomlockes, sección 2 del plan)."""

    ability_slug: str
    display_name: str
    is_hidden: bool
    effect_note_es: str | None  # None si la habilidad no está en la tabla curada
    is_approx: bool = False


@dataclass(frozen=True)
class Pokemon:
    id: int
    name: str  # slug, ej. 'charizard'
    generation: int
    types: tuple[str, ...]  # slugs, ej. ('fire', 'flying')
    type_names_es: tuple[str, ...]  # ej. ('Fuego', 'Volador')


@dataclass(frozen=True)
class WeaknessReport:
    pokemon: Pokemon
    weaknesses: tuple[Weakness, ...]  # sólo multiplier > 1, orden descendente
    ability_caveats: tuple[AbilityCaveat, ...]  # vacío si abilities.mode != 'canonical'
