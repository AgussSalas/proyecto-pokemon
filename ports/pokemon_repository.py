"""Port: acceso de sólo lectura a los datos de Pokémon precalculados.

Expresa necesidades en términos del dominio, no de SQLite. El
`SqlitePokemonRepository` es la única implementación de este iteración;
los tests del service usan un fake en memoria.
"""
from __future__ import annotations

from typing import Protocol

from domain.pokemon import AbilityCaveat, Pokemon, Weakness


class PokemonRepository(Protocol):
    def all_names(self) -> tuple[str, ...]:
        """Todos los nombres de especie conocidos, para que el NameMatcher
        tenga contra qué matchear."""
        ...

    def get_pokemon(self, name: str, generation: int) -> Pokemon | None:
        """None si el nombre no existe, o si la especie todavía no había
        sido introducida en `generation`."""
        ...

    def get_weaknesses(self, pokemon_id: int, generation: int) -> tuple[Weakness, ...]:
        """Sólo multiplicador > 1, ordenado descendente."""
        ...

    def get_ability_caveats(self, pokemon_id: int, generation: int) -> tuple[AbilityCaveat, ...]:
        """Las habilidades reales de la especie en esa generación, cada una
        con su efecto curado si existe (`effect_note_es` es None si no)."""
        ...

    def get_ability_effect(self, ability_name: str) -> AbilityCaveat | None:
        """Consulta suelta de una habilidad por nombre (comando `hab`), sin
        atarla a ningún Pokémon. None si el nombre no matchea ninguna
        habilidad conocida."""
        ...
