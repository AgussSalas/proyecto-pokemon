"""Fakes de los ports, para testear el service sin SQLite ni rapidfuzz
reales -- exactamente lo que pedía el prompt original."""
from __future__ import annotations

from domain.pokemon import AbilityCaveat, Pokemon, Weakness


class FakePokemonRepository:
    def __init__(
        self,
        pokemons: dict[tuple[str, int], Pokemon] | None = None,
        weaknesses: dict[tuple[int, int], tuple[Weakness, ...]] | None = None,
        ability_caveats: dict[tuple[int, int], tuple[AbilityCaveat, ...]] | None = None,
        ability_effects: dict[str, AbilityCaveat] | None = None,
        names: tuple[str, ...] = (),
    ) -> None:
        self._pokemons = pokemons or {}
        self._weaknesses = weaknesses or {}
        self._ability_caveats = ability_caveats or {}
        self._ability_effects = ability_effects or {}
        self._names = names

    def all_names(self) -> tuple[str, ...]:
        return self._names

    def get_pokemon(self, name: str, generation: int) -> Pokemon | None:
        return self._pokemons.get((name, generation))

    def get_weaknesses(self, pokemon_id: int, generation: int) -> tuple[Weakness, ...]:
        return self._weaknesses.get((pokemon_id, generation), ())

    def get_ability_caveats(self, pokemon_id: int, generation: int) -> tuple[AbilityCaveat, ...]:
        return self._ability_caveats.get((pokemon_id, generation), ())

    def get_ability_effect(self, ability_name: str) -> AbilityCaveat | None:
        return self._ability_effects.get(ability_name)


class FakeNameMatcher:
    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping = mapping or {}

    def match(self, query: str, candidates: tuple[str, ...]) -> str | None:
        return self._mapping.get(query)
