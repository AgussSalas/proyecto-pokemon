"""Adapter: implementa PokemonRepository contra data/pokedex.db.

Conexión de sólo lectura -- el runtime nunca escribe la DB, sólo la lee
(la escribe scripts/build_db.py). Ver esquema en la sección 1 del plan.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from domain.pokemon import AbilityCaveat, Pokemon, Weakness


def _prettify_ability_slug(slug: str) -> str:
    """'flash-fire' -> 'Flash Fire'. No hay traducción al español disponible
    sin ~367 requests extra a /ability/{id} (fuera de presupuesto de esta
    iteración); las habilidades curadas en ability_type_effects sí tienen
    su nombre en español embebido en `note_es`."""
    return slug.replace("-", " ").title()


class SqlitePokemonRepository:
    def __init__(self, db_path: Path | str) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def all_names(self) -> tuple[str, ...]:
        rows = self._conn.execute("SELECT name FROM pokemon ORDER BY name").fetchall()
        return tuple(row["name"] for row in rows)

    def get_pokemon(self, name: str, generation: int) -> Pokemon | None:
        row = self._conn.execute(
            "SELECT id, name, gen_introduced FROM pokemon WHERE name = ?", (name,)
        ).fetchone()
        if row is None or row["gen_introduced"] > generation:
            return None

        type_rows = self._conn.execute(
            """
            SELECT pt.type, tn.name_es
            FROM pokemon_types pt JOIN type_names tn ON tn.type = pt.type
            WHERE pt.pokemon_id = ? AND pt.generation = ?
            ORDER BY pt.slot
            """,
            (row["id"], generation),
        ).fetchall()
        if not type_rows:
            return None

        return Pokemon(
            id=row["id"],
            name=row["name"],
            generation=generation,
            types=tuple(t["type"] for t in type_rows),
            type_names_es=tuple(t["name_es"] for t in type_rows),
        )

    def get_weaknesses(self, pokemon_id: int, generation: int) -> tuple[Weakness, ...]:
        rows = self._conn.execute(
            """
            SELECT w.weak_type, tn.name_es, w.multiplier
            FROM weaknesses w JOIN type_names tn ON tn.type = w.weak_type
            WHERE w.pokemon_id = ? AND w.generation = ? AND w.multiplier > 1
            ORDER BY w.multiplier DESC
            """,
            (pokemon_id, generation),
        ).fetchall()
        return tuple(
            Weakness(type_slug=r["weak_type"], type_name_es=r["name_es"], multiplier=r["multiplier"])
            for r in rows
        )

    def get_ability_caveats(self, pokemon_id: int, generation: int) -> tuple[AbilityCaveat, ...]:
        rows = self._conn.execute(
            "SELECT ability, is_hidden FROM abilities WHERE pokemon_id = ? AND generation = ? ORDER BY slot",
            (pokemon_id, generation),
        ).fetchall()
        return tuple(self._build_ability_caveat(r["ability"], bool(r["is_hidden"])) for r in rows)

    def get_ability_effect(self, ability_name: str) -> AbilityCaveat | None:
        slug = ability_name.strip().lower().replace(" ", "-")
        exists = self._conn.execute(
            "SELECT 1 FROM abilities WHERE ability = ? LIMIT 1", (slug,)
        ).fetchone()
        if exists is None:
            return None
        return self._build_ability_caveat(slug, is_hidden=False)

    def _build_ability_caveat(self, slug: str, is_hidden: bool) -> AbilityCaveat:
        effect_rows = self._conn.execute(
            "SELECT note_es, is_approx FROM ability_type_effects WHERE ability = ?",
            (slug,),
        ).fetchall()
        if effect_rows:
            note = " / ".join(r["note_es"] for r in effect_rows)
            is_approx = any(bool(r["is_approx"]) for r in effect_rows)
        else:
            note = None
            is_approx = False
        return AbilityCaveat(
            ability_slug=slug,
            display_name=_prettify_ability_slug(slug),
            is_hidden=is_hidden,
            effect_note_es=note,
            is_approx=is_approx,
        )
