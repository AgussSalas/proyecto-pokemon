from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from adapters.repository.sqlite_pokemon_repository import SqlitePokemonRepository
from scripts.build_db import SCHEMA


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """DB temporal sembrada a mano con dos especies ficticias, para no
    depender de data/pokedex.db (que requiere haber corrido el ETL)."""
    path = tmp_path / "test.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    conn.executemany("INSERT INTO pokemon VALUES (?, ?, ?)", [
        (1, "testmon", 1),
        (2, "latemon", 5),  # sólo existe desde gen 5
    ])
    conn.executemany("INSERT INTO type_names VALUES (?, ?)", [
        ("fire", "Fuego"), ("water", "Agua"), ("grass", "Planta"),
    ])
    conn.executemany("INSERT INTO pokemon_types VALUES (?, ?, ?, ?)", [
        (1, 1, 1, "fire"),
        (1, 3, 1, "fire"),  # testmon cambia de tipo en gen3 en este fixture
        (1, 3, 2, "water"),
        (2, 5, 1, "grass"),
    ])
    conn.executemany("INSERT INTO weaknesses VALUES (?, ?, ?, ?)", [
        (1, 1, "water", 2.0),
        (1, 3, "grass", 2.0),
        (2, 5, "fire", 2.0),
    ])
    conn.executemany("INSERT INTO abilities VALUES (?, ?, ?, ?, ?)", [
        (1, 1, "blaze", 0, 1),
        (1, 1, "flash-fire", 1, 2),
    ])
    conn.executemany("INSERT INTO ability_type_effects VALUES (?, ?, ?, ?, ?, ?)", [
        ("flash-fire", "fire", "immune", None, "Mar Llamas: inmune a Fuego", 0),
    ])
    conn.commit()
    conn.close()
    return path


def test_all_names_returns_every_species(db_path: Path):
    repo = SqlitePokemonRepository(db_path)
    assert repo.all_names() == ("latemon", "testmon")


def test_get_pokemon_returns_types_for_the_requested_generation(db_path: Path):
    repo = SqlitePokemonRepository(db_path)
    gen1 = repo.get_pokemon("testmon", 1)
    assert gen1 is not None
    assert gen1.types == ("fire",)

    gen3 = repo.get_pokemon("testmon", 3)
    assert gen3 is not None
    assert gen3.types == ("fire", "water")
    assert gen3.type_names_es == ("Fuego", "Agua")


def test_get_pokemon_returns_none_before_species_introduced(db_path: Path):
    repo = SqlitePokemonRepository(db_path)
    assert repo.get_pokemon("latemon", 3) is None
    assert repo.get_pokemon("latemon", 5) is not None


def test_get_pokemon_returns_none_for_unknown_name(db_path: Path):
    repo = SqlitePokemonRepository(db_path)
    assert repo.get_pokemon("no-existe", 1) is None


def test_get_weaknesses_filters_multiplier_and_orders_descending(db_path: Path):
    repo = SqlitePokemonRepository(db_path)
    weaknesses = repo.get_weaknesses(1, 3)
    assert weaknesses[0].type_slug == "grass"
    assert weaknesses[0].multiplier == 2.0


def test_get_ability_caveats_includes_curated_and_uncurated(db_path: Path):
    repo = SqlitePokemonRepository(db_path)
    caveats = repo.get_ability_caveats(1, 1)
    assert len(caveats) == 2

    blaze = next(c for c in caveats if c.ability_slug == "blaze")
    assert blaze.effect_note_es is None
    assert blaze.display_name == "Blaze"
    assert blaze.is_hidden is False

    flash_fire = next(c for c in caveats if c.ability_slug == "flash-fire")
    assert flash_fire.effect_note_es == "Mar Llamas: inmune a Fuego"
    assert flash_fire.is_hidden is True


def test_get_ability_effect_by_name(db_path: Path):
    repo = SqlitePokemonRepository(db_path)
    effect = repo.get_ability_effect("flash-fire")
    assert effect is not None
    assert effect.effect_note_es == "Mar Llamas: inmune a Fuego"


def test_get_ability_effect_returns_none_for_unknown(db_path: Path):
    repo = SqlitePokemonRepository(db_path)
    assert repo.get_ability_effect("no-existe") is None
