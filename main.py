"""Composition root. Instancia los adapters concretos, los inyecta en el
service, y corre un REPL por consola.

No hay controller para esta iteración: sin voz (iteración 2) ni visión
(iteración 4) todavía, el REPL es el único punto de entrada y habla
directo con el service -- exactamente lo que pedía el prompt original para
este alcance.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from adapters.matcher.rapidfuzz_name_matcher import RapidFuzzNameMatcher
from adapters.notifier.console_notifier import ConsoleNotifier
from adapters.repository.sqlite_pokemon_repository import SqlitePokemonRepository
from domain.exceptions import PokemonNotFoundError
from service.weakness_service import ABILITIES_MODES, WeaknessService

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "pokedex.db"
CONFIG_PATH = ROOT / "config.toml"

HELP = """\
Comandos:
  <nombre>       muestra las debilidades del Pokémon (admite errores de tipeo)
  gen <n>        cambia la generación activa (1-9)
  hab <nombre>   consulta el efecto de una habilidad suelta
  ayuda          muestra este mensaje
  salir          termina el programa
"""


def load_config() -> tuple[int, str]:
    with CONFIG_PATH.open("rb") as f:
        config = tomllib.load(f)
    generation = int(config.get("generation", 3))
    abilities_mode = config.get("abilities", {}).get("mode", "canonical")
    if abilities_mode not in ABILITIES_MODES:
        print(f"config.toml: abilities.mode {abilities_mode!r} inválido, uso 'canonical'.")
        abilities_mode = "canonical"
    return generation, abilities_mode


def main() -> None:
    if not DB_PATH.exists():
        print(f"No existe {DB_PATH}.")
        print("Corré primero: python scripts/build_db.py")
        raise SystemExit(1)

    generation, abilities_mode = load_config()
    repository = SqlitePokemonRepository(DB_PATH)
    matcher = RapidFuzzNameMatcher()
    notifier = ConsoleNotifier()
    service = WeaknessService(repository, matcher, generation, abilities_mode)

    print(f"Asistente de debilidades Pokémon — Gen {service.generation}, "
          f"habilidades: {service.abilities_mode}")
    print(HELP)

    try:
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if not line:
                continue

            lowered = line.lower()
            if lowered in ("salir", "exit", "quit"):
                break
            if lowered in ("ayuda", "help", "?"):
                print(HELP)
                continue

            if lowered.startswith("gen "):
                _handle_gen(service, line[4:].strip())
                continue

            if lowered.startswith("hab "):
                _handle_ability(service, notifier, line[4:].strip())
                continue

            _handle_pokemon_query(service, notifier, line)
    finally:
        repository.close()


def _handle_gen(service: WeaknessService, arg: str) -> None:
    try:
        generation = int(arg)
    except ValueError:
        print(f"'{arg}' no es un número de generación válido.")
        return
    if not 1 <= generation <= 9:
        print("La generación debe estar entre 1 y 9.")
        return
    service.generation = generation
    print(f"Generación activa: {generation}")


def _handle_ability(service: WeaknessService, notifier: ConsoleNotifier, arg: str) -> None:
    if not arg:
        print("Uso: hab <nombre de la habilidad>")
        return
    ability = service.get_ability_info(arg)
    if ability is None:
        print(f"No se encontró la habilidad '{arg}'.")
        return
    notifier.notify_ability_info(ability)


def _handle_pokemon_query(service: WeaknessService, notifier: ConsoleNotifier, query: str) -> None:
    try:
        report = service.get_report(query)
    except PokemonNotFoundError:
        print(f"No encontré un Pokémon para '{query}' en la generación {service.generation}.")
        return
    notifier.notify_weakness_report(report)


if __name__ == "__main__":
    main()
