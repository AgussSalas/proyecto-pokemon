"""ETL: PokeAPI -> data/pokedex.db.

Construye una tabla de tipos y debilidades PRECALCULADAS por generación, de
forma que el runtime nunca llama a PokeAPI ni hace cómputo (ver decisiones
de arquitectura del prompt original).

La parte delicada es la reconstrucción histórica (tipos y tabla de
efectividades cambian entre generaciones). Ver Apéndice E del plan
(`C:\\Users\\agust\\.claude\\plans\\quiero-que-hagamos-un-snazzy-dijkstra.md`)
para la justificación completa de `resolve_at()`.

Uso:
    python scripts/build_db.py                  # build completo (~1050 requests)
    python scripts/build_db.py --skip-abilities  # build rápido (27 requests),
                                                  # usa tipos/habilidades "actuales"
                                                  # para todas las generaciones -
                                                  # sólo para smoke test rápido,
                                                  # NO reproduce cambios históricos
                                                  # de tipo (Magnemite, Clefairy...).
    python scripts/build_db.py --dump-chart 3    # inspecciona la tabla de tipos
                                                  # de una generación ya construida
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.ability_effects import ABILITY_TYPE_EFFECTS  # noqa: E402

CACHE_DIR = ROOT / "data" / ".cache"
DB_PATH = ROOT / "data" / "pokedex.db"
API_BASE = "https://pokeapi.co/api/v2"
REQUEST_DELAY = 0.05
NUM_GENERATIONS = 9
NUM_TYPES = 18

SCHEMA = """
CREATE TABLE pokemon (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    gen_introduced INTEGER NOT NULL
);

CREATE TABLE pokemon_types (
    pokemon_id INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    slot       INTEGER NOT NULL,
    type       TEXT NOT NULL,
    PRIMARY KEY (pokemon_id, generation, slot)
);

CREATE TABLE weaknesses (
    pokemon_id INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    weak_type  TEXT NOT NULL,
    multiplier REAL NOT NULL,
    PRIMARY KEY (pokemon_id, generation, weak_type)
);

CREATE TABLE abilities (
    pokemon_id INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    ability    TEXT NOT NULL,
    is_hidden  INTEGER NOT NULL,
    slot       INTEGER NOT NULL,
    PRIMARY KEY (pokemon_id, generation, slot)
);

CREATE TABLE type_names (
    type    TEXT PRIMARY KEY,
    name_es TEXT NOT NULL
);

CREATE TABLE type_chart (
    generation     INTEGER NOT NULL,
    attacking_type TEXT NOT NULL,
    defending_type TEXT NOT NULL,
    multiplier     REAL NOT NULL,
    PRIMARY KEY (generation, attacking_type, defending_type)
);

CREATE TABLE ability_type_effects (
    ability       TEXT NOT NULL,
    affected_type TEXT,
    kind          TEXT NOT NULL,
    factor        REAL,
    note_es       TEXT NOT NULL,
    is_approx     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ability, affected_type, kind)
);

CREATE INDEX idx_pokemon_name ON pokemon(name);
CREATE INDEX idx_pokemon_types_lookup ON pokemon_types(pokemon_id, generation);
CREATE INDEX idx_weaknesses_lookup ON weaknesses(pokemon_id, generation);
CREATE INDEX idx_abilities_lookup ON abilities(pokemon_id, generation);
"""

session = requests.Session()
session.headers.update({
    "User-Agent": "pokemon-assistant-etl/0.1 (script personal, no comercial)",
})


# --------------------------------------------------------------------------
# Capa HTTP con caché en disco
# --------------------------------------------------------------------------

def fetch(path: str) -> dict[str, Any]:
    """GET contra PokeAPI con caché en disco por endpoint y reintentos.

    `path` es relativo al base, ej. 'type/6/'. La fair-use policy de PokeAPI
    pide cachear localmente todo lo que se pida; este caché hace que
    re-correr el ETL sea gratis salvo la primera vez.
    """
    cache_file = CACHE_DIR / (re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_") + ".json")
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    url = f"{API_BASE}/{path}"
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data), encoding="utf-8")
            time.sleep(REQUEST_DELAY)
            return data
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"No se pudo obtener {url}") from last_error


def id_from_url(url: str) -> int:
    """'https://pokeapi.co/api/v2/pokemon-species/25/' -> 25"""
    match = re.search(r"/(\d+)/?$", url)
    if not match:
        raise ValueError(f"No se pudo extraer el id de {url}")
    return int(match.group(1))


# --------------------------------------------------------------------------
# Resolución histórica (Apéndice E del plan)
# --------------------------------------------------------------------------

def resolve_at(past_sorted: list[tuple[int, Any]], current: Any, gen: int) -> Any:
    """Devuelve el valor vigente en la generación `gen`.

    Convención de PokeAPI: una entrada past[g] valió 'hasta E INCLUYENDO la
    generación g'. La regla correcta es tomar la entrada con la generación
    MÁS CHICA que sea >= gen; si ninguna generación pasada alcanza esa cota,
    rige el valor actual (`current`).

    La regla intuitiva ("la entrada más grande <= gen", como se haría con
    cualquier otro dato histórico ordenado) da resultados incorrectos en
    generaciones intermedias — ver Apéndice E.1: falla el caso dorado
    Fantasma->Psíquico en generación 3 (debe dar x2, la intuitiva da x0).

    `past_sorted` debe venir ordenado ascendente por generación.
    """
    for gen_num, value in past_sorted:
        if gen_num >= gen:
            return value
    return current


# --------------------------------------------------------------------------
# Paso 1: generaciones -> mapeo de nombres y especie->gen_introduced
# --------------------------------------------------------------------------

def build_generations() -> tuple[dict[str, int], dict[str, int]]:
    """Devuelve (gen_name_to_num, species_gen_introduced).

    gen_name_to_num: {'generation-v': 5, ...} - se arma desde la propia API
    (campo `id` de /generation/{n}) para no parsear números romanos a mano.
    species_gen_introduced: {'magnemite': 1, ...} desde `pokemon_species` de
    cada generación.
    """
    gen_name_to_num: dict[str, int] = {}
    species_gen_introduced: dict[str, int] = {}
    for gen_num in range(1, NUM_GENERATIONS + 1):
        data = fetch(f"generation/{gen_num}/")
        gen_name_to_num[data["name"]] = data["id"]
        for species_ref in data["pokemon_species"]:
            species_gen_introduced[species_ref["name"]] = data["id"]
    return gen_name_to_num, species_gen_introduced


# --------------------------------------------------------------------------
# Paso 2: tipos -> nombres es, generación de introducción, damage_relations
#          actuales e históricas, y mapa de pokemon "actual" por tipo
# --------------------------------------------------------------------------

class TypeInfo:
    __slots__ = (
        "name", "name_es", "gen_introduced", "current_relations",
        "past_relations", "current_pokemon_slots",
    )

    def __init__(self) -> None:
        self.name: str = ""
        self.name_es: str = ""
        self.gen_introduced: int = 1
        self.current_relations: dict[str, list[str]] = {}
        self.past_relations: list[tuple[int, dict[str, list[str]]]] = []
        self.current_pokemon_slots: list[tuple[str, int]] = []


def build_types(gen_name_to_num: dict[str, int]) -> dict[str, TypeInfo]:
    types: dict[str, TypeInfo] = {}
    for type_id in range(1, NUM_TYPES + 1):
        data = fetch(f"type/{type_id}/")
        info = TypeInfo()
        info.name = data["name"]
        info.name_es = next(
            (n["name"] for n in data["names"] if n["language"]["name"] == "es"),
            data["name"],
        )
        info.gen_introduced = gen_name_to_num[data["generation"]["name"]]
        info.current_relations = {
            key: [t["name"] for t in data["damage_relations"][key]]
            for key in (
                "double_damage_from", "half_damage_from", "no_damage_from",
                "double_damage_to", "half_damage_to", "no_damage_to",
            )
        }
        past_entries = []
        for entry in data["past_damage_relations"]:
            gen_num = gen_name_to_num[entry["generation"]["name"]]
            relations = {
                key: [t["name"] for t in entry["damage_relations"][key]]
                for key in (
                    "double_damage_from", "half_damage_from", "no_damage_from",
                    "double_damage_to", "half_damage_to", "no_damage_to",
                )
            }
            past_entries.append((gen_num, relations))
        past_entries.sort(key=lambda pair: pair[0])
        info.past_relations = past_entries
        info.current_pokemon_slots = [
            (entry["pokemon"]["name"], entry["slot"]) for entry in data["pokemon"]
        ]
        types[info.name] = info
    return types


# --------------------------------------------------------------------------
# Paso 3: tabla de efectividades por generación, con validación cruzada
# --------------------------------------------------------------------------

def _multiplier_from(relations: dict[str, list[str]], attacking_type: str) -> float:
    if attacking_type in relations["no_damage_from"]:
        return 0.0
    if attacking_type in relations["half_damage_from"]:
        return 0.5
    if attacking_type in relations["double_damage_from"]:
        return 2.0
    return 1.0


def _multiplier_to(relations: dict[str, list[str]], defending_type: str) -> float:
    if defending_type in relations["no_damage_to"]:
        return 0.0
    if defending_type in relations["half_damage_to"]:
        return 0.5
    if defending_type in relations["double_damage_to"]:
        return 2.0
    return 1.0


def build_type_chart(
    types: dict[str, TypeInfo],
) -> tuple[dict[int, dict[tuple[str, str], float]], list[str]]:
    """chart[gen][(attacking, defending)] = multiplicador.

    Se construye dos veces por generación -- una vez desde la perspectiva de
    cada tipo defensor (*_damage_from) y otra desde cada tipo atacante
    (*_damage_to), que deberían coincidir siempre. La discrepancia, si la
    hay, se reporta como advertencia (Apéndice E.4, punto 3): es la
    validación cruzada gratis contra inconsistencias en la data histórica.
    """
    chart: dict[int, dict[tuple[str, str], float]] = {}
    mismatches: list[str] = []

    for gen in range(1, NUM_GENERATIONS + 1):
        existing = [t for t in types.values() if t.gen_introduced <= gen]
        gen_chart: dict[tuple[str, str], float] = {}
        for defending in existing:
            relations_from = resolve_at(defending.past_relations, defending.current_relations, gen)
            for attacking in existing:
                mult_from = _multiplier_from(relations_from, attacking.name)
                relations_to = resolve_at(attacking.past_relations, attacking.current_relations, gen)
                mult_to = _multiplier_to(relations_to, defending.name)
                if mult_from != mult_to:
                    mismatches.append(
                        f"gen {gen}: {attacking.name} -> {defending.name} "
                        f"(desde defensor={mult_from}, desde atacante={mult_to})"
                    )
                gen_chart[(attacking.name, defending.name)] = mult_from
        chart[gen] = gen_chart

    if mismatches:
        print(f"ADVERTENCIA: {len(mismatches)} inconsistencias en damage_relations históricas:", file=sys.stderr)
        for line in mismatches[:20]:
            print(f"  - {line}", file=sys.stderr)
        if len(mismatches) > 20:
            print(f"  ... y {len(mismatches) - 20} más", file=sys.stderr)

    type_names_by_id_order = [t.name for t in types.values()]
    return chart, type_names_by_id_order


def self_check_type_chart(chart: dict[int, dict[tuple[str, str], float]]) -> None:
    """Casos dorados del Apéndice E: si alguno falla, el resolvedor está mal
    y NO tiene sentido seguir construyendo la DB con datos incorrectos."""
    checks = [
        (1, "ghost", "psychic", 0.0, "Fantasma->Psíquico gen 1 (rareza histórica, no afecta)"),
        (3, "ghost", "psychic", 2.0, "Fantasma->Psíquico gen 3 (regla 'más chica >= gen')"),
        (9, "ghost", "psychic", 2.0, "Fantasma->Psíquico gen 9 (actual)"),
        (3, "fighting", "steel", 2.0, "Lucha->Acero gen 3 (Acero introducido en gen 2)"),
        (5, "ghost", "steel", 0.5, "Fantasma->Acero gen 5 (Acero resistía Fantasma hasta gen 5)"),
        (6, "ghost", "steel", 1.0, "Fantasma->Acero gen 6 (deja de resistir)"),
    ]
    failed = []
    for gen, attacking, defending, expected, label in checks:
        actual = chart[gen].get((attacking, defending))
        if actual != expected:
            failed.append(f"{label}: esperado x{expected}, obtenido x{actual}")
    if failed:
        print("ERROR: fallaron los casos dorados de resolve_at():", file=sys.stderr)
        for line in failed:
            print(f"  - {line}", file=sys.stderr)
        raise SystemExit(1)
    print(f"OK: {len(checks)} casos dorados de reconstrucción histórica verificados.")


# --------------------------------------------------------------------------
# Paso 4: especies base (id, name, gen_introduced)
# --------------------------------------------------------------------------

def build_species(gen_name_to_num: dict[str, int]) -> dict[str, dict[str, Any]]:
    """{'magnemite': {'id': 81, 'gen_introduced': 1}, ...}. Sólo formas base:
    la lista `pokemon_species` de cada generación no incluye variantes
    regionales ni megas, así que quedan excluidas sin filtrado adicional."""
    species: dict[str, dict[str, Any]] = {}
    for gen_num in range(1, NUM_GENERATIONS + 1):
        data = fetch(f"generation/{gen_num}/")
        for ref in data["pokemon_species"]:
            species[ref["name"]] = {
                "id": id_from_url(ref["url"]),
                "gen_introduced": gen_num,
            }
    return species


# --------------------------------------------------------------------------
# Paso 5 (modo rápido): tipos "actuales" por especie, desde type.pokemon
# --------------------------------------------------------------------------

def build_current_types_fallback(
    types: dict[str, TypeInfo], species: dict[str, dict[str, Any]]
) -> dict[str, list[tuple[int, str]]]:
    """{'charizard': [(1, 'fire'), (2, 'flying')], ...} usando el mapeo
    "actual" que trae cada /type/{id}.pokemon. Nombres que no matchean una
    especie base conocida (formas alternativas tipo 'raichu-alola') quedan
    excluidos naturalmente, sin necesitar un filtro aparte."""
    current_types: dict[str, list[tuple[int, str]]] = {}
    for type_info in types.values():
        for species_name, slot in type_info.current_pokemon_slots:
            if species_name in species:
                current_types.setdefault(species_name, []).append((slot, type_info.name))
    for species_name, slots in current_types.items():
        slots.sort()
    return current_types


# --------------------------------------------------------------------------
# Paso 6 (modo completo): past_types y abilities por especie
# --------------------------------------------------------------------------

def fetch_full_pokemon_data(
    species: dict[str, dict[str, Any]],
    gen_name_to_num: dict[str, int],
) -> tuple[dict[str, list[tuple[int, str]]], dict[str, list[tuple[int, list[tuple[int, str]]]]], dict[str, list[dict[str, Any]]]]:
    """Devuelve (current_types, past_types_sorted, abilities) por especie.

    Asume que el id de especie coincide con el id de la forma default en
    /pokemon/{id} -- cierto para la enorme mayoría; un puñado de casos raros
    con forma default no estándar quedan como imprecisión conocida y
    aceptada para esta iteración (no se paga el costo de ~1025 requests
    extra a /pokemon-species/{id} sólo para confirmar la default variety).
    """
    current_types: dict[str, list[tuple[int, str]]] = {}
    past_types: dict[str, list[tuple[int, list[tuple[int, str]]]]] = {}
    abilities: dict[str, list[dict[str, Any]]] = {}

    total = len(species)
    for i, (species_name, meta) in enumerate(species.items(), start=1):
        if i % 100 == 0 or i == total:
            print(f"  /pokemon/{{id}}: {i}/{total}", flush=True)
        data = fetch(f"pokemon/{meta['id']}/")

        current_types[species_name] = sorted(
            (t["slot"], t["type"]["name"]) for t in data["types"]
        )

        entries = []
        for past_entry in data.get("past_types", []):
            gen_num = gen_name_to_num[past_entry["generation"]["name"]]
            type_slots = sorted((t["slot"], t["type"]["name"]) for t in past_entry["types"])
            entries.append((gen_num, type_slots))
        entries.sort(key=lambda pair: pair[0])
        past_types[species_name] = entries

        abilities[species_name] = [
            {
                "name": a["ability"]["name"],
                "is_hidden": a["is_hidden"],
                "slot": a["slot"],
            }
            for a in data["abilities"]
        ]

    return current_types, past_types, abilities


# --------------------------------------------------------------------------
# Paso 7: combinar todo por (especie, generación) y calcular debilidades
# --------------------------------------------------------------------------

def build_rows(
    species: dict[str, dict[str, Any]],
    types: dict[str, TypeInfo],
    type_chart: dict[int, dict[tuple[str, str], float]],
    current_types: dict[str, list[tuple[int, str]]],
    past_types: dict[str, list[tuple[int, list[tuple[int, str]]]]] | None,
    abilities: dict[str, list[dict[str, Any]]] | None,
) -> tuple[list[tuple], list[tuple], list[tuple], list[tuple]]:
    """Devuelve filas listas para insertar: (pokemon, pokemon_types,
    weaknesses, abilities_rows).

    El rango de generaciones consultadas para cada especie arranca en su
    `gen_introduced` -- nunca se le pregunta al resolvedor por una
    generación anterior a que el Pokémon exista (Apéndice E.4, punto 5).
    """
    pokemon_rows = []
    type_rows = []
    weakness_rows = []
    ability_rows = []

    for species_name, meta in species.items():
        species_id = meta["id"]
        gen_introduced = meta["gen_introduced"]
        pokemon_rows.append((species_id, species_name, gen_introduced))

        species_past_types = past_types.get(species_name, []) if past_types else []
        species_current_types = current_types.get(species_name, [])
        species_abilities = abilities.get(species_name, []) if abilities else []

        for gen in range(gen_introduced, NUM_GENERATIONS + 1):
            gen_type_slots = resolve_at(species_past_types, species_current_types, gen)
            if not gen_type_slots:
                continue
            defending_type_names = [name for _, name in gen_type_slots]

            for slot, type_name in gen_type_slots:
                type_rows.append((species_id, gen, slot, type_name))

            existing_attacking_types = [t.name for t in types.values() if t.gen_introduced <= gen]
            gen_chart = type_chart[gen]
            for attacking_type in existing_attacking_types:
                multiplier = 1.0
                for defending_type in defending_type_names:
                    multiplier *= gen_chart.get((attacking_type, defending_type), 1.0)
                weakness_rows.append((species_id, gen, attacking_type, multiplier))

            for ability in species_abilities:
                ability_rows.append((species_id, gen, ability["name"], int(ability["is_hidden"]), ability["slot"]))

    return pokemon_rows, type_rows, weakness_rows, ability_rows


# --------------------------------------------------------------------------
# Escritura a SQLite
# --------------------------------------------------------------------------

def write_db(
    pokemon_rows: list[tuple],
    type_rows: list[tuple],
    weakness_rows: list[tuple],
    ability_rows: list[tuple],
    types: dict[str, TypeInfo],
    type_chart: dict[int, dict[tuple[str, str], float]],
) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)

        conn.executemany("INSERT INTO pokemon VALUES (?, ?, ?)", pokemon_rows)
        conn.executemany("INSERT INTO pokemon_types VALUES (?, ?, ?, ?)", type_rows)
        # de-duplicar por PK (especies con abilities/weaknesses duplicadas no deberían
        # existir, pero INSERT OR IGNORE es una red de seguridad barata)
        conn.executemany("INSERT OR IGNORE INTO weaknesses VALUES (?, ?, ?, ?)", weakness_rows)
        conn.executemany("INSERT OR IGNORE INTO abilities VALUES (?, ?, ?, ?, ?)", ability_rows)

        conn.executemany(
            "INSERT INTO type_names VALUES (?, ?)",
            [(t.name, t.name_es) for t in types.values()],
        )

        chart_rows = [
            (gen, attacking, defending, multiplier)
            for gen, gen_chart in type_chart.items()
            for (attacking, defending), multiplier in gen_chart.items()
        ]
        conn.executemany("INSERT INTO type_chart VALUES (?, ?, ?, ?)", chart_rows)

        conn.executemany("INSERT INTO ability_type_effects VALUES (?, ?, ?, ?, ?, ?)", ABILITY_TYPE_EFFECTS)

        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# --dump-chart: inspección legible de una generación ya construida
# --------------------------------------------------------------------------

def dump_chart(gen: int) -> None:
    if not DB_PATH.exists():
        print(f"No existe {DB_PATH}. Corré el build completo primero.", file=sys.stderr)
        raise SystemExit(1)

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT attacking_type, defending_type, multiplier FROM type_chart WHERE generation = ? ORDER BY defending_type, attacking_type",
            (gen,),
        ).fetchall()
        names = dict(conn.execute("SELECT type, name_es FROM type_names").fetchall())
    finally:
        conn.close()

    if not rows:
        print(f"No hay datos de type_chart para la generación {gen}.")
        return

    by_defending: dict[str, dict[str, float]] = {}
    for attacking, defending, multiplier in rows:
        by_defending.setdefault(defending, {})[attacking] = multiplier

    print(f"=== Tabla de tipos, generación {gen} ({len(by_defending)} tipos existentes) ===\n")
    for defending in sorted(by_defending, key=lambda t: names.get(t, t)):
        mults = by_defending[defending]
        immune = sorted(t for t, m in mults.items() if m == 0.0)
        resists = sorted(t for t, m in mults.items() if m == 0.5)
        weak = sorted(t for t, m in mults.items() if m == 2.0)
        weak4 = sorted(t for t, m in mults.items() if m == 4.0)
        print(f"{names.get(defending, defending)} ({defending})")
        if weak4:
            print(f"  x4 débil:  {', '.join(names.get(t, t) for t in weak4)}")
        if weak:
            print(f"  x2 débil:  {', '.join(names.get(t, t) for t in weak)}")
        if resists:
            print(f"  x0.5 resiste: {', '.join(names.get(t, t) for t in resists)}")
        if immune:
            print(f"  x0 inmune: {', '.join(names.get(t, t) for t in immune)}")
        print()


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def build(skip_abilities: bool) -> None:
    print("Construyendo mapa de generaciones...")
    gen_name_to_num, _ = build_generations()

    print("Construyendo tipos y damage_relations (actuales e históricas)...")
    types = build_types(gen_name_to_num)

    print("Construyendo tabla de efectividades por generación...")
    type_chart, _ = build_type_chart(types)
    self_check_type_chart(type_chart)

    print("Construyendo lista de especies base...")
    species = build_species(gen_name_to_num)
    print(f"  {len(species)} especies base encontradas.")

    current_types_fallback = build_current_types_fallback(types, species)

    past_types = None
    abilities = None
    current_types = current_types_fallback
    if skip_abilities:
        print("--skip-abilities: usando tipos 'actuales' para todas las generaciones "
              "(no reproduce cambios históricos de tipo por especie).")
    else:
        print(f"Consultando /pokemon/{{id}} para {len(species)} especies "
              "(habilidades + tipos históricos por especie)...")
        current_types, past_types, abilities = fetch_full_pokemon_data(species, gen_name_to_num)

    print("Calculando filas (tipos, debilidades, habilidades) por especie y generación...")
    pokemon_rows, type_rows, weakness_rows, ability_rows = build_rows(
        species, types, type_chart, current_types, past_types, abilities,
    )

    print(f"Escribiendo {DB_PATH} "
          f"({len(pokemon_rows)} pokemon, {len(type_rows)} filas de tipo, "
          f"{len(weakness_rows)} debilidades, {len(ability_rows)} habilidades)...")
    write_db(pokemon_rows, type_rows, weakness_rows, ability_rows, types, type_chart)
    print("Listo.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-abilities", action="store_true",
                         help="Build rápido (27 requests), sin historial de tipo por especie.")
    parser.add_argument("--dump-chart", type=int, metavar="GEN",
                         help="Imprime la tabla de tipos de una generación ya construida y sale.")
    args = parser.parse_args()

    if args.dump_chart is not None:
        dump_chart(args.dump_chart)
        return

    build(skip_abilities=args.skip_abilities)


if __name__ == "__main__":
    main()
