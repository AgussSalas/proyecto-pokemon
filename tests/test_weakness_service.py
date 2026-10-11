from __future__ import annotations

import pytest

from domain.exceptions import PokemonNotFoundError
from domain.pokemon import AbilityCaveat, Pokemon, Weakness
from service.weakness_service import WeaknessService
from tests.fakes import FakeNameMatcher, FakePokemonRepository

CHARIZARD = Pokemon(
    id=6, name="charizard", generation=3,
    types=("fire", "flying"), type_names_es=("Fuego", "Volador"),
)
CHARIZARD_WEAKNESSES = (
    Weakness("rock", "Roca", 4.0),
    Weakness("water", "Agua", 2.0),
    Weakness("electric", "Eléctrico", 2.0),
)
BLAZE = AbilityCaveat("blaze", "Blaze", is_hidden=False, effect_note_es=None)


def make_service(abilities_mode: str = "canonical") -> WeaknessService:
    repository = FakePokemonRepository(
        pokemons={("charizard", 3): CHARIZARD},
        weaknesses={(6, 3): CHARIZARD_WEAKNESSES},
        ability_caveats={(6, 3): (BLAZE,)},
        ability_effects={"levitate": AbilityCaveat("levitate", "Levitate", False, "inmune a Tierra")},
        names=("charizard", "pikachu"),
    )
    matcher = FakeNameMatcher({"charizar": "charizard", "charizard": "charizard"})
    return WeaknessService(repository, matcher, generation=3, abilities_mode=abilities_mode)


def test_get_report_resolves_fuzzy_match_and_returns_weaknesses():
    service = make_service()
    report = service.get_report("charizar")
    assert report.pokemon.name == "charizard"
    assert report.weaknesses == CHARIZARD_WEAKNESSES


def test_get_report_includes_ability_caveats_in_canonical_mode():
    service = make_service(abilities_mode="canonical")
    report = service.get_report("charizard")
    assert report.ability_caveats == (BLAZE,)


def test_get_report_hides_ability_caveats_in_randomized_mode():
    service = make_service(abilities_mode="randomized")
    report = service.get_report("charizard")
    assert report.ability_caveats == ()


def test_get_report_hides_ability_caveats_in_off_mode():
    service = make_service(abilities_mode="off")
    report = service.get_report("charizard")
    assert report.ability_caveats == ()


def test_get_report_raises_when_matcher_finds_nothing():
    service = make_service()
    with pytest.raises(PokemonNotFoundError):
        service.get_report("xyzzy")


def test_get_report_raises_when_species_not_introduced_yet():
    """El matcher puede devolver un nombre válido cuya especie no existía
    en la generación activa -- el repo devuelve None y el service debe
    traducirlo a PokemonNotFoundError, no propagar un None silencioso."""
    repository = FakePokemonRepository(
        pokemons={},  # sableye no está para generation=1
        names=("sableye",),
    )
    matcher = FakeNameMatcher({"sableye": "sableye"})
    service = WeaknessService(repository, matcher, generation=1)
    with pytest.raises(PokemonNotFoundError):
        service.get_report("sableye")


def test_get_ability_info_delegates_to_repository():
    service = make_service()
    ability = service.get_ability_info("levitate")
    assert ability is not None
    assert ability.effect_note_es == "inmune a Tierra"


def test_get_ability_info_returns_none_for_unknown_ability():
    service = make_service()
    assert service.get_ability_info("no-existe") is None


def test_invalid_abilities_mode_raises_at_construction():
    repository = FakePokemonRepository()
    matcher = FakeNameMatcher()
    with pytest.raises(ValueError):
        WeaknessService(repository, matcher, generation=3, abilities_mode="bogus")


def test_generation_can_be_changed_after_construction():
    service = make_service()
    assert service.generation == 3
    service.generation = 1
    assert service.generation == 1
