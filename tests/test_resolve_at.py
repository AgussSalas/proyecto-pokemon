"""Tests de la parte de mayor riesgo del proyecto: la reconstrucción
histórica (Apéndice E del plan). Usan como fixtures los datos REALES de
Fantasma y Fuego/Hielo que se verificaron contra PokeAPI y Bulbapedia
durante el diseño -- no datos inventados -- para que una regresión acá se
note enseguida.
"""
from __future__ import annotations

import pytest

from scripts.build_db import TypeInfo, build_type_chart, resolve_at, self_check_type_chart

# Datos reales de /type/8/ (ghost), verificados contra PokeAPI.
GHOST_PAST = [
    (1, {
        "double_damage_from": ["ghost"], "half_damage_from": ["poison", "bug"],
        "no_damage_from": ["normal", "fighting"],
        "double_damage_to": ["ghost"], "half_damage_to": [],
        "no_damage_to": ["normal", "psychic"],
    }),
    (5, {
        "double_damage_from": ["ghost", "dark"], "half_damage_from": ["poison", "bug"],
        "no_damage_from": ["normal", "fighting"],
        "double_damage_to": ["ghost", "psychic"], "half_damage_to": ["dark", "steel"],
        "no_damage_to": ["normal"],
    }),
]
GHOST_CURRENT = {
    "double_damage_from": ["ghost", "dark"], "half_damage_from": ["poison", "bug"],
    "no_damage_from": ["normal", "fighting"],
    "double_damage_to": ["ghost", "psychic"], "half_damage_to": [],
    "no_damage_to": ["normal"],
}


def test_resolve_at_picks_smallest_past_generation_gte_target():
    # gen 3 está entre las entradas de gen1 y gen5 -> debe usar la de gen5,
    # NO la de gen1 (esa es la regla "más chica >= gen", no "más grande <= gen").
    result = resolve_at(GHOST_PAST, GHOST_CURRENT, gen=3)
    assert "psychic" in result["double_damage_to"]


def test_resolve_at_exact_generation_boundary_uses_that_entry():
    result = resolve_at(GHOST_PAST, GHOST_CURRENT, gen=1)
    assert result["no_damage_to"] == ["normal", "psychic"]


def test_resolve_at_falls_back_to_current_past_the_last_entry():
    result = resolve_at(GHOST_PAST, GHOST_CURRENT, gen=9)
    assert result is GHOST_CURRENT


def test_resolve_at_wrong_rule_would_fail_this_case():
    """Documenta el bug que se evita: con la regla intuitiva ('la entrada
    más grande <= gen') el resultado en gen 3 sería la de gen1 (x0 a
    Psíquico) en vez de la de gen5 (x2). Este test falla si alguien
    reintroduce esa regla por accidente."""
    wrong_rule_result = max((g, v) for g, v in GHOST_PAST if g <= 3)[1]
    correct_result = resolve_at(GHOST_PAST, GHOST_CURRENT, gen=3)
    assert wrong_rule_result != correct_result


def _make_type(name: str, gen_introduced: int, current: dict, past: list[tuple[int, dict]]) -> TypeInfo:
    info = TypeInfo()
    info.name = name
    info.name_es = name
    info.gen_introduced = gen_introduced
    info.current_relations = current
    info.past_relations = sorted(past, key=lambda pair: pair[0])
    info.current_pokemon_slots = []
    return info


EMPTY_RELATIONS = {
    "double_damage_from": [], "half_damage_from": [], "no_damage_from": [],
    "double_damage_to": [], "half_damage_to": [], "no_damage_to": [],
}


def test_build_type_chart_reproduces_gen1_fire_ice_quirk():
    """Dato real verificado en Bulbapedia: en Gen 1, Fuego NO resistía
    Hielo (la resistencia se agregó después). fire.past_relations codifica
    exactamente eso: en gen1, half_damage_from no incluye 'ice'."""
    fire = _make_type(
        "fire", gen_introduced=1,
        current={**EMPTY_RELATIONS, "half_damage_from": ["ice"]},
        past=[(1, {**EMPTY_RELATIONS, "half_damage_from": []})],
    )
    ice = _make_type("ice", gen_introduced=1, current=EMPTY_RELATIONS, past=[])
    types = {"fire": fire, "ice": ice}

    chart, _ = build_type_chart(types)

    assert chart[1][("ice", "fire")] == 1.0  # gen1: neutral, sin resistencia
    assert chart[2][("ice", "fire")] == 0.5  # gen2 en adelante: resiste


def test_build_type_chart_excludes_types_not_yet_introduced():
    fire = _make_type("fire", gen_introduced=1, current=EMPTY_RELATIONS, past=[])
    fairy = _make_type("fairy", gen_introduced=6, current=EMPTY_RELATIONS, past=[])
    types = {"fire": fire, "fairy": fairy}

    chart, _ = build_type_chart(types)

    assert ("fire", "fairy") not in chart[1]
    assert ("fairy", "fire") not in chart[1]
    assert ("fire", "fairy") in chart[6]


def test_build_type_chart_warns_on_from_to_mismatch(capsys):
    # water dice que fire le hace x2 (double_damage_from), pero fire dice
    # que a water le hace x1 (double_damage_to vacío) -- inconsistencia.
    water = _make_type("water", 1, {**EMPTY_RELATIONS, "double_damage_from": ["fire"]}, [])
    fire = _make_type("fire", 1, EMPTY_RELATIONS, [])
    build_type_chart({"water": water, "fire": fire})
    captured = capsys.readouterr()
    assert "inconsistencias" in captured.err


def test_self_check_type_chart_passes_with_correct_golden_values():
    chart = {
        1: {("ghost", "psychic"): 0.0},
        3: {("ghost", "psychic"): 2.0, ("fighting", "steel"): 2.0},
        5: {("ghost", "steel"): 0.5},
        6: {("ghost", "steel"): 1.0},
        9: {("ghost", "psychic"): 2.0},
    }
    self_check_type_chart(chart)  # no debe lanzar


def test_self_check_type_chart_fails_with_wrong_value():
    chart = {
        1: {("ghost", "psychic"): 2.0},  # incorrecto, debería ser 0.0
        3: {("ghost", "psychic"): 2.0, ("fighting", "steel"): 2.0},
        5: {("ghost", "steel"): 0.5},
        6: {("ghost", "steel"): 1.0},
        9: {("ghost", "psychic"): 2.0},
    }
    with pytest.raises(SystemExit):
        self_check_type_chart(chart)
