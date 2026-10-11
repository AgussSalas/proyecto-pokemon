> **Nota de retro-portado (2026-10-11):** este spec se escribió y aprobó el
> 2026-08-22 en Plan Mode de Claude Code, y vivió en
> `~/.claude/plans/quiero-que-hagamos-un-snazzy-dijkstra.md` -- fuera del
> repo, sin versionar. Para cuando se retomó el proyecto, ese archivo ya
> no existía (Claude Code limpia los archivos de Plan Mode con el tiempo).
> Se reconstruyó desde el historial de la conversación original para que
> quede como registro permanente, versionado junto al código. Incluye una
> corrección hecha el mismo día, después de la implementación: los valores
> de Charizard Gen 1 y Magnemite Gen 2 en la tabla de verificación estaban
> mal calculados a mano (ver nota al pie de esa tabla). El resto del
> contenido es el original, sin reescribir.
>
> **Esta es la razón concreta por la que, de ahora en más, los specs de
> cada iteración se escriben directamente en `docs/specs/` dentro del
> repo, no en el almacenamiento de Plan Mode.**

# Iteración 1 — Núcleo de datos y dominio (slice vertical)

## Contexto

Queremos un asistente que, mientras jugás un Pokémon en emulador, te diga las debilidades
del rival. El objetivo final es voz → overlay, pero el proyecto arranca en cero: la carpeta
sólo tiene el prompt de diseño.

Esta iteración construye el **slice vertical más fino que ya sirve**: ETL desde PokeAPI →
SQLite → dominio → ports → service → CLI por consola. Entrada por texto tipeado en vez de
voz, salida por consola en vez de overlay. Al terminar tenés algo usable con alt-tab, y
—más importante— el diseño de ports queda validado de punta a punta antes de meter
hardware (micrófono, hotkeys, GUI) en la ecuación.

Decisiones tomadas con vos: alcance = slice vertical fino; generación = **configurable**;
habilidades = **incluidas, pero anotadas con su efecto y nunca aplicadas automáticamente**
(porque en randomlockes las habilidades no son las del Pokémon original).

## Hallazgos de la investigación que cambian el plan

Verificados contra PokeAPI y el código fuente de `faster-whisper`, no de memoria:

1. **No hay Python instalado.** `python` en PATH es sólo el alias del Microsoft Store. Paso 0.
2. **GPU AMD RX 6700 → no hay CUDA.** Relevante para la iteración 2 (Whisper irá en CPU
   con `compute_type="int8"`). No afecta esta iteración.
3. **`/type/{id}` ya trae el array `pokemon` completo con `slot`.** 18 requests bastan para
   armar el mapa Pokémon→tipos actual y toda la tabla de efectividades. No hacen falta
   ~1300 llamadas para eso.
4. **`/type/{id}.names` trae el nombre del tipo en español** ("Roca", "Lucha", "Siniestro").
   Gratis, sin diccionario hardcodeado.
5. **`past_damage_relations` existe** → se reconstruye la tabla de tipos de cada generación.
6. **`past_types` y `past_abilities` existen en el recurso Pokemon** (confirmado en
   `pokemon_v2/serializers.py`), con forma `{generation, types:[{slot, type}]}`. Sin esto,
   la opción "configurable por generación" daría respuestas incorrectas: Magnemite era
   Eléctrico puro en Gen 1, Clefairy era Normal hasta Gen 5.
7. **`/ability/{id}` describe el efecto sólo como texto libre** (en/de/fr, sin español),
   sin ningún campo estructurado tipo `type_affected`. **No se puede derivar
   automáticamente qué tipo afecta una habilidad.** → tabla curada a mano, ~18 entradas.

## Decisiones de diseño de esta iteración

### 1. El esquema SQLite acordado necesita cambiar (justificación)

El esquema del prompt asume tipos fijos por Pokémon (`type1`, `type2` en la tabla
`pokemon`). Al elegir "configurable por generación" eso deja de ser cierto: los tipos, las
habilidades y la propia tabla de efectividades varían por generación. Los tipos se mueven a
su propia tabla y `generation` entra en la clave primaria de todo lo que varía.

```sql
CREATE TABLE pokemon (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,          -- 'charizard' (slug de PokeAPI)
    gen_introduced INTEGER NOT NULL
);

CREATE TABLE pokemon_types (               -- reemplaza type1/type2
    pokemon_id INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    slot       INTEGER NOT NULL,
    type       TEXT NOT NULL,
    PRIMARY KEY (pokemon_id, generation, slot)
);

CREATE TABLE weaknesses (                  -- precalculado, como se acordó
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

CREATE TABLE type_names (                  -- de /type/{id}.names, idioma es
    type TEXT PRIMARY KEY,
    name_es TEXT NOT NULL
);

CREATE TABLE type_chart (                  -- intermedio del ETL, se persiste
    generation      INTEGER NOT NULL,
    attacking_type  TEXT NOT NULL,
    defending_type  TEXT NOT NULL,
    multiplier      REAL NOT NULL,
    PRIMARY KEY (generation, attacking_type, defending_type)
);

CREATE TABLE ability_type_effects (        -- CURADA A MANO, no viene de PokeAPI
    ability       TEXT NOT NULL,
    affected_type TEXT,                    -- NULL = aplica a todos los tipos
    kind          TEXT NOT NULL,           -- 'immune' | 'multiply' | 'special'
    factor        REAL,                    -- para 'multiply': 0.5, 0.75, 2.0
    note_es       TEXT NOT NULL,
    is_approx     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ability, affected_type, kind)
);
```

**Guardamos los 18 multiplicadores por Pokémon, no sólo los > 1.** Cuesta nada y te habilita
mostrar resistencias e inmunidades sin re-correr el ETL. El filtro `multiplier > 1` queda en
la query, tal como estaba acordado.

`type_chart` se persiste (9 gens × 18 × 18 ≈ 2.9k filas) porque es el intermedio natural del
ETL y hace la matemática auditable y testeable sin red.

Tamaño total estimado: ~97k filas en `weaknesses`, unos pocos MB. Irrelevante para SQLite.

Query de runtime (sigue sin cómputo y sin red, sólo suma `generation`):
```sql
SELECT w.weak_type, t.name_es, w.multiplier
FROM weaknesses w JOIN type_names t ON t.type = w.weak_type
WHERE w.pokemon_id = ? AND w.generation = ? AND w.multiplier > 1
ORDER BY w.multiplier DESC;
```

### 2. Habilidades: se anotan, nunca se aplican

Por tu punto de randomlockes, y porque de todos modos **no podés saber cuál de las 2-3
habilidades tiene el rival**, el multiplicador que devuelve el sistema es siempre el de
tipos puros. Las habilidades salen como *advertencias* aparte:

```
Charizard (Fuego/Volador) — Gen 3
  ×4  Roca
  ×2  Agua, Eléctrico
  ⚠ Si tiene Mar Llamas: nada (no afecta tipos)
  ⚠ Si tiene Absorbe Fuego: inmune a Fuego
```

Config `abilities.mode` en `config.toml`:
- `canonical` — muestra las habilidades reales de la especie (juego normal).
- `randomized` — **no** muestra habilidades por especie (serían mentira en un randomlocke);
  deja disponible el comando `hab <nombre>` del CLI para consultar una habilidad suelta.
- `off` — sin advertencias.

`ability_type_effects` se curan a mano (~18 filas), en `scripts/ability_effects.py` como
constante y se vuelcan a la DB en el ETL. Cubre: `levitate`, `flash-fire`, `water-absorb`,
`volt-absorb`, `lightning-rod`, `motor-drive`, `storm-drain`, `sap-sipper`, `dry-skin`,
`earth-eater`, `well-baked-body`, `thick-fat`, `heatproof`, `water-bubble`, `fluffy`,
`purifying-salt`, `filter`/`solid-rock`/`prism-armor`, `wonder-guard`. Las que dependen del
*movimiento* y no del tipo (`bulletproof`, `soundproof`, `wind-rider`) van con
`is_approx = 1` y nota aclaratoria. Las que dependen de HP (`multiscale`) se excluyen.

### 3. El fuzzy match va detrás de un port, no suelto en el service

`WeaknessService` no importa `rapidfuzz` directo. Se define un port `NameMatcher` con un
adapter `RapidFuzzNameMatcher`. Razón: en la iteración 2 la calidad del match sobre lo que
transcribe Whisper va a ser *el* problema difícil, y vas a querer probar un matcher fonético
en español contra el de Levenshtein sin tocar el service. Además hace los tests del service
deterministas.

### 4. Layout

Se respeta **exactamente** la estructura de carpetas acordada en el prompt (`domain/`,
`ports/`, `adapters/`, `service/`, `controller/`, `scripts/`, `data/`, `main.py` en la raíz).
Considerado y descartado: envolver todo en un paquete `pokemon_assistant/`. No vale la
fricción ahora; si más adelante empaquetamos, es un refactor mecánico.

## Archivos a crear

```
pyproject.toml                     # deps de esta iteración: requests, rapidfuzz, pytest
config.toml                        # generation = 3, abilities.mode = "canonical"
domain/pokemon.py                  # Pokemon, Weakness, AbilityCaveat, WeaknessReport
domain/exceptions.py               # PokemonNotFoundError, etc.
ports/pokemon_repository.py        # Protocol
ports/name_matcher.py              # Protocol  (nuevo respecto del prompt)
ports/notifier.py                  # Protocol
ports/transcriber.py               # Protocol — definido, sin adapter (iteración 2)
ports/screen_reader.py             # Protocol — definido, sin adapter (iteración 4)
adapters/repository/sqlite_pokemon_repository.py
adapters/matcher/rapidfuzz_name_matcher.py
adapters/notifier/console_notifier.py
service/weakness_service.py
scripts/ability_effects.py         # tabla curada a mano
scripts/build_db.py                # ETL
main.py                            # composition root + REPL
tests/                              # fakes de los ports + fixtures JSON del ETL
```

`domain/` extiende lo acordado con `AbilityCaveat` y `WeaknessReport` — consecuencia directa
de la decisión de anotar habilidades sin aplicarlas.

## Plan de ejecución (en este orden)

**Paso 0 — Entorno.** Instalar **Python 3.12** desde python.org (no el del Microsoft Store:
el actual sólo intercepta el PATH y su filesystem sandboxeado da problemas). 3.12 y no 3.13
por wheels estables de PyQt6 / faster-whisper, que llegan en iteraciones siguientes.
Después: `git init`, venv, `pip install -e .`.

**Paso 1 — ETL (`scripts/build_db.py`).** El grueso del trabajo.
- Presupuesto de requests: `/generation/{1..9}` (9, mapa especie→gen) + `/type/{1..18}` (18,
  efectividades actuales e históricas + nombres es + mapa tipos actual) + `/pokemon/{id}`
  (~1025, sólo para habilidades y `past_types`) ≈ **1050 requests**.
- **Caché en disco** (`data/.cache/*.json`) + reintentos + reanudación. Con caché frío
  ~5-10 min; en frío se corre una vez sola. Throttle cortés (la fair-use policy de PokeAPI
  pide cachear; no hay rate limit formal desde 2018, pero banean por abuso).
- Flag `--skip-abilities` para tener una DB funcionando en ~30 segundos (sólo 27 requests) y
  poder avanzar con el resto mientras corre el ETL completo.
- Reconstrucción histórica: ver **Apéndice E**. Es el 70% del riesgo de esta iteración.
  Se implementa con una única función `resolve_at(past_entries, current, gen)` compartida
  por `past_types` y `past_damage_relations`, más validación cruzada y volcado inspeccionable.
- Descartado: el endpoint GraphQL (`https://graphql.pokeapi.co/v1beta2`) resolvería esto en
  1-2 queries, pero es beta declarada, tiene límite de 100 llamadas/hora y corre en una
  e2-micro con reinicio diario. REST estático es más aburrido y más confiable.

**Paso 2 — Dominio y ports.** Dataclasses `frozen=True`, `Protocol` sin implementación.

**Paso 3 — `SqlitePokemonRepository`.** Conexión read-only
(`file:...?mode=ro`), índice por `name`.

**Paso 4 — `WeaknessService`.** Recibe repo + matcher + generación. Devuelve `WeaknessReport`.
Depende sólo de ports.

**Paso 5 — `ConsoleNotifier` + `main.py`.** REPL: escribís un nombre, imprime el reporte.
Comandos `gen <n>` para cambiar de generación en caliente y `hab <nombre>` para consultar una
habilidad.

**Paso 6 — Tests.**

## Verificación

Casos elegidos porque *fallan* si la lógica por generación está mal:

| Caso | Esperado |
|---|---|
| `charizard` gen 1 | ×4 Roca; ×2 Agua, Eléctrico, **Hielo** (Fuego no resistía Hielo en Gen 1 — confirmado en Bulbapedia). **Sin** Hada |
| `magnemite` gen 1 | Eléctrico puro → ×2 Tierra |
| `magnemite` gen 2 | Eléctrico/Acero → **×4 Tierra** (ambos tipos son débiles a Tierra, se multiplican), ×2 Fuego, Lucha (`past_types` funciona) |
| `clefairy` gen 5 vs gen 6 | Normal → Hada (`past_types` en cambio de tipo) |
| `sableye` gen 5 | **Cero** debilidades |
| `sableye` gen 6 | ×2 Hada (tabla de tipos nueva) |
| **Fantasma→Psíquico gen 3** | **×2. Si sale ×0, el resolvedor usa la regla equivocada** |
| Fantasma→Psíquico gen 1 | ×0 (la rareza histórica sí aplica acá) |
| Tabla de tipos gen 1 | 15×15. Acero, Siniestro y Hada **ausentes**, no en ×1 |
| `charizar`, `pikachú` | El fuzzy match resuelve a Charizard / Pikachu |

> Nota de la corrección post-implementación: las filas de `charizard` gen 1 y `magnemite`
> gen 2 decían originalmente "×2 Agua, Eléctrico" y "×2 Tierra, Fuego, Lucha" -- estaban mal
> calculadas a mano, sin tener en cuenta que los multiplicadores de tipos dobles se
> **multiplican** entre sí (no se toma el máximo) y sin la rareza histórica de Gen 1 donde
> Fuego no resistía Hielo. El código resultó estar bien; lo que estaba mal era esta tabla,
> escrita por el agente antes de verificar contra Bulbapedia. Corregido el mismo día, tras
> correr el ETL completo y comparar la salida real contra una fuente independiente.

El caso de Fantasma→Psíquico en Gen 3 es el test más importante de todos: es el único que
distingue el resolvedor correcto del intuitivo-pero-roto (ver Apéndice E).

Comandos:
```bash
python scripts/build_db.py --skip-abilities && python scripts/build_db.py
```
```bash
python scripts/build_db.py --dump-chart 3
```
```bash
pytest -q
```
```bash
python main.py
```

`pytest` cubre: matemática del ETL contra fixtures JSON guardadas (sin red), el service con
fakes de `PokemonRepository`/`NameMatcher`/`Notifier`, y el repo contra una DB temporal
sembrada a mano.

## Qué queda explícitamente afuera

Iteración 2: voz (`faster-whisper` en CPU int8, `sounddevice`, hotkey; `initial_prompt` y
`hotwords` de faster-whisper sesgados con nombres de Pokémon — ambos parámetros verificados
en el source). Iteración 3: `OverlayNotifier` PyQt6 + `TtsNotifier` + `CompositeNotifier`
(ojo con el threading entre el callback de `keyboard` y el event loop de Qt: se resuelve con
señales en conexión encolada). Iteración 4: OCR / sprite matching.

---

# Apéndice — Tradeoffs evaluados

Registro de por qué se eligió cada cosa, para cuando vuelvas dentro de un mes.

## A. CUDA, AMD y rendimiento de Whisper

CUDA es la plataforma de NVIDIA para cómputo general en GPU. Whisper es una red neuronal:
su trabajo son multiplicaciones de matrices, algo mucho más rápido en GPU. `faster-whisper`
corre sobre CTranslate2, que tiene backend CPU y CUDA — **no tiene backend AMD**. Con la
RX 6700 la GPU queda sin usar.

**Por qué importa menos de lo que parece:** Whisper procesa siempre en ventanas de 30s.
Decir "Charizard" son 2s que se rellenan hasta 30 → el costo es un forward pass de tamaño
fijo, no escala con lo que hablás. Y un combate Pokémon es por turnos: el juego te espera.

Estimación (**no medida — se mide en la iteración 2**): `small` int8 en el i5-12400F,
~0.5-1.5s de fin de habla a texto. Con CUDA sería ~0.1-0.2s. ~5x más lento, <1s en absoluto.

Palancas si midiendo resulta lento, en orden:
1. Bajar a `base` o `tiny` (~3x cada escalón). Clave: abajo hay fuzzy match contra ~1000
   nombres conocidos, así que la transcripción no necesita ser buena, sino *parecida*. Un
   `base` que escribe "charizar" resuelve igual. `small` puede ser overkill.
2. `beam_size=1` (en vez de 5) y `vad_filter=True`.
3. Cargar el modelo una vez al arrancar, nunca por frase.
4. Escotilla de escape: **whisper.cpp con backend Vulkan sí funciona en AMD**. Es otra
   librería → se escribe un segundo adapter del port `Transcriber` y no se toca nada más.
   Esto es precisamente para lo que existe el port.

## B. Qué significa "tabla curada a mano"

Las filas las escribimos nosotros como literal de Python en `scripts/ability_effects.py`,
en vez de derivarlas de PokeAPI.

**Por qué es obligatorio:** PokeAPI da el efecto de Levitación como prosa en inglés
(*"This Pokémon is immune to Ground-type moves, Spikes..."*). No existe ningún campo
`{immune_to: "ground"}`. Derivarlo automáticamente exigiría parsear inglés con regex o un
LLM: frágil, y absurdo para ~18 filas que casi no cambian.

```python
ABILITY_TYPE_EFFECTS = [
    # ability,       affected_type, kind,       factor, note_es,                                  approx
    ("levitate",     "ground",     "immune",   None,  "Levitación: inmune a Tierra",              False),
    ("water-absorb", "water",      "immune",   None,  "Absorbe Agua: inmune a Agua",              False),
    ("thick-fat",    "fire",       "multiply", 0.5,   "Sebo: reduce Fuego a la mitad",            False),
    ("thick-fat",    "ice",        "multiply", 0.5,   "Sebo: reduce Hielo a la mitad",            False),
    ("fluffy",       "fire",       "multiply", 2.0,   "Peluche: recibe DOBLE de Fuego",           False),
    ("filter",       None,         "multiply", 0.75,  "Filtro: -25% a golpes súper efectivos",    False),
    ("wonder-guard", None,         "special",  None,  "Superguarda: sólo le entra súper efectivo", False),
    ("bulletproof",  None,         "special",  None,  "Antibalas: bloquea movimientos, no un tipo", True),
]
```

`thick-fat` ocupa dos filas → por eso la PK es `(ability, affected_type, kind)`.
`affected_type = NULL` significa "aplica a todos los tipos" (Filtro).
`is_approx = True` marca lo que no es honesto modelar como tipo: Antibalas bloquea
*movimientos* concretos, no el tipo Fantasma entero.

**Ventaja:** versionado, diffeable, testeable; agregar una habilidad nueva es una línea; el
runtime lee de un solo lugar. Además resuelve el español, que PokeAPI no da para efectos.

**Desventaja honesta:** son datos manuales escritos desde conocimiento, sin fuente
autoritativa que los valide. Un factor mal puesto no lo detecta nada automáticamente.
Lo que acota el daño es la decisión de no aplicarlas nunca al multiplicador: un error ahí
es cosmético (una nota mal escrita) y no corrompe los números.

## C. Entidades de dominio — a nivel código

**A favor**
- **`WeaknessReport` es la costura que hace intercambiables a los notifiers.** Console,
  Overlay y TTS reciben todos el mismo objeto. Sin entidad, cada notifier conocería la forma
  de la fila SQL y pasar a overlay en la iteración 3 tocaría lógica de negocio. Con ella, la
  iteración 3 es puramente aditiva. Es el 80% del valor.
- **Separar `AbilityCaveat` de `Weakness` codifica la decisión de randomlocke en los tipos.**
  Es imposible que una habilidad modifique un multiplicador por accidente: son tipos
  distintos. La decisión vive en el compilador, no en un comentario.
- Fakes sin SQLite para testear el service (lo que pedía el prompt); `frozen=True` da
  igualdad gratis en tests; la firma documenta el sistema.

**En contra**
- ~40-60 líneas de boilerplate de mapeo `sqlite3.Row` → dataclass, a tocar cada vez que
  cambia el esquema.
- **`WeaknessReport` no es una entidad de dominio, es un modelo de respuesta**: su forma la
  dicta la UI. Riesgo real de cajón de sastre. Un purista devolvería `Pokemon` +
  `list[Weakness]` y compondría en un presenter. Crítica legítima; se elige el agregado
  único por simplicidad a esta escala.
- Indirección al debuggear: SQL → mapeo → dataclass → service → notifier.

**Cuándo no lo haría:** si fueran 100 líneas con una sola salida. El prompt ya compromete
tres notifiers y dos controllers; la abstracción se paga sola en el segundo adapter.

## D. Entidades y esquema — a nivel base de datos

**Decisión: normalizado, 7 tablas.**

**A favor**
- La corrección multi-generación es *representable*. `type1`/`type2` no puede expresar que
  Magnemite tiene tipos distintos en Gen 1 y Gen 2. Requisito, no estética.
- `type_chart` persistido hace auditable el ETL: si Sableye Gen 5 sale mal, se consulta la
  tabla y se aísla si el bug está en construir la tabla de tipos o en combinar tipos dobles.
  La reconstrucción histórica es el código más delicado de la iteración.
- Guardar los 18 multiplicadores vuelve "mostrar resistencias" un cambio de query.

**En contra (asumido conscientemente)**
- **Redundancia masiva:** ~97k filas, la mayoría idénticas entre generaciones (Charizard
  Gen 3 == Gen 4). Un esquema "sólo cuando cambia" sería ~10x más chico. Se elige la
  redundancia para que la query siga siendo una igualdad trivial en vez de una subconsulta
  "generación más reciente ≤ N". Almacenamiento gratis, complejidad de query no.
- 4 tablas por consulta en vez de 2.
- **El ETL se complica bastante.** Con una sola generación fija, `build_db.py` sería un
  tercio del tamaño. Ese es el precio real de "configurable".

**Alternativa evaluada y descartada:** una sola tabla denormalizada
`(pokemon_id, generation, name, types_csv, weaknesses_json, abilities_json)`. Funcionaría
—la app es read-only y SQLite consulta JSON— y ahorraría mapeo. Se descarta por perder
auditabilidad del ETL y la posibilidad de consultar por tipo
("¿qué Pokémon son débiles a Lucha en Gen 4?").

## E. Reconstrucción histórica — dónde está el riesgo real

Datos reales verificados contra la API:

- **Acero** (`generation-ii`) tiene **una** entrada pasada: `generation-v` → resiste
  Fantasma y Siniestro, sin Hada.
- **Fantasma** (`generation-i`) tiene **dos**: `generation-i` (`no_damage_to: [normal,
  psychic]`) y `generation-v` (`double_damage_to: [ghost, psychic]`,
  `half_damage_to: [dark, steel]`).

### E.1 La convención es "hasta e incluyendo", y la regla es contraintuitiva

Una entrada `generation-v` **no** significa "esto es lo de Gen 5", sino **"esto valió hasta
Gen 5 inclusive"**. Por eso a Acero le alcanza una sola entrada para cubrir las gens 2 a 5.

**Regla correcta:** para la generación N, tomar la entrada pasada con la generación **más
chica que sea ≥ N**; si no hay ninguna, usar `damage_relations` actual.

**El bug que se escribe solo:** el instinto con datos históricos es "la entrada más grande
≤ N". Aplicado a Fantasma en Gen 3 (entradas [1, 5]) da `generation-i` → **Bola Sombra sin
efecto contra Alakazam en Esmeralda**. Incorrecto, silencioso, y perfectamente plausible a
la vista. La regla correcta falla sólo si no se aplica; la incorrecta falla en las gens
2, 3 y 4 — justo el rango más probable de uso.

Verificación de la regla contra los tres tramos de Fantasma:
`gen 1 → generation-i` (×0 a Psíquico) · `gen 2-5 → generation-v` (×2) ·
`gen 6+ → actual` (deja de resistir Acero). ✓

### E.2 Tipos inexistentes: excluir, no neutralizar

Acero y Siniestro son `generation-ii`; Hada es `generation-vi`. Para Gen 1 no alcanza con
que den ×1: deben **quedar fuera de la tabla**, o el reporte lista "Hada ×1" en un juego
sin Hada. Dimensiones: gen 1 = 15×15, gen 2-5 = 17×17, gen 6+ = 18×18.

### E.3 `past_types` comparte la convención

Magnemite: `generation-i → [electric]` (Eléctrico puro sólo en Gen 1).
Clefairy: `generation-v → [normal]` (Normal de gen 1 a 5).
→ **Una sola función `resolve_at()` sirve para tipos y para damage relations.** Un único
lugar donde equivocarse, un único lugar donde testear.

### E.4 Salvaguardas que salen de este análisis

1. **`resolve_at(past_entries, current, gen)` compartida**, ordenando explícitamente las
   entradas (no asumir que la API las devuelve ordenadas). Es la función más testeada del
   proyecto.
2. **Mapeo generación→número desde `/generation/{n}`** (trae `id` y `name`), en vez de
   parsear números romanos a mano.
3. **Validación cruzada gratis:** cada tipo declara `*_damage_from` y `*_damage_to`, que son
   redundantes. Se construye la tabla por ambos caminos y se assertan iguales. Atrapa
   inconsistencias en la data histórica de PokeAPI antes de que entren a la DB.
4. **`--dump-chart <gen>`**: vuelca la tabla de una generación en formato legible para
   cotejarla una vez contra Bulbapedia a ojo.
5. **Guarda:** nunca consultar el resolvedor por una generación anterior a la introducción
   del Pokémon.

### E.5 Lo que esto NO cubre

PokeAPI modela cambios de la **tabla de tipos**, no rarezas por juego, y su data histórica
es mantenida por la comunidad: puede tener huecos. La validación cruzada detecta
inconsistencia *interna*, no error factual. Los casos dorados de verificación son la única
red contra un dato equivocado en el origen.
