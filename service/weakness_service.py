"""Orquestación de negocio. Depende sólo de ports -- se testea con fakes,
sin SQLite ni rapidfuzz reales."""
from __future__ import annotations

from domain.exceptions import PokemonNotFoundError
from domain.pokemon import AbilityCaveat, WeaknessReport
from ports.name_matcher import NameMatcher
from ports.pokemon_repository import PokemonRepository

ABILITIES_MODES = ("canonical", "randomized", "off")


class WeaknessService:
    def __init__(
        self,
        repository: PokemonRepository,
        matcher: NameMatcher,
        generation: int,
        abilities_mode: str = "canonical",
    ) -> None:
        if abilities_mode not in ABILITIES_MODES:
            raise ValueError(f"abilities_mode inválido: {abilities_mode!r}")
        self._repository = repository
        self._matcher = matcher
        self.generation = generation
        self.abilities_mode = abilities_mode

    def get_report(self, query: str) -> WeaknessReport:
        candidates = self._repository.all_names()
        matched_name = self._matcher.match(query, candidates)
        if matched_name is None:
            raise PokemonNotFoundError(query)

        pokemon = self._repository.get_pokemon(matched_name, self.generation)
        if pokemon is None:
            raise PokemonNotFoundError(query)

        weaknesses = self._repository.get_weaknesses(pokemon.id, self.generation)

        ability_caveats: tuple[AbilityCaveat, ...] = ()
        if self.abilities_mode == "canonical":
            ability_caveats = self._repository.get_ability_caveats(pokemon.id, self.generation)

        return WeaknessReport(pokemon=pokemon, weaknesses=weaknesses, ability_caveats=ability_caveats)

    def get_ability_info(self, ability_query: str) -> AbilityCaveat | None:
        return self._repository.get_ability_effect(ability_query)
