# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Objetivo del proyecto

Asistente que, mientras se juega un Pokémon en emulador, dice las debilidades de tipo del
Pokémon rival. Entrada por voz (a futuro) o texto tipeado (hoy); salida por overlay (a
futuro) o consola (hoy). El runtime **nunca llama a PokeAPI ni hace cómputo de tipos**: todo
viene precalculado por un ETL que corre aparte.

Soporta **varias generaciones configurables** (no un solo juego fijo), y está pensado para
randomlockes: las habilidades del rival se anotan como advertencia informativa, pero
**nunca** ajustan el multiplicador de debilidad, porque en un randomlocke la habilidad real
no es la de la especie original.

Estado actual: Iteración 1 (slice vertical de datos y dominio) completa e implementada.
Specs de las Iteraciones 2 (voz), 3 (overlay + TTS) y 4 (OCR/sprite matching) ya están
escritos en `docs/specs/`, pero **no implementados** -- cada uno tiene preguntas abiertas
marcadas explícitamente que hay que resolver con el usuario antes de empezar a programar
(ver "Decisiones de diseño" de cada spec). No asumir que están aprobados para implementar
sólo porque el documento existe.

## Cómo trabajamos (spec-driven)

Cada iteración se especifica **antes** de programarla, en `docs/specs/NN-nombre.md`:
contexto, decisiones, tradeoffs evaluados, criterios de verificación. El ciclo:

1. Escribir el spec en `docs/specs/`.
2. Revisar tradeoffs y alternativas descartadas con el usuario — el usuario prefiere ver las
   desventajas de una decisión, no sólo la recomendación final.
3. Implementar.
4. Verificar contra los criterios de aceptación del spec (casos dorados, tests).
5. Actualizar este archivo si cambió algo estructural (nueva capa, nueva convención).

Los specs quedan versionados en el repo a propósito: antes vivían en el almacenamiento de
Plan Mode de Claude Code (`~/.claude/plans/`), fuera de git, y el de la Iteración 1 se perdió
ahí antes de poder consultarlo de nuevo.

## Comandos

```bash
# Setup (venv recomendado; ver "Entorno" más abajo sobre dónde ubicarlo)
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"

# Reconstruir data/pokedex.db desde PokeAPI
.venv/Scripts/python.exe scripts/build_db.py                  # completo, ~1050 requests, ~5-10 min
.venv/Scripts/python.exe scripts/build_db.py --skip-abilities # rápido, ~27 requests, sin historial de tipo por especie
.venv/Scripts/python.exe scripts/build_db.py --dump-chart 3   # inspecciona la tabla de tipos de una generación ya construida

# Tests
.venv/Scripts/python.exe -m pytest -q                                    # toda la suite
.venv/Scripts/python.exe -m pytest tests/test_resolve_at.py -v           # un archivo
.venv/Scripts/python.exe -m pytest tests/test_resolve_at.py::test_resolve_at_picks_smallest_past_generation_gte_target -v  # un test puntual

# Correr la app
.venv/Scripts/python.exe main.py
```

Comandos del REPL una vez adentro: `<nombre>` (consulta), `gen <n>` (cambia generación
activa), `hab <nombre>` (consulta una habilidad suelta), `ayuda`, `salir`.

## Entorno

- Requiere **Python 3.12** (wheels estables de PyQt6/faster-whisper en iteraciones
  siguientes; no 3.13).
- El proyecto vive dentro de una carpeta sincronizada por OneDrive. El `.venv` actual
  también está ahí — es una decisión consciente y conocida (no un descuido): OneDrive
  sincroniza igualmente los archivos del venv aunque `.gitignore` los excluya de git, lo
  que puede hacer más lento el sync o, rara vez, bloquear un archivo mientras Python lo
  usa. Si eso empieza a molestar en la práctica, mover `.venv` fuera del árbol de OneDrive
  es el fix (no requiere cambiar código, nada referencia la ruta del venv).
- GPU AMD (RX 6700) → **sin backend CUDA** para `faster-whisper`/CTranslate2. La iteración
  de voz corre en CPU; medir rendimiento real antes de fijar el tamaño del modelo Whisper
  (ver `docs/specs/01-nucleo-datos.md`, Apéndice A).

## Arquitectura

Hexagonal (ports & adapters), cuatro capas con una sola dirección de dependencia:

```
domain/  ←  ports/  ←  service/  ←  adapters/, main.py
```

- **`domain/`** (`pokemon.py`, `exceptions.py`): entidades puras, cero dependencias externas
  (ni `sqlite3`, ni `requests`). `Pokemon` es la especie **en una generación puntual** — la
  misma especie produce objetos distintos según la generación consultada, porque sus tipos
  pueden cambiar (Magnemite, Clefairy). `AbilityCaveat` es un tipo separado de `Weakness` a
  propósito: estructuralmente no hay forma de que una habilidad toque un multiplicador.
- **`ports/`**: `Protocol`s sin implementación. `PokemonRepository`, `NameMatcher`,
  `Notifier` tienen adapter ya escrito; `Transcriber` (voz, iteración 2) y `ScreenReader`
  (OCR, iteración 4) están definidos pero sin adapter todavía.
- **`adapters/`**: una implementación concreta por port, agrupadas en subcarpetas
  (`repository/`, `matcher/`, `notifier/`). Ninguna clase declara `implements` — Python usa
  tipado estructural (`Protocol`): basta con tener los métodos correctos.
- **`service/weakness_service.py`**: la única lógica de negocio. Depende sólo de ports, se
  testea con fakes (`tests/fakes.py`), nunca con SQLite real.
- **`main.py`**: composition root + REPL. No hay `controller/` todavía — sin voz ni visión,
  el REPL cumple ese rol directo. El primer controller real (`VoiceController`) llega en la
  Iteración 2.

**Flujo de datos de punta a punta:**
`scripts/build_db.py` (ETL, corre aparte, una vez) → PokeAPI → `data/pokedex.db` (SQLite,
read-only en runtime) → `SqlitePokemonRepository` → `WeaknessService` → `Notifier`.

**El invariante más importante de todo el proyecto** vive en `scripts/build_db.py`, función
`resolve_at()`: PokeAPI codifica historial de tipos con la convención "esta entrada valió
**hasta e incluyendo** la generación G". La regla correcta es tomar la entrada con la
generación **más chica que sea ≥ la buscada**, no "la más grande ≤" (que es lo intuitivo y
está mal). El test `test_resolve_at_wrong_rule_would_fail_this_case` en
`tests/test_resolve_at.py` existe específicamente para que nadie reintroduzca la regla
incorrecta sin darse cuenta. Detalle completo en `docs/specs/01-nucleo-datos.md`, Apéndice E.

**Simplificaciones deliberadas y conocidas** (no son bugs):
- Nombres de habilidad sin efecto curado se muestran en inglés prettificado ("Flash Fire"),
  no hay traducción al español (costaría ~367 requests extra a `/ability/{id}`).
- La tabla `abilities` no resuelve `past_abilities` por generación; guarda las habilidades
  "actuales" para todas las generaciones donde la especie existe.

## Datos

`data/pokedex.db` y `data/.cache/` (caché en disco de las respuestas de PokeAPI, ~1052
archivos) están en `.gitignore` -- son 100% reproducibles corriendo el ETL de nuevo. No
commitear ninguno de los dos.
